from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import ProviderTask, utc_now
from vandrel_foundry.domain.provider import ProviderTaskStatus
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.domain.workflow_policy import transition_workflow
from vandrel_foundry.storage.manifests import ManifestRepository


def reconcile_ambiguous_submission(
    config: FoundryConfig,
    asset_id: str,
    task_key: str,
    provider_task_id: str | None = None,
    confirm_not_created: bool = False,
) -> ProviderTask:
    """Apply a user-verified reconciliation outcome without making a network call."""
    if bool(provider_task_id) == confirm_not_created:
        raise FoundryError(
            "Provide exactly one reconciliation outcome: "
            "--provider-task-id or --confirm-not-created."
        )
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    matching = [task for task in manifest.generation.tasks if task.task_key == task_key]
    if not matching:
        raise FoundryError(f"Provider task not found: {task_key}")
    task = matching[-1]
    if task.status not in {ProviderTaskStatus.SUBMITTING, ProviderTaskStatus.AMBIGUOUS}:
        raise FoundryError(f"Task does not require reconciliation: {task_key} ({task.status})")

    if provider_task_id is not None:
        opaque_id = provider_task_id.strip()
        if not opaque_id:
            raise FoundryError("Provider task ID must not be empty.")
        if len(opaque_id) > 1024 or any(ord(character) < 32 for character in opaque_id):
            raise FoundryError("Provider task ID contains invalid control data.")
        task.provider_task_id = opaque_id
        task.status = ProviderTaskStatus.PENDING
        task.error = None
        transition_workflow(manifest, WorkflowState.SUBMITTED)
        manifest.workflow.blocked_reason = None
        event_type = "provider.submission_reconciled"
    else:
        task.status = ProviderTaskStatus.SUBMISSION_FAILED
        task.error = "User confirmed that the provider task was not created."
        transition_workflow(manifest, WorkflowState.DRAFT)
        manifest.workflow.blocked_reason = None
        event_type = "provider.submission_not_created"

    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    repository.save(
        manifest,
        event_type,
        expected_revision=manifest.revision - 1,
    )
    return task
