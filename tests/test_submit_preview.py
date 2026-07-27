import json
from pathlib import Path

import pytest

from vandrel_foundry.domain.errors import (
    AmbiguousSubmissionError,
    DefinitiveSubmissionError,
    FoundryError,
)
from vandrel_foundry.domain.provider import ProviderTaskStatus
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.providers.meshy.models import (
    CreateTaskResponse,
    TextTo3DPreviewRequest,
)
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.inspect_assets import initialize_workspace
from vandrel_foundry.services.submit_preview import submit_text_preview
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.provider_evidence import write_new_json_evidence


class SuccessfulTransport:
    def __init__(self, repository: ManifestRepository | None = None) -> None:
        self.calls = 0
        self.received_key: str | None = None
        self.repository = repository
        self.observed_status: ProviderTaskStatus | None = None

    def create_text_preview(
        self,
        request: TextTo3DPreviewRequest,
        api_key: str,
    ) -> CreateTaskResponse:
        self.calls += 1
        self.received_key = api_key
        if self.repository is not None:
            manifest = self.repository.load("stone_knife_001")
            self.observed_status = manifest.generation.tasks[-1].status
        return CreateTaskResponse(result="opaque-provider-task-id")


class AmbiguousTransport:
    def __init__(self) -> None:
        self.calls = 0

    def create_text_preview(
        self,
        request: TextTo3DPreviewRequest,
        api_key: str,
    ) -> CreateTaskResponse:
        self.calls += 1
        raise TimeoutError(f"timed out using {api_key}")


class RejectingTransport:
    def __init__(self) -> None:
        self.calls = 0

    def create_text_preview(
        self,
        request: TextTo3DPreviewRequest,
        api_key: str,
    ) -> CreateTaskResponse:
        self.calls += 1
        raise DefinitiveSubmissionError("HTTP 400: invalid prompt")


class InterruptedTransport:
    def create_text_preview(
        self,
        request: TextTo3DPreviewRequest,
        api_key: str,
    ) -> CreateTaskResponse:
        raise KeyboardInterrupt


def created_asset(config, lanes, prompt: Path) -> None:
    initialize_workspace(config.foundry.workspace_root)
    create_asset(
        config,
        lanes,
        "stone_knife_001",
        "static_prop",
        "Stone Knife",
        prompt,
    )


def test_success_records_submitting_before_transport_and_then_provider_id(
    config, lanes, prompt: Path
) -> None:
    created_asset(config, lanes, prompt)
    repository = ManifestRepository(config.foundry.workspace_root)
    transport = SuccessfulTransport(repository)
    task = submit_text_preview(
        config,
        "stone_knife_001",
        transport,
        {"MESHY_API_KEY": "top-secret"},
    )
    manifest = ManifestRepository(config.foundry.workspace_root).load("stone_knife_001")
    asset_root = config.foundry.workspace_root / "assets" / "stone_knife_001"

    assert transport.calls == 1
    assert transport.received_key == "top-secret"
    assert transport.observed_status is ProviderTaskStatus.SUBMITTING
    assert task.status is ProviderTaskStatus.PENDING
    assert task.provider_task_id == "opaque-provider-task-id"
    assert manifest.workflow.state is WorkflowState.SUBMITTED
    assert manifest.revision == 3
    assert len(manifest.generation.tasks) == 1
    assert (asset_root / str(task.request_path)).is_file()
    assert (asset_root / str(task.response_path)).is_file()
    request_snapshot = json.loads((asset_root / str(task.request_path)).read_text(encoding="utf-8"))
    assert request_snapshot["prompt"] == "a rough stone knife"
    response_snapshot = json.loads(
        (asset_root / str(task.response_path)).read_text(encoding="utf-8")
    )
    all_evidence = f"{request_snapshot}{response_snapshot}"
    assert "top-secret" not in all_evidence
    events = (asset_root / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["event"] for line in events] == [
        "asset.created",
        "provider.submission_started",
        "provider.submission_accepted",
    ]


def test_ambiguous_outcome_is_redacted_and_blocks_resubmission(config, lanes, prompt: Path) -> None:
    created_asset(config, lanes, prompt)
    transport = AmbiguousTransport()
    with pytest.raises(AmbiguousSubmissionError):
        submit_text_preview(
            config,
            "stone_knife_001",
            transport,
            {"MESHY_API_KEY": "top-secret"},
        )
    manifest = ManifestRepository(config.foundry.workspace_root).load("stone_knife_001")
    task = manifest.generation.tasks[0]
    assert transport.calls == 1
    assert task.status is ProviderTaskStatus.AMBIGUOUS
    assert "top-secret" not in (task.error or "")
    assert "[REDACTED]" in (task.error or "")

    with pytest.raises(FoundryError, match="needs reconciliation"):
        submit_text_preview(
            config,
            "stone_knife_001",
            transport,
            {"MESHY_API_KEY": "top-secret"},
        )
    assert transport.calls == 1


def test_definitive_rejection_is_recorded(config, lanes, prompt: Path) -> None:
    created_asset(config, lanes, prompt)
    transport = RejectingTransport()
    with pytest.raises(DefinitiveSubmissionError):
        submit_text_preview(
            config,
            "stone_knife_001",
            transport,
            {"MESHY_API_KEY": "top-secret"},
        )
    manifest = ManifestRepository(config.foundry.workspace_root).load("stone_knife_001")
    assert transport.calls == 1
    assert manifest.generation.tasks[0].status is ProviderTaskStatus.SUBMISSION_FAILED
    assert manifest.workflow.state is WorkflowState.DRAFT


def test_interruption_after_transport_starts_is_ambiguous(config, lanes, prompt: Path) -> None:
    created_asset(config, lanes, prompt)
    with pytest.raises(KeyboardInterrupt):
        submit_text_preview(
            config,
            "stone_knife_001",
            InterruptedTransport(),
            {"MESHY_API_KEY": "top-secret"},
        )
    manifest = ManifestRepository(config.foundry.workspace_root).load("stone_knife_001")
    assert manifest.generation.tasks[0].status is ProviderTaskStatus.AMBIGUOUS


def test_missing_key_does_not_write_or_call_transport(config, lanes, prompt: Path) -> None:
    created_asset(config, lanes, prompt)
    transport = SuccessfulTransport()
    with pytest.raises(FoundryError, match="MESHY_API_KEY"):
        submit_text_preview(config, "stone_knife_001", transport, {})
    manifest = ManifestRepository(config.foundry.workspace_root).load("stone_knife_001")
    requests = (
        config.foundry.workspace_root
        / "assets"
        / "stone_knife_001"
        / "provider"
        / "meshy"
        / "requests"
    )
    assert transport.calls == 0
    assert manifest.revision == 1
    assert manifest.generation.tasks == []
    assert not requests.exists()


def test_provider_evidence_never_overwrites_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "request.json"
    write_new_json_evidence(path, {"attempt": 1})
    with pytest.raises(FoundryError, match="already exists"):
        write_new_json_evidence(path, {"attempt": 2})
    assert json.loads(path.read_text(encoding="utf-8")) == {"attempt": 1}
    assert list(tmp_path.glob("*.tmp")) == []
