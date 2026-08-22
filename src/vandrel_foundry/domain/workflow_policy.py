"""Neutral workflow-transition and approval policy for Foundry candidates."""

from __future__ import annotations

from typing import TYPE_CHECKING

from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.meshy_native_release import (
    release_check_playback_policy_passes,
    release_check_visual_review_policy_passes,
)
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
SUSPENDED_APPROVAL_PROCESSORS = frozenset(
    {"blender_rest_pose_retarget", "blender_compound_creature_derivation"}
)
PROVIDER_NATIVE_PROCESSOR = "godot_provider_native_character"
MESHY_NATIVE_ASSEMBLY_PROCESSOR = "blender_meshy_native_character_motion_assembly"
MESHY_NATIVE_RELEASE_CHECK = "meshy_native_character_release_playback"
MESHY_NATIVE_RELEASE_REPORT_ROLE = "meshy_native_character_release_report"
ANIMATION_LIBRARY_LANE = "animation_library"
ANIMATION_LIBRARY_APPROVAL_ROLES = (
    "processed_animation_library",
    "animation_library_technical_report",
    "animation_library_godot_monitor_report",
    "animation_library_isolation_report",
    "animation_library_visual_matrix_report",
)


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
    if manifest.asset.lane == ANIMATION_LIBRARY_LANE:
        return ANIMATION_LIBRARY_APPROVAL_ROLES
    processor_name = _current_processed_model_processor(manifest)
    return BASE_APPROVAL_ROLES + (
        PROVIDER_NATIVE_APPROVAL_ROLES if processor_name == PROVIDER_NATIVE_PROCESSOR else ()
    ) + (
        (MESHY_NATIVE_RELEASE_REPORT_ROLE,)
        if processor_name == MESHY_NATIVE_ASSEMBLY_PROCESSOR
        else ()
    ) + (("creature_playback_report",) if manifest.asset.lane == "creature" else ())


def approval_artifact_bindings(manifest: AssetManifest) -> dict[str, str]:
    """Return exact approval keys, including repeated animation evidence artifacts."""
    bindings: dict[str, str] = {}
    for role in approval_artifact_roles(manifest):
        candidates = [item for item in manifest.artifacts if item.role == role]
        if not candidates:
            raise FoundryError(f"Approval artifact role is missing: {role}")
        bindings[role] = candidates[-1].sha256
    if manifest.asset.lane == ANIMATION_LIBRARY_LANE:
        reports = [
            item
            for item in manifest.artifacts
            if item.role == "animation_library_visual_matrix_report"
        ]
        if not reports:
            raise FoundryError("Animation visual matrix report is missing.")
        by_id = {item.artifact_id: item for item in manifest.artifacts}
        for artifact_id in reports[-1].derived_from:
            artifact = by_id.get(artifact_id)
            if artifact is not None and artifact.role == "animation_visual_evidence":
                bindings[f"artifact:{artifact_id}"] = artifact.sha256
    return bindings


def approval_checks_pass(manifest: AssetManifest) -> bool:
    checks_by_name = {
        str(check.get("name")): bool(check.get("passed")) for check in manifest.validation.checks
    }
    if manifest.asset.lane == ANIMATION_LIBRARY_LANE:
        checks = {str(check.get("name")): check for check in manifest.validation.checks}
        required = {
            "animation_library_monitored_godot",
            "animation_library_technical_probe",
            "animation_library_isolation",
            "animation_library_visual_matrix",
        }
        if manifest.validation.result != "passed" or not required.issubset(checks):
            return False
        if any(checks[name].get("passed") is not True for name in required):
            return False
        artifacts = {item.role: item for item in manifest.artifacts}
        library = artifacts.get("processed_animation_library")
        technical = artifacts.get("animation_library_technical_report")
        monitor = artifacts.get("animation_library_godot_monitor_report")
        isolation = artifacts.get("animation_library_isolation_report")
        visual = artifacts.get("animation_library_visual_matrix_report")
        if any(item is None for item in (library, technical, monitor, isolation, visual)):
            return False
        return bool(
            checks["animation_library_technical_probe"].get("animation_library_sha256")
            == library.sha256
            and checks["animation_library_technical_probe"].get("report_sha256")
            == technical.sha256
            and checks["animation_library_monitored_godot"].get(
                "animation_library_sha256"
            )
            == library.sha256
            and checks["animation_library_monitored_godot"].get("report_sha256")
            == monitor.sha256
            and checks["animation_library_isolation"].get("animation_library_sha256")
            == library.sha256
            and checks["animation_library_isolation"].get("report_sha256")
            == isolation.sha256
            and checks["animation_library_isolation"].get("external_dependencies") == []
            and checks["animation_library_visual_matrix"].get(
                "animation_library_sha256"
            )
            == library.sha256
            and checks["animation_library_visual_matrix"].get("technical_report_sha256")
            == technical.sha256
            and checks["animation_library_visual_matrix"].get("report_sha256")
            == visual.sha256
            and checks["animation_library_visual_matrix"].get("failed_cells") == []
        )
    processor_name = _current_processed_model_processor(manifest)
    is_compound_creature = (
        manifest.asset.lane == "creature"
        and processor_name == "blender_compound_creature_derivation"
    )
    disallowed_suspension = _current_processed_model_has_disallowed_suspension(manifest)
    processed = [item for item in manifest.artifacts if item.role == "processed_model"]
    creature_playback_passes = bool(
        is_compound_creature
        and processed
        and any(
            check.get("name") == "creature_continuous_playback"
            and check.get("passed")
            and check.get("processed_model_sha256") == processed[-1].sha256
            for check in manifest.validation.checks
        )
    )
    if disallowed_suspension:
        return False
    if (
        processor_name in SUSPENDED_APPROVAL_PROCESSORS
        and not (is_compound_creature and creature_playback_passes)
    ):
        return False
    required_checks = (
        REQUIRED_APPROVAL_CHECKS - {"glb_structure"} | {"provider_native_character_playback"}
        if processor_name == PROVIDER_NATIVE_PROCESSOR
        else (
            REQUIRED_APPROVAL_CHECKS | {MESHY_NATIVE_RELEASE_CHECK}
            if processor_name == MESHY_NATIVE_ASSEMBLY_PROCESSOR
            else REQUIRED_APPROVAL_CHECKS
        )
    )
    standard_checks_pass = (
        manifest.validation.result == "passed"
        and required_checks.issubset(checks_by_name)
        and all(checks_by_name[name] for name in required_checks)
    )
    requires_animation_review = processor_name == "blender_rest_pose_retarget"
    animation_review_passes = bool(
        processed
        and any(
            check.get("name") == "animation_visual_review"
            and check.get("passed")
            and check.get("processed_model_sha256") == processed[-1].sha256
            for check in manifest.validation.checks
        )
    )
    requires_animation_review = requires_animation_review or is_compound_creature
    meshy_release_passes = bool(
        processor_name != MESHY_NATIVE_ASSEMBLY_PROCESSOR
        or (
            processed
            and any(
                check.get("name") == MESHY_NATIVE_RELEASE_CHECK
                and check.get("passed")
                and check.get("processed_model_sha256") == processed[-1].sha256
                and release_check_playback_policy_passes(check)
                and release_check_visual_review_policy_passes(check)
                for check in manifest.validation.checks
            )
        )
    )
    return (
        standard_checks_pass
        and (not requires_animation_review or animation_review_passes)
        and meshy_release_passes
    )


def approval_bindings_resolve(manifest: AssetManifest) -> bool:
    """Return whether an approved record resolves to the current exact artifacts."""
    if not manifest.approval.approved:
        return True
    bindings = manifest.approval.approved_artifact_hashes
    try:
        required_bindings = approval_artifact_bindings(manifest)
    except FoundryError:
        return False
    if not set(required_bindings).issubset(bindings):
        return False
    by_id = {item.artifact_id: item for item in manifest.artifacts}
    for key, expected_hash in bindings.items():
        if key.startswith("artifact:"):
            artifact = by_id.get(key.removeprefix("artifact:"))
            if artifact is None or artifact.sha256 != expected_hash:
                return False
            continue
        candidates = [artifact for artifact in manifest.artifacts if artifact.role == key]
        if not candidates or candidates[-1].sha256 != expected_hash:
            return False
    return True


def _current_processed_model_processor(manifest: AssetManifest) -> str | None:
    processed = [item for item in manifest.artifacts if item.role == "processed_model"]
    if not processed or processed[-1].processor is None:
        return None
    return processed[-1].processor.name


def _current_processed_model_has_disallowed_suspension(manifest: AssetManifest) -> bool:
    processed = [item for item in manifest.artifacts if item.role == "processed_model"]
    if not processed:
        return False
    by_id = {item.artifact_id: item for item in manifest.artifacts}
    current = processed[-1]
    pending = [(current, True)]
    visited: set[str] = set()
    while pending:
        artifact, is_current = pending.pop()
        if artifact.artifact_id in visited:
            continue
        visited.add(artifact.artifact_id)
        if (
            artifact.processor
            and artifact.processor.name in SUSPENDED_APPROVAL_PROCESSORS
            and not (
                is_current
                and artifact.processor.name == "blender_compound_creature_derivation"
            )
        ):
            return True
        if any(parent not in by_id for parent in artifact.derived_from):
            return True
        pending.extend((by_id[parent], False) for parent in artifact.derived_from)
    return False
