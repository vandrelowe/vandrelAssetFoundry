import os
from collections.abc import Callable, Mapping

from pydantic import ValidationError

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import (
    AmbiguousSubmissionError,
    DefinitiveSubmissionError,
    FoundryError,
)
from vandrel_foundry.domain.manifest import AssetManifest, ProviderTask, utc_now
from vandrel_foundry.domain.provider import ProviderTaskStatus
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.providers.base import TextPreviewTransport
from vandrel_foundry.providers.meshy.models import (
    CreateTaskResponse,
    ImageTo3DRequest,
    RemeshRequest,
    TextTo3DPreviewRequest,
    TextTo3DRefineRequest,
)
from vandrel_foundry.providers.redaction import redact_provider_evidence
from vandrel_foundry.services.prepare_submission import (
    PreparedSubmission,
    prepare_image_submission,
    prepare_remesh_submission,
    prepare_text_preview_submission,
    prepare_text_refine_submission,
)
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path
from vandrel_foundry.storage.provider_evidence import write_new_json_evidence


def submit_text_preview(
    config: FoundryConfig,
    asset_id: str,
    transport: TextPreviewTransport,
    environment: Mapping[str, str] | None = None,
) -> ProviderTask:
    """Submit exactly once through an injected transport after durable local recording."""
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.workflow.state is not WorkflowState.DRAFT:
        raise FoundryError(
            f"Text preview submission requires draft state, got {manifest.workflow.state.value}: "
            f"{asset_id}"
        )
    prepared = prepare_text_preview_submission(config.foundry.workspace_root, manifest)
    return _submit_prepared(
        config,
        manifest,
        repository,
        prepared,
        transport.create_text_preview,
        environment,
    )


def submit_text_refine(
    config: FoundryConfig,
    asset_id: str,
    preview_task_key: str,
    transport: TextPreviewTransport,
    enable_pbr: bool = True,
    environment: Mapping[str, str] | None = None,
) -> ProviderTask:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.workflow.state not in {WorkflowState.SOURCE_READY, WorkflowState.DOWNLOADED}:
        raise FoundryError(
            f"Text refine submission requires source_ready or downloaded state, got "
            f"{manifest.workflow.state.value}: {asset_id}"
        )
    prepared = prepare_text_refine_submission(
        manifest,
        preview_task_key,
        enable_pbr=enable_pbr,
    )
    return _submit_prepared(
        config,
        manifest,
        repository,
        prepared,
        transport.create_text_refine,
        environment,
    )


def submit_image_to_3d(
    config: FoundryConfig,
    asset_id: str,
    transport: TextPreviewTransport,
    reference: RelativeManifestPath | None = None,
    environment: Mapping[str, str] | None = None,
) -> ProviderTask:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.workflow.state is not WorkflowState.DRAFT:
        raise FoundryError(
            f"Image submission requires draft state, got {manifest.workflow.state.value}: "
            f"{asset_id}"
        )
    prepared = prepare_image_submission(
        config.foundry.workspace_root,
        manifest,
        reference,
    )
    return _submit_prepared(
        config,
        manifest,
        repository,
        prepared,
        transport.create_image_task,
        environment,
    )


def submit_remesh(
    config: FoundryConfig,
    asset_id: str,
    target_polycount: int,
    transport: TextPreviewTransport,
    environment: Mapping[str, str] | None = None,
) -> ProviderTask:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.workflow.state not in {
        WorkflowState.SOURCE_READY,
        WorkflowState.DOWNLOADED,
        WorkflowState.PROCESSED,
    }:
        raise FoundryError(
            f"Remesh requires source_ready, downloaded, or processed state: {asset_id}"
        )
    prepared = prepare_remesh_submission(manifest, target_polycount)
    return _submit_prepared(
        config,
        manifest,
        repository,
        prepared,
        transport.create_remesh_task,
        environment,
    )


def _submit_prepared(
    config: FoundryConfig,
    manifest: AssetManifest,
    repository: ManifestRepository,
    prepared: PreparedSubmission,
    create_task: Callable[
        [
            TextTo3DPreviewRequest | TextTo3DRefineRequest | ImageTo3DRequest | RemeshRequest,
            str,
        ],
        CreateTaskResponse,
    ],
    environment: Mapping[str, str] | None,
) -> ProviderTask:
    unresolved = [
        task.task_key
        for task in manifest.generation.tasks
        if task.operation == prepared.operation
        and task.status in {ProviderTaskStatus.SUBMITTING, ProviderTaskStatus.AMBIGUOUS}
    ]
    if unresolved:
        raise FoundryError(
            "Cannot submit while an earlier attempt needs reconciliation: " + ", ".join(unresolved)
        )
    variables = environment if environment is not None else os.environ
    key_name = config.providers.meshy.api_key_environment_variable
    api_key = variables.get(key_name, "")
    if not api_key:
        raise FoundryError(f"Required API key environment variable is not set: {key_name}")

    asset_root = config.foundry.workspace_root / "assets" / manifest.asset.asset_id
    request_relative = RelativeManifestPath(f"provider/meshy/requests/{prepared.task_key}.json")
    response_relative = RelativeManifestPath(f"provider/meshy/responses/{prepared.task_key}.json")
    write_new_json_evidence(
        contained_path(asset_root, request_relative),
        redact_provider_evidence(prepared.request.model_dump(mode="json")),
    )

    task = ProviderTask(
        task_key=prepared.task_key,
        provider="meshy",
        operation=prepared.operation,
        attempt=prepared.attempt,
        status=ProviderTaskStatus.SUBMITTING,
        request_fingerprint=prepared.request_fingerprint,
        request_path=request_relative,
        submitted_at=utc_now(),
    )
    manifest.generation.tasks.append(task)
    _save_revision(repository, manifest, "provider.submission_started")

    try:
        response = create_task(prepared.request, api_key)
        response = CreateTaskResponse.model_validate(response)
    except DefinitiveSubmissionError as exc:
        task.status = ProviderTaskStatus.SUBMISSION_FAILED
        task.error = _safe_error(exc, api_key)
        _save_revision(repository, manifest, "provider.submission_rejected")
        raise
    except (AmbiguousSubmissionError, ValidationError) as exc:
        task.status = ProviderTaskStatus.AMBIGUOUS
        task.error = _safe_error(exc, api_key)
        manifest.workflow.blocked_reason = "Provider submission outcome is ambiguous."
        _save_revision(repository, manifest, "provider.submission_ambiguous")
        raise AmbiguousSubmissionError(task.error) from exc
    except KeyboardInterrupt:
        task.status = ProviderTaskStatus.AMBIGUOUS
        task.error = "KeyboardInterrupt during provider submission"
        manifest.workflow.blocked_reason = "Provider submission outcome is ambiguous."
        _save_revision(repository, manifest, "provider.submission_ambiguous")
        raise
    except Exception as exc:
        task.status = ProviderTaskStatus.AMBIGUOUS
        task.error = _safe_error(exc, api_key)
        manifest.workflow.blocked_reason = "Provider submission outcome is ambiguous."
        _save_revision(repository, manifest, "provider.submission_ambiguous")
        raise AmbiguousSubmissionError(task.error) from exc

    task.provider_task_id = response.result
    task.status = ProviderTaskStatus.PENDING
    manifest.workflow.state = WorkflowState.SUBMITTED
    try:
        write_new_json_evidence(
            contained_path(asset_root, response_relative),
            redact_provider_evidence(response.model_dump(mode="json")),
        )
        task.response_path = response_relative
    except FoundryError as exc:
        task.error = f"Task accepted, but response evidence could not be written: {exc}"
    _save_revision(repository, manifest, "provider.submission_accepted")
    return task


def _save_revision(
    repository: ManifestRepository,
    manifest: AssetManifest,
    event_type: str,
) -> None:
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    repository.save(
        manifest,
        event_type,
        expected_revision=manifest.revision - 1,
    )


def _safe_error(exc: Exception, api_key: str) -> str:
    name = type(exc).__name__
    message = str(exc).replace(api_key, "[REDACTED]").strip()
    return f"{name}: {message}" if message else name
