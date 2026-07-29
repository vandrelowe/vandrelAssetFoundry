import hashlib
from pathlib import Path

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.custody_assertion import (
    current_source_inputs,
    custody_freshness,
)
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, AssetManifest, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.domain.workflow_policy import (
    approval_artifact_roles,
    approval_checks_pass,
    invalidate_approval,
    transition_workflow,
)
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import contained_path


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
    custody_fresh, custody_blockers = custody_freshness(manifest)
    if not custody_fresh:
        raise FoundryError(
            "Approval requires evaluated, documented, fresh custody: " + ", ".join(custody_blockers)
        )
    reviewer = reviewer.strip()
    if not reviewer:
        raise FoundryError("Approval requires a reviewer name.")
    bindings: dict[str, str] = {}
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    for role in approval_artifact_roles(manifest):
        candidates = [item for item in manifest.artifacts if item.role == role]
        if not candidates:
            raise FoundryError(f"Approval artifact role is missing: {role}")
        artifact = candidates[-1]
        _verify_artifact(asset_root, artifact)
        bindings[role] = artifact.sha256
    assert manifest.custody is not None
    for contribution in manifest.custody.source_contributions:
        for evidence in contribution.license_evidence:
            artifact = next(
                (
                    item
                    for item in manifest.artifacts
                    if item.artifact_id == evidence.candidate_evidence_artifact_id
                ),
                None,
            )
            if artifact is None:
                raise FoundryError(f"Custody evidence artifact is missing: {evidence.binding_id}")
            _verify_artifact(asset_root, artifact)
    manifest.approval.approved = True
    manifest.approval.approved_at = utc_now()
    manifest.approval.approved_artifact_hashes = bindings
    manifest.approval.custody_assertion_sha256 = manifest.custody.semantic_assertion_sha256
    manifest.approval.custody_source_inputs = current_source_inputs(manifest)
    manifest.approval.reviewer = reviewer
    manifest.approval.notes = notes.strip()
    transition_workflow(manifest, WorkflowState.APPROVED)
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
    invalidate_approval(manifest)
    manifest.approval.notes = reason
    transition_workflow(manifest, WorkflowState.REJECTED)
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
