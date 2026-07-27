import hashlib
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from vandrel_foundry.domain.errors import DownloadError
from vandrel_foundry.domain.manifest import Artifact
from vandrel_foundry.domain.provider import ProviderTaskStatus
from vandrel_foundry.providers.meshy.models import (
    CreateTaskResponse,
    RetextureRequest,
    RetextureTaskResponse,
    RiggingRequest,
    RiggingResult,
    RiggingTaskResponse,
    TextureUrls,
)
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.download_artifact import download_text_preview_glb
from vandrel_foundry.services.inspect_assets import initialize_workspace
from vandrel_foundry.services.poll_task import poll_text_task
from vandrel_foundry.services.quantize_semantic_mask import PALETTE, quantize_semantic_mask
from vandrel_foundry.services.submit_preview import submit_retexture, submit_rigging
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath


class CharacterTransport:
    def __init__(self) -> None:
        self.retexture_requests: list[RetextureRequest] = []
        self.rigging_requests: list[RiggingRequest] = []

    def create_retexture_task(
        self,
        request: RetextureRequest,
        api_key: str,
    ) -> CreateTaskResponse:
        self.retexture_requests.append(request)
        suffix = "beauty" if request.enable_pbr else "semantic"
        return CreateTaskResponse(result=f"{suffix}-provider-id")

    def create_rigging_task(
        self,
        request: RiggingRequest,
        api_key: str,
    ) -> CreateTaskResponse:
        self.rigging_requests.append(request)
        return CreateTaskResponse(result="rig-provider-id")

    def retrieve_retexture_task(
        self,
        provider_task_id: str,
        api_key: str,
    ) -> RetextureTaskResponse:
        semantic = provider_task_id.startswith("semantic")
        return RetextureTaskResponse(
            id=provider_task_id,
            status=ProviderTaskStatus.SUCCEEDED,
            progress=100,
            model_urls={"glb": f"https://assets.meshy.ai/{provider_task_id}.glb"},
            texture_urls=(
                [TextureUrls(base_color="https://assets.meshy.ai/semantic.png")] if semantic else []
            ),
            consumed_credits=10,
        )

    def retrieve_rigging_task(
        self,
        provider_task_id: str,
        api_key: str,
    ) -> RiggingTaskResponse:
        return RiggingTaskResponse(
            id=provider_task_id,
            status=ProviderTaskStatus.SUCCEEDED,
            progress=100,
            result=RiggingResult(
                rigged_character_fbx_url="https://assets.meshy.ai/rigged.fbx",
                rigged_character_glb_url="https://assets.meshy.ai/rigged.glb",
                basic_animations={
                    "walking_glb_url": "https://assets.meshy.ai/walking.glb",
                    "running_glb_url": "https://assets.meshy.ai/running.glb",
                    "walking_fbx_url": "https://assets.meshy.ai/walking.fbx",
                    "running_fbx_url": "https://assets.meshy.ai/running.fbx",
                },
            ),
            consumed_credits=5,
        )

    def download_file(self, url: str, destination: Path) -> int:
        if url.endswith(".png"):
            image = Image.new("RGB", (2, 2))
            image.putdata([(250, 4, 4), (4, 250, 4), (4, 4, 250), (250, 250, 250)])
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            content = buffer.getvalue()
        else:
            content = b"downloaded-glb"
        destination.write_bytes(content)
        return len(content)


def _create_character(config, lanes, prompt: Path) -> None:
    initialize_workspace(config.foundry.workspace_root)
    manifest = create_asset(
        config,
        lanes,
        "character_001",
        "static_prop",
        "Character",
        prompt,
    )
    relative = RelativeManifestPath("processed/original.glb")
    path = config.foundry.workspace_root / "assets/character_001" / str(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = b"original-glb"
    path.write_bytes(content)
    manifest.artifacts.append(
        Artifact(
            artifact_id="processed_glb_001",
            role="processed_model",
            stage="processed",
            format="glb",
            path=relative,
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
        )
    )
    manifest.revision += 1
    ManifestRepository(config.foundry.workspace_root).save(
        manifest,
        "fixture.artifact_added",
        expected_revision=manifest.revision - 1,
    )


def test_direct_character_retexture_mask_and_rigging_corridor(config, lanes, prompt: Path) -> None:
    _create_character(config, lanes, prompt)
    transport = CharacterTransport()
    environment = {"MESHY_API_KEY": "secret-key"}

    beauty = submit_retexture(
        config,
        "character_001",
        "processed_glb_001",
        "natural fur, skin, and layered travel clothing",
        transport,
        task_label="beauty",
        enable_pbr=True,
        environment=environment,
    )
    poll_text_task(
        config,
        "character_001",
        transport,
        beauty.task_key,
        environment,
    )
    semantic = submit_retexture(
        config,
        "character_001",
        "processed_glb_001",
        "flat red skin, green fur, blue cloth, white accessories",
        transport,
        task_label="semantic",
        enable_pbr=False,
        environment=environment,
    )
    poll_text_task(
        config,
        "character_001",
        transport,
        semantic.task_key,
        environment,
    )
    polled = ManifestRepository(config.foundry.workspace_root).load("character_001")
    assert polled.generation.tasks[-1].consumed_credits == 10
    download_text_preview_glb(
        config,
        "character_001",
        transport,
        semantic.task_key,
        environment,
    )
    mask = quantize_semantic_mask(config, "character_001")
    rig = submit_rigging(
        config,
        "character_001",
        beauty.task_key,
        1.8,
        transport,
        environment,
    )

    asset_root = config.foundry.workspace_root / "assets/character_001"
    request_evidence = json.loads(
        (asset_root / "provider/meshy/requests/meshy_retexture_beauty_001.json").read_text()
    )
    assert request_evidence["model_url"] == "[REDACTED_DATA_URI]"
    assert transport.retexture_requests[0].enable_original_uv is True
    assert transport.rigging_requests[0].input_task_id == "beauty-provider-id"
    assert rig.provider_task_id == "rig-provider-id"

    poll_text_task(
        config,
        "character_001",
        transport,
        rig.task_key,
        environment,
    )
    downloaded_rig = download_text_preview_glb(
        config,
        "character_001",
        transport,
        rig.task_key,
        environment,
    )
    downloaded_manifest = ManifestRepository(config.foundry.workspace_root).load("character_001")
    assert downloaded_rig.role == "source_model"
    animation_sources = [
        artifact
        for artifact in downloaded_manifest.artifacts
        if artifact.role in {"source_animation_walk", "source_animation_run"}
    ]
    assert [artifact.artifact_id for artifact in animation_sources] == [
        "source_animation_walk_glb_001",
        "source_animation_run_glb_001",
        "source_animation_walk_fbx_002",
        "source_animation_run_fbx_002",
    ]
    assert [artifact.role for artifact in animation_sources] == [
        "source_animation_walk",
        "source_animation_run",
        "source_animation_walk",
        "source_animation_run",
    ]
    assert all(artifact.source_task_key == rig.task_key for artifact in animation_sources)
    assert any(
        artifact.role == "source_model" and artifact.format == "fbx"
        for artifact in downloaded_manifest.artifacts
    )
    artifact_count = len(downloaded_manifest.artifacts)
    with pytest.raises(DownloadError, match="already downloaded"):
        download_text_preview_glb(
            config,
            "character_001",
            transport,
            rig.task_key,
            environment,
        )
    assert (
        len(ManifestRepository(config.foundry.workspace_root).load("character_001").artifacts)
        == artifact_count
    )

    with Image.open(asset_root / str(mask.path)) as image:
        rgb = image.convert("RGB")
        pixels = rgb.load()
        assert {pixels[x, y] for y in range(rgb.height) for x in range(rgb.width)} == set(
            PALETTE.values()
        )
    report = json.loads(
        (asset_root / "reports/semantic_mask_report_001.json").read_text(encoding="utf-8")
    )
    assert report["palette_fidelity_passed"] is True
    assert report["class_coverage_passed"] is True
    assert report["usable_for_material_authoring"] is True


def test_semantic_quantizer_rejects_low_fidelity_source(config, lanes, prompt: Path) -> None:
    _create_character(config, lanes, prompt)
    asset_root = config.foundry.workspace_root / "assets/character_001"
    relative = RelativeManifestPath("masks/poor-semantic-source.png")
    path = asset_root / str(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (2, 2), (128, 128, 128)).save(path)
    content = path.read_bytes()
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load("character_001")
    manifest.artifacts.append(
        Artifact(
            artifact_id="semantic_mask_source_001",
            role="semantic_mask_source",
            stage="masks",
            format="png",
            path=relative,
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
        )
    )
    manifest.revision += 1
    repository.save(
        manifest,
        "fixture.semantic_source_added",
        expected_revision=manifest.revision - 1,
    )

    quantize_semantic_mask(config, "character_001")
    report = json.loads(
        (asset_root / "reports/semantic_mask_report_001.json").read_text(encoding="utf-8")
    )
    assert report["palette_fidelity_passed"] is False
    assert report["class_coverage_passed"] is False
    assert report["usable_for_material_authoring"] is False
