import hashlib
import json
from pathlib import Path

import pytest

from vandrel_foundry.domain.errors import DownloadError
from vandrel_foundry.domain.provider import ProviderTaskStatus
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.providers.meshy.models import (
    CreateTaskResponse,
    RemeshRequest,
    TextTo3DPreviewRequest,
    TextTo3DRefineRequest,
    TextTo3DTaskResponse,
)
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.download_artifact import download_text_preview_glb
from vandrel_foundry.services.inspect_assets import initialize_workspace
from vandrel_foundry.services.poll_task import poll_text_task
from vandrel_foundry.services.process_asset import process_passthrough
from vandrel_foundry.services.select_output import select_output
from vandrel_foundry.services.submit_preview import (
    submit_remesh,
    submit_text_preview,
    submit_text_refine,
)
from vandrel_foundry.storage.manifests import ManifestRepository


class LifecycleTransport:
    def __init__(self, responses: list[TextTo3DTaskResponse], content: bytes = b"glb-data"):
        self.responses = responses
        self.content = content
        self.download_calls = 0

    def create_text_preview(
        self,
        request: TextTo3DPreviewRequest,
        api_key: str,
    ) -> CreateTaskResponse:
        return CreateTaskResponse(result="provider-task")

    def create_text_refine(
        self,
        request: TextTo3DRefineRequest,
        api_key: str,
    ) -> CreateTaskResponse:
        return CreateTaskResponse(result="provider-refine-task")

    def create_remesh_task(
        self,
        request: RemeshRequest,
        api_key: str,
    ) -> CreateTaskResponse:
        return CreateTaskResponse(result="provider-remesh-task")

    def retrieve_text_task(
        self,
        provider_task_id: str,
        api_key: str,
    ) -> TextTo3DTaskResponse:
        return self.responses.pop(0)

    def download_file(self, url: str, destination: Path) -> int:
        self.download_calls += 1
        destination.write_bytes(self.content)
        return len(self.content)


class FailingDownloadTransport(LifecycleTransport):
    def download_file(self, url: str, destination: Path) -> int:
        destination.write_bytes(b"partial")
        raise DownloadError("connection lost")


class FailingThumbnailTransport(LifecycleTransport):
    def download_file(self, url: str, destination: Path) -> int:
        self.download_calls += 1
        destination.write_bytes(b"partial" if self.download_calls == 2 else self.content)
        if self.download_calls == 2:
            raise DownloadError("thumbnail connection lost")
        return len(self.content)


def task_response(status: ProviderTaskStatus, progress: int) -> TextTo3DTaskResponse:
    return TextTo3DTaskResponse(
        id="provider-task",
        type="text-to-3d-preview",
        status=status,
        progress=progress,
        model_urls=(
            {
                "glb": (
                    "https://assets.meshy.ai/tasks/provider-task/model.glb"
                    "?Expires=1&Signature=secret"
                )
            }
            if status is ProviderTaskStatus.SUCCEEDED
            else {}
        ),
        thumbnail_url=(
            "https://assets.meshy.ai/tasks/provider-task/preview.png"
            "?Expires=1&Signature=thumbnail-secret"
            if status is ProviderTaskStatus.SUCCEEDED
            else None
        ),
    )


def create_and_submit(config, lanes, prompt: Path, transport: LifecycleTransport) -> None:
    initialize_workspace(config.foundry.workspace_root)
    create_asset(
        config,
        lanes,
        "stone_knife_001",
        "static_prop",
        "Stone Knife",
        prompt,
    )
    submit_text_preview(
        config,
        "stone_knife_001",
        transport,
        {"MESHY_API_KEY": "secret-key"},
    )


def test_poll_and_download_lifecycle(config, lanes, prompt: Path) -> None:
    transport = LifecycleTransport(
        [
            task_response(ProviderTaskStatus.PENDING, 10),
            task_response(ProviderTaskStatus.SUCCEEDED, 100),
            task_response(ProviderTaskStatus.SUCCEEDED, 100),
        ]
    )
    create_and_submit(config, lanes, prompt, transport)

    pending = poll_text_task(
        config,
        "stone_knife_001",
        transport,
        environment={"MESHY_API_KEY": "secret-key"},
    )
    assert pending.status is ProviderTaskStatus.PENDING
    assert (
        ManifestRepository(config.foundry.workspace_root).load("stone_knife_001").workflow.state
        is WorkflowState.GENERATING
    )

    succeeded = poll_text_task(
        config,
        "stone_knife_001",
        transport,
        environment={"MESHY_API_KEY": "secret-key"},
    )
    assert succeeded.status is ProviderTaskStatus.SUCCEEDED
    assert (
        ManifestRepository(config.foundry.workspace_root).load("stone_knife_001").workflow.state
        is WorkflowState.SOURCE_READY
    )

    artifact = download_text_preview_glb(
        config,
        "stone_knife_001",
        transport,
        environment={"MESHY_API_KEY": "secret-key"},
    )
    manifest = ManifestRepository(config.foundry.workspace_root).load("stone_knife_001")
    asset_root = config.foundry.workspace_root / "assets" / "stone_knife_001"
    assert transport.download_calls == 2
    assert artifact.sha256 == hashlib.sha256(b"glb-data").hexdigest()
    assert (asset_root / str(artifact.path)).read_bytes() == b"glb-data"
    assert manifest.workflow.state is WorkflowState.DOWNLOADED
    assert manifest.artifacts[0] == artifact
    assert [item.role for item in manifest.artifacts] == [
        "source_model",
        "preview_thumbnail",
    ]
    thumbnail = manifest.artifacts[1]
    assert (asset_root / str(thumbnail.path)).read_bytes() == b"glb-data"
    assert list((config.foundry.workspace_root / "temp").glob("*.part")) == []

    response_evidence = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (asset_root / "provider" / "meshy" / "responses").glob("*.json")
    )
    assert "Signature=secret" not in response_evidence
    assert "secret-key" not in response_evidence


def test_failed_download_removes_partial_file_and_adds_no_artifact(
    config, lanes, prompt: Path
) -> None:
    transport = FailingDownloadTransport(
        [
            task_response(ProviderTaskStatus.SUCCEEDED, 100),
            task_response(ProviderTaskStatus.SUCCEEDED, 100),
        ]
    )
    create_and_submit(config, lanes, prompt, transport)
    poll_text_task(
        config,
        "stone_knife_001",
        transport,
        environment={"MESHY_API_KEY": "secret-key"},
    )
    with pytest.raises(DownloadError, match="connection lost"):
        download_text_preview_glb(
            config,
            "stone_knife_001",
            transport,
            environment={"MESHY_API_KEY": "secret-key"},
        )
    manifest = ManifestRepository(config.foundry.workspace_root).load("stone_knife_001")
    asset_root = config.foundry.workspace_root / "assets" / "stone_knife_001"
    assert manifest.artifacts == []
    assert not any((asset_root / "source").rglob("*.glb"))
    assert list((config.foundry.workspace_root / "temp").glob("*.part")) == []


def test_thumbnail_failure_rolls_back_promoted_model(config, lanes, prompt: Path) -> None:
    transport = FailingThumbnailTransport(
        [
            task_response(ProviderTaskStatus.SUCCEEDED, 100),
            task_response(ProviderTaskStatus.SUCCEEDED, 100),
        ]
    )
    create_and_submit(config, lanes, prompt, transport)
    poll_text_task(
        config,
        "stone_knife_001",
        transport,
        environment={"MESHY_API_KEY": "secret-key"},
    )
    with pytest.raises(DownloadError, match="thumbnail connection lost"):
        download_text_preview_glb(
            config,
            "stone_knife_001",
            transport,
            environment={"MESHY_API_KEY": "secret-key"},
        )
    manifest = ManifestRepository(config.foundry.workspace_root).load("stone_knife_001")
    asset_root = config.foundry.workspace_root / "assets" / "stone_knife_001"
    assert manifest.artifacts == []
    assert not any((asset_root / "source").rglob("*.glb"))
    assert not any((asset_root / "preview").rglob("*.png"))


def test_refine_submission_reuses_durable_paid_action_protocol(config, lanes, prompt: Path) -> None:
    transport = LifecycleTransport([task_response(ProviderTaskStatus.SUCCEEDED, 100)])
    create_and_submit(config, lanes, prompt, transport)
    poll_text_task(
        config,
        "stone_knife_001",
        transport,
        environment={"MESHY_API_KEY": "secret-key"},
    )
    task = submit_text_refine(
        config,
        "stone_knife_001",
        "meshy_preview_001",
        transport,
        environment={"MESHY_API_KEY": "secret-key"},
    )
    manifest = ManifestRepository(config.foundry.workspace_root).load("stone_knife_001")
    asset_root = config.foundry.workspace_root / "assets" / "stone_knife_001"
    request = asset_root / "provider" / "meshy" / "requests" / "meshy_refine_001.json"
    assert task.operation == "text_to_3d_refine"
    assert task.provider_task_id == "provider-refine-task"
    assert task.status is ProviderTaskStatus.PENDING
    assert manifest.workflow.state is WorkflowState.SUBMITTED
    assert json.loads(request.read_text(encoding="utf-8"))["preview_task_id"] == ("provider-task")


def test_select_and_passthrough_processing_creates_distinct_verified_artifact(
    config, lanes, prompt: Path
) -> None:
    transport = LifecycleTransport(
        [
            task_response(ProviderTaskStatus.SUCCEEDED, 100),
            task_response(ProviderTaskStatus.SUCCEEDED, 100),
        ]
    )
    create_and_submit(config, lanes, prompt, transport)
    poll_text_task(
        config,
        "stone_knife_001",
        transport,
        environment={"MESHY_API_KEY": "secret-key"},
    )
    download_text_preview_glb(
        config,
        "stone_knife_001",
        transport,
        environment={"MESHY_API_KEY": "secret-key"},
    )
    select_output(config, "stone_knife_001", "meshy_preview_001")
    processed = process_passthrough(config, "stone_knife_001")
    manifest = ManifestRepository(config.foundry.workspace_root).load("stone_knife_001")
    asset_root = config.foundry.workspace_root / "assets" / "stone_knife_001"
    source = manifest.artifacts[0]

    assert manifest.workflow.state is WorkflowState.PROCESSED
    assert manifest.generation.selected_task_key == "meshy_preview_001"
    assert processed.derived_from == [source.artifact_id]
    assert processed.source_task_key == "meshy_preview_001"
    assert processed.processor is not None
    assert processed.processor.name == "passthrough"
    assert (asset_root / str(processed.path)).read_bytes() == b"glb-data"
    assert (asset_root / str(processed.path)).stat().st_ino != (
        asset_root / str(source.path)
    ).stat().st_ino


def test_remesh_uses_lane_sized_explicit_paid_attempt(config, lanes, prompt: Path) -> None:
    transport = LifecycleTransport([task_response(ProviderTaskStatus.SUCCEEDED, 100)])
    create_and_submit(config, lanes, prompt, transport)
    poll_text_task(
        config,
        "stone_knife_001",
        transport,
        environment={"MESHY_API_KEY": "secret-key"},
    )
    task = submit_remesh(
        config,
        "stone_knife_001",
        2500,
        transport,
        environment={"MESHY_API_KEY": "secret-key"},
    )
    asset_root = config.foundry.workspace_root / "assets" / "stone_knife_001"
    request = json.loads(
        (asset_root / "provider/meshy/requests/meshy_remesh_001.json").read_text(encoding="utf-8")
    )
    assert task.operation == "remesh"
    assert task.provider_task_id == "provider-remesh-task"
    assert request["input_task_id"] == "provider-task"
    assert request["target_polycount"] == 2500
    assert request["topology"] == "triangle"
