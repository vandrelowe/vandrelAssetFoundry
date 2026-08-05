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
