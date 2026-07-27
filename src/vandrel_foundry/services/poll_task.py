import os
from collections.abc import Mapping

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import AssetManifest, ProviderTask, utc_now
from vandrel_foundry.domain.provider import ProviderTaskStatus
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.providers.base import TextPreviewTransport
from vandrel_foundry.providers.meshy.models import TaskError
from vandrel_foundry.providers.redaction import redact_provider_evidence
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path
from vandrel_foundry.storage.provider_evidence import write_new_json_evidence


def poll_text_task(
    config: FoundryConfig,
    asset_id: str,
    transport: TextPreviewTransport,
    task_key: str | None = None,
    environment: Mapping[str, str] | None = None,
) -> ProviderTask:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    task = select_generation_task(manifest, task_key)
    if not task.provider_task_id:
        raise FoundryError(f"Provider task ID is unavailable: {task.task_key}")
    if task.status in {
        ProviderTaskStatus.SUBMISSION_FAILED,
        ProviderTaskStatus.AMBIGUOUS,
        ProviderTaskStatus.FAILED,
        ProviderTaskStatus.CANCELED,
    }:
        raise FoundryError(f"Task cannot be polled from state {task.status}: {task.task_key}")

    variables = environment if environment is not None else os.environ
    key_name = config.providers.meshy.api_key_environment_variable
    api_key = variables.get(key_name, "")
    if not api_key:
        raise FoundryError(f"Required API key environment variable is not set: {key_name}")

    if task.operation == "image_to_3d":
        response = transport.retrieve_image_task(task.provider_task_id, api_key)
    elif task.operation == "remesh":
        response = transport.retrieve_remesh_task(task.provider_task_id, api_key)
    elif task.operation.startswith("retexture_"):
        response = transport.retrieve_retexture_task(task.provider_task_id, api_key)
    elif task.operation == "rigging":
        response = transport.retrieve_rigging_task(task.provider_task_id, api_key)
    else:
        response = transport.retrieve_text_task(task.provider_task_id, api_key)
    if response.id != task.provider_task_id:
        raise FoundryError(
            f"Provider returned task {response.id} while polling {task.provider_task_id}"
        )
    snapshot_number = len(task.response_snapshots) + 1
    snapshot_relative = RelativeManifestPath(
        f"provider/meshy/responses/{task.task_key}.poll_{snapshot_number:03d}.json"
    )
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    write_new_json_evidence(
        contained_path(asset_root, snapshot_relative),
        redact_provider_evidence(response.model_dump(mode="json")),
    )

    task.response_snapshots.append(snapshot_relative)
    task.status = response.status
    task.progress = response.progress
    task.consumed_credits = getattr(response, "consumed_credits", None)
    task.completed_at = (
        utc_now()
        if response.status
        in {
            ProviderTaskStatus.SUCCEEDED,
            ProviderTaskStatus.FAILED,
            ProviderTaskStatus.CANCELED,
        }
        else None
    )
    task.error = _task_error(response.task_error)
    _apply_workflow_state(manifest, task)
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    repository.save(
        manifest,
        "provider.task_polled",
        expected_revision=manifest.revision - 1,
    )
    return task


def select_generation_task(
    manifest: AssetManifest,
    task_key: str | None,
) -> ProviderTask:
    candidates = [
        task
        for task in manifest.generation.tasks
        if task.provider == "meshy"
        and task.operation
        in {
            "text_to_3d_preview",
            "text_to_3d_refine",
            "image_to_3d",
            "remesh",
            "retexture_beauty",
            "retexture_semantic",
            "rigging",
        }
    ]
    if task_key is not None:
        candidates = [task for task in candidates if task.task_key == task_key]
    if not candidates:
        target = task_key or "latest generation"
        raise FoundryError(f"Provider task not found: {target}")
    return candidates[-1]


select_text_task = select_generation_task


def _apply_workflow_state(manifest: AssetManifest, task: ProviderTask) -> None:
    if task.status is ProviderTaskStatus.SUCCEEDED:
        manifest.workflow.state = WorkflowState.SOURCE_READY
        manifest.workflow.blocked_reason = None
        manifest.workflow.last_error = None
    elif task.status in {ProviderTaskStatus.PENDING, ProviderTaskStatus.IN_PROGRESS}:
        manifest.workflow.state = WorkflowState.GENERATING
        manifest.workflow.blocked_reason = None
        manifest.workflow.last_error = None
    elif task.status in {ProviderTaskStatus.FAILED, ProviderTaskStatus.CANCELED}:
        manifest.workflow.state = WorkflowState.BLOCKED
        manifest.workflow.blocked_reason = f"Provider task {task.status.value.lower()}."
        manifest.workflow.last_error = task.error


def _task_error(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, TaskError):
        message = value.message
        return str(message) if message else None
    if isinstance(value, dict):
        message = value.get("message")
        return str(message) if message else None
    return str(value)
