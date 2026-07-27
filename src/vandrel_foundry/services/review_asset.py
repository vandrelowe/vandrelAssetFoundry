import hashlib
from pathlib import Path

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, AssetManifest, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import contained_path

APPROVAL_ROLES = ("processed_model", "godot_wrapper_scene")
REQUIRED_CHECKS = {
    "glb_structure",
    "triangle_budget",
    "materials_required",
    "skeleton_required",
    "godot_sandbox_import",
}


def approval_checks_pass(manifest: AssetManifest) -> bool:
    checks_by_name = {
        str(check.get("name")): bool(check.get("passed")) for check in manifest.validation.checks
    }
    return (
        manifest.validation.result == "passed"
        and REQUIRED_CHECKS.issubset(checks_by_name)
        and all(checks_by_name[name] for name in REQUIRED_CHECKS)
    )


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
    for role in APPROVAL_ROLES:
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
    if manifest.workflow.state is not WorkflowState.REVIEW:
        raise FoundryError(f"Rejection requires review state: {asset_id}")
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
