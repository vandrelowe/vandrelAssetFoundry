"""Neutral workflow-transition and approval policy for Foundry candidates."""

from __future__ import annotations

from typing import TYPE_CHECKING

from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.states import WorkflowState

if TYPE_CHECKING:
    from vandrel_foundry.domain.manifest import AssetManifest


BASE_APPROVAL_ROLES = ("processed_model", "godot_wrapper_scene")
PROVIDER_NATIVE_APPROVAL_ROLES = (
    "processed_animation_walk",
    "processed_animation_run",
    "godot_animation_loader_script",
)
REQUIRED_APPROVAL_CHECKS = frozenset(
    {
        "glb_structure",
        "geometry_present",
        "triangle_budget",
        "materials_required",
        "skeleton_required",
        "godot_sandbox_import",
    }
)
SUSPENDED_APPROVAL_PROCESSORS = frozenset({"blender_rest_pose_retarget"})
PROVIDER_NATIVE_PROCESSOR = "godot_provider_native_character"


ALLOWED_WORKFLOW_TRANSITIONS: dict[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.DRAFT: frozenset(
        {
            WorkflowState.DRAFT,
            WorkflowState.SUBMITTED,
            WorkflowState.DOWNLOADED,
        }
    ),
    WorkflowState.SUBMITTED: frozenset(
        {
            WorkflowState.DRAFT,
            WorkflowState.SUBMITTED,
            WorkflowState.GENERATING,
            WorkflowState.SOURCE_READY,
            WorkflowState.BLOCKED,
        }
    ),
    WorkflowState.GENERATING: frozenset(
        {
            WorkflowState.GENERATING,
            WorkflowState.SOURCE_READY,
            WorkflowState.BLOCKED,
        }
    ),
    WorkflowState.SOURCE_READY: frozenset(
        {
            WorkflowState.SUBMITTED,
            WorkflowState.DOWNLOADED,
        }
    ),
    WorkflowState.DOWNLOADED: frozenset(
        {
            WorkflowState.SUBMITTED,
            WorkflowState.PROCESSED,
            WorkflowState.REVIEW,
            WorkflowState.BLOCKED,
        }
    ),
    WorkflowState.PROCESSED: frozenset(
        {
            WorkflowState.SUBMITTED,
            WorkflowState.PROCESSED,
            WorkflowState.STAGED,
            WorkflowState.REVIEW,
            WorkflowState.BLOCKED,
        }
    ),
    WorkflowState.STAGED: frozenset(
        {
            WorkflowState.PROCESSED,
            WorkflowState.REVIEW,
            WorkflowState.BLOCKED,
        }
    ),
    WorkflowState.REVIEW: frozenset(
        {
            WorkflowState.SUBMITTED,
            WorkflowState.PROCESSED,
            WorkflowState.REVIEW,
            WorkflowState.APPROVED,
            WorkflowState.REJECTED,
            WorkflowState.BLOCKED,
        }
    ),
    WorkflowState.APPROVED: frozenset(
        {
            WorkflowState.PROCESSED,
            WorkflowState.REVIEW,
            WorkflowState.BLOCKED,
        }
    ),
    WorkflowState.REJECTED: frozenset(
        {
            WorkflowState.SUBMITTED,
            WorkflowState.REVIEW,
            WorkflowState.BLOCKED,
        }
    ),
    WorkflowState.BLOCKED: frozenset(
        {
            WorkflowState.SUBMITTED,
            WorkflowState.REVIEW,
            WorkflowState.REJECTED,
            WorkflowState.BLOCKED,
        }
    ),
}


def transition_workflow(manifest: AssetManifest, target: WorkflowState) -> None:
    """Apply one explicitly allowed in-memory workflow transition."""
    source = manifest.workflow.state
    if target not in ALLOWED_WORKFLOW_TRANSITIONS[source]:
        raise FoundryError(f"Illegal workflow transition: {source.value} -> {target.value}")
    manifest.workflow.state = target


def invalidate_approval(manifest: AssetManifest) -> None:
    """Clear the complete approval tuple after approval-affecting candidate change."""
    manifest.approval.approved = False
    manifest.approval.approved_at = None
    manifest.approval.approved_artifact_hashes = {}
    manifest.approval.custody_assertion_sha256 = None
    manifest.approval.custody_source_inputs = []
    manifest.approval.reviewer = None
    manifest.approval.notes = ""


def approval_artifact_roles(manifest: AssetManifest) -> tuple[str, ...]:
    processor_name = _current_processed_model_processor(manifest)
    return BASE_APPROVAL_ROLES + (
        PROVIDER_NATIVE_APPROVAL_ROLES if processor_name == PROVIDER_NATIVE_PROCESSOR else ()
    )


def approval_checks_pass(manifest: AssetManifest) -> bool:
    checks_by_name = {
        str(check.get("name")): bool(check.get("passed")) for check in manifest.validation.checks
    }
    processor_name = _current_processed_model_processor(manifest)
    if processor_name in SUSPENDED_APPROVAL_PROCESSORS:
        return False
    required_checks = (
        REQUIRED_APPROVAL_CHECKS - {"glb_structure"} | {"provider_native_character_playback"}
        if processor_name == PROVIDER_NATIVE_PROCESSOR
        else REQUIRED_APPROVAL_CHECKS
    )
    standard_checks_pass = (
        manifest.validation.result == "passed"
        and required_checks.issubset(checks_by_name)
        and all(checks_by_name[name] for name in required_checks)
    )
    requires_animation_review = processor_name == "blender_rest_pose_retarget"
    processed = [item for item in manifest.artifacts if item.role == "processed_model"]
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


def approval_bindings_resolve(manifest: AssetManifest) -> bool:
    """Return whether an approved record resolves to the current exact artifacts."""
    if not manifest.approval.approved:
        return True
    bindings = manifest.approval.approved_artifact_hashes
    required_roles = approval_artifact_roles(manifest)
    if not set(required_roles).issubset(bindings):
        return False
    for role, expected_hash in bindings.items():
        candidates = [artifact for artifact in manifest.artifacts if artifact.role == role]
        if not candidates or candidates[-1].sha256 != expected_hash:
            return False
    return True


def _current_processed_model_processor(manifest: AssetManifest) -> str | None:
    processed = [item for item in manifest.artifacts if item.role == "processed_model"]
    if not processed or processed[-1].processor is None:
        return None
    return processed[-1].processor.name
