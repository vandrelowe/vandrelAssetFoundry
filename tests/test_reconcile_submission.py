from pathlib import Path

import pytest

from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import ProviderTask
from vandrel_foundry.domain.provider import ProviderTaskStatus
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.inspect_assets import initialize_workspace
from vandrel_foundry.services.reconcile_submission import reconcile_ambiguous_submission
from vandrel_foundry.storage.manifests import ManifestRepository


def ambiguous_asset(config, lanes, prompt: Path) -> ManifestRepository:
    initialize_workspace(config.foundry.workspace_root)
    manifest = create_asset(
        config,
        lanes,
        "stone_knife_001",
        "static_prop",
        "Stone Knife",
        prompt,
    )
    manifest.generation.tasks.append(
        ProviderTask(
            task_key="meshy_preview_001",
            provider="meshy",
            operation="text_to_3d_preview",
            attempt=1,
            status=ProviderTaskStatus.AMBIGUOUS,
        )
    )
    manifest.workflow.blocked_reason = "Provider submission outcome is ambiguous."
    manifest.revision = 2
    repository = ManifestRepository(config.foundry.workspace_root)
    repository.save(manifest, "provider.submission_ambiguous")
    return repository


def test_reconcile_binds_user_verified_provider_task(config, lanes, prompt: Path) -> None:
    repository = ambiguous_asset(config, lanes, prompt)
    task = reconcile_ambiguous_submission(
        config,
        "stone_knife_001",
        "meshy_preview_001",
        provider_task_id="opaque-id",
    )
    manifest = repository.load("stone_knife_001")
    assert task.status is ProviderTaskStatus.PENDING
    assert task.provider_task_id == "opaque-id"
    assert manifest.workflow.state is WorkflowState.SUBMITTED
    assert manifest.workflow.blocked_reason is None


def test_reconcile_not_created_allows_explicit_retry(config, lanes, prompt: Path) -> None:
    repository = ambiguous_asset(config, lanes, prompt)
    task = reconcile_ambiguous_submission(
        config,
        "stone_knife_001",
        "meshy_preview_001",
        confirm_not_created=True,
    )
    manifest = repository.load("stone_knife_001")
    assert task.status is ProviderTaskStatus.SUBMISSION_FAILED
    assert manifest.workflow.state is WorkflowState.DRAFT


@pytest.mark.parametrize(
    ("provider_task_id", "confirm_not_created"),
    [(None, False), ("id", True)],
)
def test_reconcile_requires_exactly_one_outcome(
    config,
    provider_task_id: str | None,
    confirm_not_created: bool,
) -> None:
    with pytest.raises(FoundryError, match="exactly one"):
        reconcile_ambiguous_submission(
            config,
            "stone_knife_001",
            "meshy_preview_001",
            provider_task_id=provider_task_id,
            confirm_not_created=confirm_not_created,
        )
