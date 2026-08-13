from datetime import UTC, datetime

import pytest

from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import (
    Artifact,
    AssetManifest,
    CustodySourceInput,
    Processor,
)
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.domain.workflow_policy import (
    ALLOWED_WORKFLOW_TRANSITIONS,
    approval_artifact_roles,
    approval_bindings_resolve,
    approval_checks_pass,
    invalidate_approval,
    transition_workflow,
)

EXPECTED_LEGAL_TRANSITIONS = {
    (WorkflowState.DRAFT, WorkflowState.DRAFT),
    (WorkflowState.DRAFT, WorkflowState.SUBMITTED),
    (WorkflowState.DRAFT, WorkflowState.DOWNLOADED),
    (WorkflowState.SUBMITTED, WorkflowState.DRAFT),
    (WorkflowState.SUBMITTED, WorkflowState.SUBMITTED),
    (WorkflowState.SUBMITTED, WorkflowState.GENERATING),
    (WorkflowState.SUBMITTED, WorkflowState.SOURCE_READY),
    (WorkflowState.SUBMITTED, WorkflowState.BLOCKED),
    (WorkflowState.GENERATING, WorkflowState.GENERATING),
    (WorkflowState.GENERATING, WorkflowState.SOURCE_READY),
    (WorkflowState.GENERATING, WorkflowState.BLOCKED),
    (WorkflowState.SOURCE_READY, WorkflowState.SUBMITTED),
    (WorkflowState.SOURCE_READY, WorkflowState.DOWNLOADED),
    (WorkflowState.DOWNLOADED, WorkflowState.SUBMITTED),
    (WorkflowState.DOWNLOADED, WorkflowState.PROCESSED),
    (WorkflowState.DOWNLOADED, WorkflowState.REVIEW),
    (WorkflowState.DOWNLOADED, WorkflowState.BLOCKED),
    (WorkflowState.PROCESSED, WorkflowState.SUBMITTED),
    (WorkflowState.PROCESSED, WorkflowState.PROCESSED),
    (WorkflowState.PROCESSED, WorkflowState.STAGED),
    (WorkflowState.PROCESSED, WorkflowState.REVIEW),
    (WorkflowState.PROCESSED, WorkflowState.BLOCKED),
    (WorkflowState.STAGED, WorkflowState.PROCESSED),
    (WorkflowState.STAGED, WorkflowState.REVIEW),
    (WorkflowState.STAGED, WorkflowState.BLOCKED),
    (WorkflowState.REVIEW, WorkflowState.SUBMITTED),
    (WorkflowState.REVIEW, WorkflowState.PROCESSED),
    (WorkflowState.REVIEW, WorkflowState.REVIEW),
    (WorkflowState.REVIEW, WorkflowState.APPROVED),
    (WorkflowState.REVIEW, WorkflowState.REJECTED),
    (WorkflowState.REVIEW, WorkflowState.BLOCKED),
    (WorkflowState.APPROVED, WorkflowState.PROCESSED),
    (WorkflowState.APPROVED, WorkflowState.REVIEW),
    (WorkflowState.APPROVED, WorkflowState.BLOCKED),
    (WorkflowState.REJECTED, WorkflowState.SUBMITTED),
    (WorkflowState.REJECTED, WorkflowState.REVIEW),
    (WorkflowState.REJECTED, WorkflowState.BLOCKED),
    (WorkflowState.BLOCKED, WorkflowState.SUBMITTED),
    (WorkflowState.BLOCKED, WorkflowState.REVIEW),
    (WorkflowState.BLOCKED, WorkflowState.REJECTED),
    (WorkflowState.BLOCKED, WorkflowState.BLOCKED),
}
ALL_TRANSITIONS = {(source, target) for source in WorkflowState for target in WorkflowState}


def test_transition_policy_matches_characterized_graph() -> None:
    actual = {
        (source, target)
        for source, targets in ALLOWED_WORKFLOW_TRANSITIONS.items()
        for target in targets
    }
    assert actual == EXPECTED_LEGAL_TRANSITIONS


@pytest.mark.parametrize(
    ("source", "target"),
    sorted(
        EXPECTED_LEGAL_TRANSITIONS,
        key=lambda pair: (pair[0].value, pair[1].value),
    ),
)
def test_every_legal_workflow_transition_changes_only_in_memory_state(
    source,
    target,
) -> None:
    manifest = _manifest()
    manifest.workflow.state = source
    original_revision = manifest.revision
    original_updated_at = manifest.asset.updated_at

    transition_workflow(manifest, target)

    assert manifest.workflow.state is target
    assert manifest.revision == original_revision
    assert manifest.asset.updated_at == original_updated_at


@pytest.mark.parametrize(
    ("source", "target"),
    sorted(
        ALL_TRANSITIONS - EXPECTED_LEGAL_TRANSITIONS,
        key=lambda pair: (pair[0].value, pair[1].value),
    ),
)
def test_every_illegal_workflow_transition_fails_without_mutation(
    source,
    target,
) -> None:
    manifest = _manifest()
    manifest.workflow.state = source
    before = manifest.model_dump(mode="json")

    with pytest.raises(
        FoundryError,
        match=f"Illegal workflow transition: {source.value} -> {target.value}",
    ):
        transition_workflow(manifest, target)

    assert manifest.model_dump(mode="json") == before


def test_invalidate_approval_clears_complete_tuple_without_state_revision_or_event_change() -> None:
    manifest = _manifest()
    manifest.workflow.state = WorkflowState.APPROVED
    manifest.revision = 17
    manifest.approval.approved = True
    manifest.approval.approved_at = datetime(2026, 7, 28, tzinfo=UTC)
    manifest.approval.approved_artifact_hashes = {"processed_model": "a" * 64}
    manifest.approval.custody_assertion_sha256 = "b" * 64
    manifest.approval.custody_source_inputs = [
        CustodySourceInput(
            artifact_id="source_glb_001",
            role="source_model",
            sha256="c" * 64,
            size_bytes=123,
        )
    ]
    manifest.approval.reviewer = "Prior Reviewer"
    manifest.approval.notes = "Prior approval notes"
    before_state = manifest.workflow.state
    before_revision = manifest.revision
    before_updated_at = manifest.asset.updated_at

    invalidate_approval(manifest)

    assert manifest.approval.model_dump(mode="json") == {
        "approved": False,
        "approved_at": None,
        "approved_artifact_hashes": {},
        "custody_assertion_sha256": None,
        "custody_source_inputs": [],
        "reviewer": None,
        "notes": "",
    }
    assert manifest.workflow.state is before_state
    assert manifest.revision == before_revision
    assert manifest.asset.updated_at == before_updated_at


def test_approval_roles_and_bindings_are_neutral_exact_policy() -> None:
    manifest = _manifest()
    processed = _artifact("processed", "processed_model", "1" * 64)
    wrapper = _artifact("wrapper", "godot_wrapper_scene", "2" * 64)
    manifest.artifacts = [processed, wrapper]
    manifest.approval.approved = True
    manifest.approval.approved_artifact_hashes = {
        "processed_model": processed.sha256,
        "godot_wrapper_scene": wrapper.sha256,
    }

    assert approval_artifact_roles(manifest) == (
        "processed_model",
        "godot_wrapper_scene",
    )
    assert approval_bindings_resolve(manifest)

    processed.processor = Processor(name="godot_provider_native_character", version="1")
    assert approval_artifact_roles(manifest) == (
        "processed_model",
        "godot_wrapper_scene",
        "processed_animation_walk",
        "processed_animation_run",
        "godot_animation_loader_script",
    )
    assert not approval_bindings_resolve(manifest)


def test_meshy_native_assembly_requires_exact_current_release_evidence() -> None:
    manifest = _manifest()
    manifest.asset.lane = "humanoid"
    processed = _artifact("processed", "processed_model", "1" * 64)
    processed.processor = Processor(
        name="blender_meshy_native_character_motion_assembly", version="2"
    )
    report = _artifact(
        "release-report", "meshy_native_character_release_report", "2" * 64
    )
    manifest.artifacts = [processed, report]
    manifest.validation.result = "passed"
    manifest.validation.checks = [
        {"name": name, "passed": True}
        for name in (
            "glb_structure",
            "geometry_present",
            "triangle_budget",
            "materials_required",
            "skeleton_required",
            "godot_sandbox_import",
        )
    ]
    assert approval_artifact_roles(manifest) == (
        "processed_model",
        "godot_wrapper_scene",
        "meshy_native_character_release_report",
    )
    assert not approval_checks_pass(manifest)

    manifest.validation.checks.append(
        {
            "name": "meshy_native_character_release_playback",
            "passed": True,
            "processed_model_sha256": processed.sha256,
            "clip_count": 29,
            "playback_evidence_count": 13,
            "accepted_hand_visual_debt": True,
            "h4_additional_hand_corruption": False,
        }
    )
    assert approval_checks_pass(manifest)

    manifest.validation.checks[-1].update(
        {
            "clip_count": 61,
            "source_root_count": 68,
            "playback_evidence_count": 3,
            "playback_clip_names": [
                "target_character|Idle_6",
                "target_character|Walking",
                "target_character|Pull_Radish",
            ],
            "assembly_evidence_schema": (
                "vandrel_foundry_meshy_native_character_motion/1.4"
            ),
            "playback_evidence_profile": "representative_batch",
        }
    )
    assert approval_checks_pass(manifest)

    manifest.validation.checks[-1]["playback_clip_names"][-1] = (
        "target_character|Unrelated"
    )
    assert not approval_checks_pass(manifest)

    manifest.validation.checks[-1].update(
        {
            "clip_count": 61,
            "source_root_count": 68,
            "playback_evidence_count": 45,
        }
    )
    assert approval_checks_pass(manifest)

    manifest.validation.checks[-1].pop("source_root_count")
    assert not approval_checks_pass(manifest)
    manifest.validation.checks[-1]["source_root_count"] = 68

    manifest.validation.checks[-1].update(
        {
            "playback_evidence_count": 6,
            "playback_clip_names": [
                "target_character|Idle_6",
                "target_character|Walking",
                "target_character|019fe8ca-a6c4-7968-822f-92efebbab5a4",
                "target_character|019fe8d7-ed16-7b82-a594-728d821ee711",
                "target_character|Heavy_Hammer_Swing",
                "target_character|Walk_Forward_with_Bow_Aimed",
            ],
            "assembly_evidence_schema": (
                "vandrel_foundry_meshy_native_character_motion/1.5"
            ),
            "playback_evidence_profile": "repair_canary",
            "top8_independent_skin_passed": True,
            "top8_source_influence_gate_passes": True,
            "consumer_blocking_reasons": [],
            "godot_current_model_binding_passed": True,
            "accepted_hand_visual_debt": False,
            "visual_debt_status": "pending_consumer_review",
            "visual_acceptance_basis": "pending_vandrel_lightweight_f12",
            "consumer_visual_review_pending": True,
            "h4_additional_hand_corruption": False,
        }
    )
    assert approval_checks_pass(manifest)

    manifest.validation.checks[-1]["accepted_hand_visual_debt"] = True
    assert not approval_checks_pass(manifest)
    manifest.validation.checks[-1]["accepted_hand_visual_debt"] = False

    manifest.validation.checks[-1]["processed_model_sha256"] = "3" * 64
    assert not approval_checks_pass(manifest)


def test_unrelated_suspended_creature_processor_is_rejected_without_exception() -> None:
    manifest = _manifest()
    manifest.asset.lane = "creature"
    processed = _artifact("processed", "processed_model", "1" * 64)
    processed.processor = Processor(name="blender_rest_pose_retarget", version="1")
    manifest.artifacts = [processed]
    manifest.validation.result = "passed"
    manifest.validation.checks = [
        {"name": name, "passed": True}
        for name in (
            "glb_structure",
            "geometry_present",
            "triangle_budget",
            "materials_required",
            "skeleton_required",
            "godot_sandbox_import",
        )
    ]

    assert not approval_checks_pass(manifest)


def test_compound_creature_requires_exact_playback_and_visual_review() -> None:
    manifest = _manifest()
    manifest.asset.lane = "creature"
    processed = _artifact("processed", "processed_model", "1" * 64)
    processed.processor = Processor(name="blender_compound_creature_derivation", version="1")
    manifest.artifacts = [processed]
    manifest.validation.result = "passed"
    manifest.validation.checks = [
        {"name": name, "passed": True}
        for name in (
            "glb_structure",
            "geometry_present",
            "triangle_budget",
            "materials_required",
            "skeleton_required",
            "godot_sandbox_import",
        )
    ]
    assert not approval_checks_pass(manifest)
    manifest.validation.checks.extend(
        [
            {
                "name": "creature_continuous_playback",
                "passed": True,
                "processed_model_sha256": processed.sha256,
            },
            {
                "name": "animation_visual_review",
                "passed": True,
                "processed_model_sha256": processed.sha256,
            },
        ]
    )
    assert approval_checks_pass(manifest)


@pytest.mark.parametrize(
    "ancestor_processor",
    ["blender_rest_pose_retarget", "blender_compound_creature_derivation"],
)
def test_compound_playback_does_not_excuse_additional_suspended_ancestor(
    ancestor_processor,
) -> None:
    manifest = _compound_playback_manifest()
    ancestor = _artifact("ancestor", "processing_intermediate", "2" * 64)
    ancestor.processor = Processor(name=ancestor_processor, version="1")
    manifest.artifacts.insert(0, ancestor)
    manifest.artifacts[-1].derived_from = [ancestor.artifact_id]

    assert not approval_checks_pass(manifest)


def test_compound_playback_fails_closed_on_missing_parent() -> None:
    manifest = _compound_playback_manifest()
    manifest.artifacts[-1].derived_from = ["missing-parent"]

    assert not approval_checks_pass(manifest)


def _compound_playback_manifest() -> AssetManifest:
    manifest = _manifest()
    manifest.asset.lane = "creature"
    processed = _artifact("processed", "processed_model", "1" * 64)
    processed.processor = Processor(name="blender_compound_creature_derivation", version="1")
    manifest.artifacts = [processed]
    manifest.validation.result = "passed"
    manifest.validation.checks = [
        {"name": name, "passed": True}
        for name in (
            "glb_structure",
            "geometry_present",
            "triangle_budget",
            "materials_required",
            "skeleton_required",
            "godot_sandbox_import",
        )
    ]
    manifest.validation.checks.extend(
        [
            {
                "name": "creature_continuous_playback",
                "passed": True,
                "processed_model_sha256": processed.sha256,
            },
            {
                "name": "animation_visual_review",
                "passed": True,
                "processed_model_sha256": processed.sha256,
            },
        ]
    )
    return manifest


def _manifest() -> AssetManifest:
    return AssetManifest.initial(
        asset_id="workflow_policy_fixture",
        display_name="Workflow Policy Fixture",
        lane="static_prop",
        provider="meshy",
    )


def _artifact(artifact_id: str, role: str, sha256: str) -> Artifact:
    return Artifact(
        artifact_id=artifact_id,
        role=role,
        stage="processed",
        format="bin",
        path=f"processed/{artifact_id}.bin",
        sha256=sha256,
        size_bytes=1,
    )
