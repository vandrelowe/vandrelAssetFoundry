import hashlib
from pathlib import Path

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, AssetManifest, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import contained_path

APPROVAL_ROLES = ("processed_model", "godot_wrapper_scene")
PROVIDER_NATIVE_APPROVAL_ROLES = (
    "processed_animation_walk",
    "processed_animation_run",
    "godot_animation_loader_script",
)
REQUIRED_CHECKS = {
    "glb_structure",
    "geometry_present",
    "triangle_budget",
    "materials_required",
    "skeleton_required",
    "godot_sandbox_import",
}
SUSPENDED_APPROVAL_PROCESSORS = {
    "blender_rest_pose_retarget",
}


def approval_checks_pass(manifest: AssetManifest) -> bool:
    checks_by_name = {
        str(check.get("name")): bool(check.get("passed")) for check in manifest.validation.checks
    }
    processed = [item for item in manifest.artifacts if item.role == "processed_model"]
    processor_name = (
        processed[-1].processor.name if processed and processed[-1].processor is not None else None
    )
    if processor_name in SUSPENDED_APPROVAL_PROCESSORS:
        return False
    required_checks = (
        REQUIRED_CHECKS - {"glb_structure"} | {"provider_native_character_playback"}
        if processor_name == "godot_provider_native_character"
        else REQUIRED_CHECKS
    )
    standard_checks_pass = (
        manifest.validation.result == "passed"
        and required_checks.issubset(checks_by_name)
        and all(checks_by_name[name] for name in required_checks)
    )
    requires_animation_review = bool(
        processed
        and processed[-1].processor
        and processed[-1].processor.name == "blender_rest_pose_retarget"
    )
    animation_review_passes = bool(
        processed
        and any(
            check.get("name") == "animation_visual_review"
            and check.get("passed")
            and check.get("processed_model_sha256") == processed[-1].sha256
            for check in manifest.validation.checks
        )
    )
    return standard_checks_pass and (not requires_animation_review or animation_review_passes)


def approve_asset(
    config: FoundryConfig,
    asset_id: str,
    reviewer: str,
    notes: str = "",
) -> AssetManifest:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.workflow.state is not WorkflowState.REVIEW:
        raise FoundryError(f"Approval requires review state: {asset_id}")
    if not approval_checks_pass(manifest):
        raise FoundryError("Approval requires every recorded validation check to pass.")
    reviewer = reviewer.strip()
    if not reviewer:
        raise FoundryError("Approval requires a reviewer name.")
    bindings: dict[str, str] = {}
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    processed = [item for item in manifest.artifacts if item.role == "processed_model"]
    processor_name = (
        processed[-1].processor.name if processed and processed[-1].processor is not None else None
    )
    approval_roles = APPROVAL_ROLES + (
        PROVIDER_NATIVE_APPROVAL_ROLES
        if processor_name == "godot_provider_native_character"
        else ()
    )
    for role in approval_roles:
        candidates = [item for item in manifest.artifacts if item.role == role]
        if not candidates:
            raise FoundryError(f"Approval artifact role is missing: {role}")
        artifact = candidates[-1]
        _verify_artifact(asset_root, artifact)
        bindings[role] = artifact.sha256
    manifest.approval.approved = True
    manifest.approval.approved_at = utc_now()
    manifest.approval.approved_artifact_hashes = bindings
    manifest.approval.reviewer = reviewer
    manifest.approval.notes = notes.strip()
    manifest.workflow.state = WorkflowState.APPROVED
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    repository.save(
        manifest,
        "asset.approved",
        expected_revision=manifest.revision - 1,
    )
    return manifest


def reject_asset(
    config: FoundryConfig,
    asset_id: str,
    reason: str,
) -> AssetManifest:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.workflow.state not in {WorkflowState.REVIEW, WorkflowState.BLOCKED}:
        raise FoundryError(f"Rejection requires review or blocked state: {asset_id}")
    reason = reason.strip()
    if not reason:
        raise FoundryError("Rejection requires a reason.")
    manifest.approval.approved = False
    manifest.approval.approved_at = None
    manifest.approval.approved_artifact_hashes = {}
    manifest.approval.reviewer = None
    manifest.approval.notes = reason
    manifest.workflow.state = WorkflowState.REJECTED
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    repository.save(
        manifest,
        "asset.rejected",
        expected_revision=manifest.revision - 1,
    )
    return manifest


def _verify_artifact(asset_root: Path, artifact: Artifact) -> None:
    path = contained_path(asset_root, artifact.path)
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise FoundryError(
            f"Could not verify approval artifact {artifact.artifact_id}: {exc}"
        ) from exc
    if digest.hexdigest() != artifact.sha256 or size != artifact.size_bytes:
        raise FoundryError(f"Approval artifact changed: {artifact.artifact_id}")
