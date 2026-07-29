import hashlib
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import DownloadError, FoundryError
from vandrel_foundry.domain.manifest import Artifact, utc_now
from vandrel_foundry.domain.provider import ProviderTaskStatus
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.domain.workflow_policy import transition_workflow
from vandrel_foundry.providers.base import TextPreviewTransport
from vandrel_foundry.providers.redaction import redact_provider_evidence
from vandrel_foundry.services.poll_task import select_generation_task
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path
from vandrel_foundry.storage.provider_evidence import write_new_json_evidence


def download_text_preview_glb(
    config: FoundryConfig,
    asset_id: str,
    transport: TextPreviewTransport,
    task_key: str | None = None,
    environment: Mapping[str, str] | None = None,
) -> Artifact:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    task = select_generation_task(manifest, task_key)
    if task.status is not ProviderTaskStatus.SUCCEEDED or not task.provider_task_id:
        raise FoundryError(f"Task is not ready for download: {task.task_key} ({task.status})")

    variables = environment if environment is not None else os.environ
    key_name = config.providers.meshy.api_key_environment_variable
    api_key = variables.get(key_name, "")
    if not api_key:
        raise FoundryError(f"Required API key environment variable is not set: {key_name}")

    if task.operation == "image_to_3d":
        response = transport.retrieve_image_task(task.provider_task_id, api_key)
    elif task.operation == "remesh":
        response = transport.retrieve_remesh_task(task.provider_task_id, api_key)
    elif task.operation.startswith("retexture_"):
        response = transport.retrieve_retexture_task(task.provider_task_id, api_key)
    elif task.operation == "rigging":
        response = transport.retrieve_rigging_task(task.provider_task_id, api_key)
    else:
        response = transport.retrieve_text_task(task.provider_task_id, api_key)
    if response.id != task.provider_task_id:
        raise DownloadError(
            f"Provider returned task {response.id} while refreshing {task.provider_task_id}"
        )
    if response.status is not ProviderTaskStatus.SUCCEEDED:
        raise DownloadError(
            f"Provider task is no longer downloadable: {task.task_key} ({response.status})"
        )
    rigging_result = response.result if task.operation == "rigging" else None
    if task.operation == "rigging":
        model_url = rigging_result.rigged_character_glb_url if rigging_result is not None else None
    else:
        model_url = response.model_urls.get("glb")
    if not model_url:
        raise DownloadError(f"Provider task has no GLB output: {task.task_key}")

    asset_root = config.foundry.workspace_root / "assets" / asset_id
    snapshot_relative = _next_download_snapshot(asset_root, task.task_key)
    write_new_json_evidence(
        contained_path(asset_root, snapshot_relative),
        redact_provider_evidence(response.model_dump(mode="json")),
    )
    task.response_snapshots.append(snapshot_relative)
    task.progress = response.progress
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    repository.save(
        manifest,
        "provider.download_refreshed",
        expected_revision=manifest.revision - 1,
    )

    candidate_outputs = [
        ("source_model", "source", "glb", model_url),
    ]
    if rigging_result is not None and rigging_result.rigged_character_fbx_url:
        candidate_outputs.append(
            (
                "source_model",
                "source",
                "fbx",
                rigging_result.rigged_character_fbx_url,
            )
        )
    if rigging_result is not None:
        basic_animations = rigging_result.basic_animations or {}
        for key, role, file_format in (
            ("walking_glb_url", "source_animation_walk", "glb"),
            ("running_glb_url", "source_animation_run", "glb"),
            ("walking_fbx_url", "source_animation_walk", "fbx"),
            ("running_fbx_url", "source_animation_run", "fbx"),
        ):
            animation_url = basic_animations.get(key)
            if animation_url:
                candidate_outputs.append(
                    (
                        role,
                        "source",
                        file_format,
                        animation_url,
                    )
                )
    outputs = _missing_outputs(
        manifest.artifacts,
        task.task_key,
        candidate_outputs,
    )
    thumbnail_url = getattr(response, "thumbnail_url", None)
    if thumbnail_url:
        outputs.append(
            (
                "preview_thumbnail",
                "preview",
                _image_format(thumbnail_url),
                thumbnail_url,
            )
        )
    if task.operation == "retexture_semantic":
        texture_urls = getattr(response, "texture_urls", [])
        base_color = texture_urls[0].base_color if texture_urls else None
        if not base_color:
            raise DownloadError(f"Semantic retexture has no base-color texture: {task.task_key}")
        outputs.append(("semantic_mask_source", "masks", "png", base_color))
    if not outputs:
        raise DownloadError(f"All provider outputs are already downloaded: {task.task_key}")
    new_artifacts: list[Artifact] = []
    promoted_paths: list[Path] = []
    try:
        for role, stage, file_format, url in outputs:
            artifact, promoted = _download_output(
                config,
                manifest.artifacts + new_artifacts,
                asset_id,
                task.task_key,
                role,
                stage,
                file_format,
                url,
                transport,
            )
            new_artifacts.append(artifact)
            promoted_paths.append(promoted)
    except BaseException:
        for promoted in promoted_paths:
            promoted.unlink(missing_ok=True)
        raise

    manifest.artifacts.extend(new_artifacts)
    transition_workflow(manifest, WorkflowState.DOWNLOADED)
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    repository.save(
        manifest,
        "artifact.downloaded",
        expected_revision=manifest.revision - 1,
    )
    return new_artifacts[0]


def _missing_outputs(
    existing_artifacts: list[Artifact],
    task_key: str,
    candidates: list[tuple[str, str, str, str]],
) -> list[tuple[str, str, str, str]]:
    retained: list[tuple[str, str, str, str]] = []
    seen: dict[tuple[str, str], int] = {}
    existing: dict[tuple[str, str], int] = {}
    for artifact in existing_artifacts:
        if artifact.source_task_key != task_key:
            continue
        key = (artifact.role, artifact.format)
        existing[key] = existing.get(key, 0) + 1
    for candidate in candidates:
        key = (candidate[0], candidate[2])
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > existing.get(key, 0):
            retained.append(candidate)
    return retained


def _download_output(
    config: FoundryConfig,
    existing_artifacts: list[Artifact],
    asset_id: str,
    task_key: str,
    role: str,
    stage: str,
    file_format: str,
    url: str,
    transport: TextPreviewTransport,
) -> tuple[Artifact, Path]:
    number = sum(artifact.role == role for artifact in existing_artifacts) + 1
    prefixes = {
        ("source_model", "glb"): "source_glb",
        ("source_model", "fbx"): "source_fbx",
        ("source_animation_walk", "glb"): "source_animation_walk_glb",
        ("source_animation_walk", "fbx"): "source_animation_walk_fbx",
        ("source_animation_run", "glb"): "source_animation_run_glb",
        ("source_animation_run", "fbx"): "source_animation_run_fbx",
        "preview_thumbnail": "thumbnail",
        "semantic_mask_source": "semantic_mask_source",
    }
    prefix = prefixes.get((role, file_format), prefixes.get(role))
    if prefix is None:
        raise DownloadError(f"Unsupported provider output role and format: {role}/{file_format}")
    artifact_id = f"{prefix}_{number:03d}"
    final_relative = RelativeManifestPath(f"{stage}/{task_key}/{artifact_id}.{file_format}")
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    final_path = contained_path(asset_root, final_relative)
    if final_path.exists():
        raise DownloadError(f"Artifact destination already exists: {final_path}")
    final_path.parent.mkdir(parents=True, exist_ok=True)

    temp_root = config.foundry.workspace_root / "temp"
    temp_root.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temporary = tempfile.mkstemp(
        prefix=f"{asset_id}-{task_key}-",
        suffix=".part",
        dir=temp_root,
    )
    os.close(descriptor)
    temporary = Path(raw_temporary)
    temporary.unlink()
    try:
        reported_size = transport.download_file(url, temporary)
        actual_size = temporary.stat().st_size
        if actual_size <= 0 or reported_size != actual_size:
            raise DownloadError(
                f"Downloaded size mismatch: transport={reported_size}, file={actual_size}"
            )
        digest = _sha256(temporary)
        try:
            os.link(temporary, final_path)
        except FileExistsError as exc:
            raise DownloadError(f"Artifact destination already exists: {final_path}") from exc
    finally:
        temporary.unlink(missing_ok=True)

    return (
        Artifact(
            artifact_id=artifact_id,
            role=role,
            stage=stage,
            format=file_format,
            path=final_relative,
            sha256=digest,
            size_bytes=actual_size,
            derived_from=[],
            source_task_key=task_key,
        ),
        final_path,
    )


def _next_download_snapshot(asset_root: Path, task_key: str) -> RelativeManifestPath:
    number = 1
    while True:
        relative = RelativeManifestPath(
            f"provider/meshy/responses/{task_key}.download_{number:03d}.json"
        )
        if not contained_path(asset_root, relative).exists():
            return relative
        number += 1


def _image_format(url: str) -> str:
    suffix = Path(urlsplit(url).path).suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "jpg"
    return "png"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
