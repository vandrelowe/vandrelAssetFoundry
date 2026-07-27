from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import ProviderTask, utc_now
from vandrel_foundry.domain.provider import ProviderTaskStatus
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.storage.manifests import ManifestRepository


def select_output(
    config: FoundryConfig,
    asset_id: str,
    task_key: str,
) -> ProviderTask:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.workflow.state is not WorkflowState.DOWNLOADED:
        raise FoundryError(f"Output selection requires downloaded state: {asset_id}")
    matches = [
        task
        for task in manifest.generation.tasks
        if task.task_key == task_key and task.status is ProviderTaskStatus.SUCCEEDED
    ]
    if not matches:
        raise FoundryError(f"Succeeded provider task not found: {task_key}")
    if not any(
        artifact.role == "source_model" and artifact.source_task_key == task_key
        for artifact in manifest.artifacts
    ):
        raise FoundryError(f"Selected task has no downloaded source model: {task_key}")
    manifest.generation.selected_task_key = task_key
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    repository.save(
        manifest,
        "provider.output_selected",
        expected_revision=manifest.revision - 1,
    )
    return matches[-1]
