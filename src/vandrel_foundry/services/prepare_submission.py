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
    TextTo3DPreviewRequest,
    TextTo3DRefineRequest,
)
from vandrel_foundry.services.add_reference import MAX_REFERENCE_IMAGE_BYTES
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path


@dataclass(frozen=True)
class PreparedSubmission:
    asset_id: str
    task_key: str
    attempt: int
    operation: str
    request: TextTo3DPreviewRequest | TextTo3DRefineRequest | ImageTo3DRequest | RemeshRequest
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


def _prepare(
    manifest: AssetManifest,
    operation: str,
    task_prefix: str,
    request: TextTo3DPreviewRequest | TextTo3DRefineRequest | ImageTo3DRequest | RemeshRequest,
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
