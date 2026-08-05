import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import AssetManifest, ProviderTask
from vandrel_foundry.domain.provider import ProviderTaskStatus
from vandrel_foundry.providers.meshy.models import (
    ImageTo3DRequest,
    RemeshRequest,
    RetextureRequest,
    RiggingRequest,
    TextTo3DPreviewRequest,
    TextTo3DRefineRequest,
)
from vandrel_foundry.services.add_reference import MAX_REFERENCE_IMAGE_BYTES
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path

MAX_MODEL_DATA_URI_BYTES = 100 * 1024 * 1024


@dataclass(frozen=True)
class PreparedSubmission:
    asset_id: str
    task_key: str
    attempt: int
    operation: str
    request: (
        TextTo3DPreviewRequest
        | TextTo3DRefineRequest
        | ImageTo3DRequest
        | RemeshRequest
        | RetextureRequest
        | RiggingRequest
    )
    request_fingerprint: str


def prepare_text_preview_submission(
    workspace_root: Path,
    manifest: AssetManifest,
) -> PreparedSubmission:
    """Build a deterministic local request without making or recording a network call."""
    if manifest.generation.provider != "meshy":
        raise FoundryError(
            f"Asset provider is {manifest.generation.provider}, not meshy: "
            f"{manifest.asset.asset_id}"
        )
    prompt_path = contained_path(
        workspace_root / "assets" / manifest.asset.asset_id,
        manifest.input.prompt_file,
    )
    try:
        prompt = prompt_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise FoundryError(f"Could not read asset prompt {prompt_path}: {exc}") from exc
    if not prompt:
        raise FoundryError(f"Asset prompt is empty: {manifest.asset.asset_id}")

    operation = "text_to_3d_preview"
    request = TextTo3DPreviewRequest(prompt=prompt)
    return _prepare(
        manifest,
        operation,
        "meshy_preview",
        request,
    )


def prepare_text_refine_submission(
    manifest: AssetManifest,
    preview_task_key: str,
    enable_pbr: bool = True,
) -> PreparedSubmission:
    if manifest.generation.provider != "meshy":
        raise FoundryError(
            f"Asset provider is {manifest.generation.provider}, not meshy: "
            f"{manifest.asset.asset_id}"
        )
    previews = [
        task
        for task in manifest.generation.tasks
        if task.task_key == preview_task_key and task.operation == "text_to_3d_preview"
    ]
    if not previews:
        raise FoundryError(f"Preview task not found: {preview_task_key}")
    preview = previews[-1]
    _require_succeeded_provider_task(preview)
    request = TextTo3DRefineRequest(
        preview_task_id=preview.provider_task_id,
        enable_pbr=enable_pbr,
    )
    return _prepare(
        manifest,
        "text_to_3d_refine",
        "meshy_refine",
        request,
    )


def prepare_image_submission(
    workspace_root: Path,
    manifest: AssetManifest,
    target_polycount: int,
    reference: RelativeManifestPath | None = None,
) -> PreparedSubmission:
    if manifest.generation.provider != "meshy":
        raise FoundryError(
            f"Asset provider is {manifest.generation.provider}, not meshy: "
            f"{manifest.asset.asset_id}"
        )
    selected = reference or (
        manifest.input.reference_images[0] if manifest.input.reference_images else None
    )
    if selected is None or selected not in manifest.input.reference_images:
        raise FoundryError("Image submission requires a recorded reference image.")
    asset_root = workspace_root / "assets" / manifest.asset.asset_id
    path = contained_path(asset_root, selected)
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise FoundryError(f"Could not read reference image {path}: {exc}") from exc
    if not content or len(content) > MAX_REFERENCE_IMAGE_BYTES:
        raise FoundryError("Recorded reference image has an invalid size.")
    suffix = path.suffix.lower()
    media_type = "image/png" if suffix == ".png" else "image/jpeg"
    encoded = base64.b64encode(content).decode("ascii")
    request = ImageTo3DRequest(
        image_url=f"data:{media_type};base64,{encoded}",
        target_polycount=target_polycount,
    )
    return _prepare(
        manifest,
        "image_to_3d",
        "meshy_image",
        request,
    )


def prepare_remesh_submission(
    manifest: AssetManifest,
    target_polycount: int,
) -> PreparedSubmission:
    if manifest.generation.provider != "meshy":
        raise FoundryError(f"Asset provider is not meshy: {manifest.asset.asset_id}")
    selected = manifest.generation.selected_task_key
    candidates = [
        task
        for task in manifest.generation.tasks
        if task.status is ProviderTaskStatus.SUCCEEDED
        and task.provider_task_id
        and (selected is None or task.task_key == selected)
        and task.operation in {"text_to_3d_preview", "text_to_3d_refine", "image_to_3d"}
    ]
    if not candidates:
        raise FoundryError("Remesh requires a selected succeeded generation task.")
    source = candidates[-1]
    request = RemeshRequest(
        input_task_id=source.provider_task_id,
        target_polycount=target_polycount,
    )
    return _prepare(manifest, "remesh", "meshy_remesh", request)


def prepare_retexture_submission(
    workspace_root: Path,
    manifest: AssetManifest,
    artifact_id: str,
    prompt: str,
    *,
    enable_pbr: bool,
    texture_resolution: str,
    task_label: str,
) -> PreparedSubmission:
    if manifest.generation.provider != "meshy":
        raise FoundryError(f"Asset provider is not meshy: {manifest.asset.asset_id}")
    matches = [item for item in manifest.artifacts if item.artifact_id == artifact_id]
    if not matches:
        raise FoundryError(f"Artifact not found: {artifact_id}")
    artifact = matches[-1]
    if artifact.format != "glb":
        raise FoundryError("Meshy retexture input must be a GLB artifact.")
    asset_root = workspace_root / "assets" / manifest.asset.asset_id
    path = contained_path(asset_root, artifact.path)
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise FoundryError(f"Could not read retexture input {artifact_id}: {exc}") from exc
    if not content or len(content) > MAX_MODEL_DATA_URI_BYTES:
        raise FoundryError("Retexture input is empty or exceeds the 100 MiB upload limit.")
    if (
        len(content) != artifact.size_bytes
        or hashlib.sha256(content).hexdigest() != artifact.sha256
    ):
        raise FoundryError(f"Retexture input no longer matches its manifest hash: {artifact_id}")
    label = task_label.strip().lower().replace("-", "_")
    if label not in {"beauty", "semantic"}:
        raise FoundryError("Retexture task label must be beauty or semantic.")
    request = RetextureRequest(
        model_url=(
            "data:application/octet-stream;base64," + base64.b64encode(content).decode("ascii")
        ),
        text_style_prompt=prompt.strip(),
        enable_pbr=enable_pbr,
        texture_resolution=texture_resolution,
    )
    return _prepare(manifest, f"retexture_{label}", f"meshy_retexture_{label}", request)


def prepare_rigging_submission(
    manifest: AssetManifest,
    retexture_task_key: str,
    height_meters: float,
) -> PreparedSubmission:
    if manifest.generation.provider != "meshy":
        raise FoundryError(f"Asset provider is not meshy: {manifest.asset.asset_id}")
    candidates = [
        task
        for task in manifest.generation.tasks
        if task.task_key == retexture_task_key and task.operation == "retexture_beauty"
    ]
    if not candidates:
        raise FoundryError(f"Beauty retexture task not found: {retexture_task_key}")
    source = candidates[-1]
    if source.status is not ProviderTaskStatus.SUCCEEDED or not source.provider_task_id:
        raise FoundryError(f"Beauty retexture task is not succeeded: {retexture_task_key}")
    request = RiggingRequest(
        input_task_id=source.provider_task_id,
        height_meters=height_meters,
    )
    return _prepare(manifest, "rigging", "meshy_rigging", request)


def _prepare(
    manifest: AssetManifest,
    operation: str,
    task_prefix: str,
    request: (
        TextTo3DPreviewRequest
        | TextTo3DRefineRequest
        | ImageTo3DRequest
        | RemeshRequest
        | RetextureRequest
        | RiggingRequest
    ),
) -> PreparedSubmission:
    prior_attempts = [
        task.attempt for task in manifest.generation.tasks if task.operation == operation
    ]
    attempt = max(prior_attempts, default=0) + 1
    canonical = json.dumps(
        request.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return PreparedSubmission(
        asset_id=manifest.asset.asset_id,
        task_key=f"{task_prefix}_{attempt:03d}",
        attempt=attempt,
        operation=operation,
        request=request,
        request_fingerprint=hashlib.sha256(canonical).hexdigest(),
    )


def _require_succeeded_provider_task(task: ProviderTask) -> None:
    if task.status is not ProviderTaskStatus.SUCCEEDED or not task.provider_task_id:
        raise FoundryError(f"Preview task is not succeeded: {task.task_key} ({task.status})")
