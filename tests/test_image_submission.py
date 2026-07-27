import json
from pathlib import Path

import pytest

from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.provider import ProviderTaskStatus
from vandrel_foundry.providers.meshy.models import CreateTaskResponse, ImageTo3DRequest
from vandrel_foundry.services.add_reference import add_reference_image
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.inspect_assets import initialize_workspace
from vandrel_foundry.services.submit_preview import submit_image_to_3d
from vandrel_foundry.storage.manifests import ManifestRepository


class ImageTransport:
    def __init__(self, repository: ManifestRepository) -> None:
        self.repository = repository
        self.received: ImageTo3DRequest | None = None
        self.observed_status: ProviderTaskStatus | None = None

    def create_image_task(
        self,
        request: ImageTo3DRequest,
        api_key: str,
    ) -> CreateTaskResponse:
        self.received = request
        manifest = self.repository.load("stone_knife_001")
        self.observed_status = manifest.generation.tasks[-1].status
        assert api_key == "secret-key"
        return CreateTaskResponse(result="image-provider-task")


def _create_draft(config, lanes, prompt: Path) -> None:
    initialize_workspace(config.foundry.workspace_root)
    create_asset(
        config,
        lanes,
        "stone_knife_001",
        "static_prop",
        "Stone Knife",
        prompt,
    )


def test_image_is_copied_and_submission_evidence_redacts_data(config, lanes, prompt, tmp_path):
    _create_draft(config, lanes, prompt)
    image = tmp_path / "reference.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"local-image")
    relative = add_reference_image(config, "stone_knife_001", image)
    repository = ManifestRepository(config.foundry.workspace_root)
    transport = ImageTransport(repository)

    task = submit_image_to_3d(
        config,
        "stone_knife_001",
        transport,
        environment={"MESHY_API_KEY": "secret-key"},
    )

    asset_root = config.foundry.workspace_root / "assets" / "stone_knife_001"
    manifest = repository.load("stone_knife_001")
    evidence = json.loads((asset_root / str(task.request_path)).read_text(encoding="utf-8"))
    assert relative == "input/references/reference_001.png"
    assert (asset_root / str(relative)).read_bytes() == image.read_bytes()
    assert manifest.input.kind == "image"
    assert transport.observed_status is ProviderTaskStatus.SUBMITTING
    assert transport.received is not None
    assert transport.received.image_url.startswith("data:image/png;base64,")
    assert evidence["image_url"] == "[REDACTED_DATA_URI]"
    assert "local-image" not in json.dumps(evidence)
    assert task.operation == "image_to_3d"
    assert task.provider_task_id == "image-provider-task"


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("fake.png", b"not-a-png"),
        ("fake.jpg", b"not-a-jpeg"),
        ("fake.gif", b"GIF89a"),
    ],
)
def test_reference_rejects_mislabeled_or_unsupported_files(
    config, lanes, prompt, tmp_path, name, content
):
    _create_draft(config, lanes, prompt)
    image = tmp_path / name
    image.write_bytes(content)
    with pytest.raises(FoundryError, match="signature|PNG|JPG|JPEG"):
        add_reference_image(config, "stone_knife_001", image)
    manifest = ManifestRepository(config.foundry.workspace_root).load("stone_knife_001")
    assert manifest.input.reference_images == []
