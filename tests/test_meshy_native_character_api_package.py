import hashlib
import io
import json
import struct
from pathlib import Path

import pytest
from PIL import Image
from typer.testing import CliRunner

import vandrel_foundry.services.add_meshy_native_character_package as intake_service
import vandrel_foundry.services.inspect_meshy_native_character as inspection_service
from vandrel_foundry.cli import app
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.lanes import LaneConfiguration
from vandrel_foundry.services.add_meshy_native_character_package import (
    API_CHARACTER_SOURCE,
    add_meshy_native_character_api_package,
)
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.validate_godot import ProcessResult
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.save_journal import SaveDiagnosis

RUNNER = CliRunner()


def _lanes() -> LaneConfiguration:
    return LaneConfiguration.model_validate(
        {
            "lanes": {
                "humanoid": {
                    "wrapper_template": "humanoid_candidate",
                    "collision_policy": "manual_review",
                    "requires_materials": True,
                    "requires_skeleton": True,
                    "release_enabled": False,
                }
            }
        }
    )


def _glb(path: Path) -> bytes:
    image_buffer = io.BytesIO()
    Image.new("RGBA", (1, 1), (90, 100, 110, 255)).save(image_buffer, format="PNG")
    image = image_buffer.getvalue()
    binary = image + b"\0" * (-len(image) % 4)
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(image)}],
        "images": [{"name": "texture_0", "bufferView": 0, "mimeType": "image/png"}],
        "nodes": [{"name": "Hips" if index == 0 else f"joint_{index}"} for index in range(24)],
        "skins": [{"joints": list(range(24))}],
    }
    payload = json.dumps(document, separators=(",", ":")).encode()
    payload += b" " * (-len(payload) % 4)
    value = (
        struct.pack("<4sII", b"glTF", 2, 28 + len(payload) + len(binary))
        + struct.pack("<II", len(payload), 0x4E4F534A)
        + payload
        + struct.pack("<II", len(binary), 0x004E4942)
        + binary
    )
    path.write_bytes(value)
    return image


def _outputs(tmp_path: Path) -> tuple[dict[str, Path], bytes]:
    values = {
        "character_fbx": tmp_path / "Character_output.fbx",
        "character_glb": tmp_path / "Character_output.glb",
        "walking_fbx": tmp_path / "Animation_Walking_withSkin.fbx",
        "running_fbx": tmp_path / "Animation_Running_withSkin.fbx",
    }
    values["character_fbx"].write_bytes(b"character")
    texture = _glb(values["character_glb"])
    values["walking_fbx"].write_bytes(b"walking")
    values["running_fbx"].write_bytes(b"running")
    return values, texture


def _metadata() -> dict[str, object]:
    return {
        "source_task_id": "source-task",
        "source_display_name": "Exact provider model",
        "remesh_task_id": "remesh-task",
        "remesh_face_count": 5128,
        "remesh_vertex_count": 7756,
        "rig_task_id": "rig-task",
        "stable_vandrel_character_id": "caveman_meshy_feral_apeman_low_poly",
        "rig_status": "SUCCEEDED",
        "rig_progress": 100,
        "consumed_credits": 0,
        "provider_balance_before": 1099,
        "provider_balance_after": 1099,
        "created_at_epoch_ms": 1,
        "started_at_epoch_ms": 2,
        "finished_at_epoch_ms": 3,
    }


def _candidate(config, prompt: Path, tmp_path: Path):
    config.tools.blender_executable = prompt
    create_asset(config, _lanes(), "native_api_test_001", "humanoid", "Native API", prompt)
    outputs, texture = _outputs(tmp_path)
    hashes = {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in outputs.items()}
    artifacts = add_meshy_native_character_api_package(
        config,
        "native_api_test_001",
        outputs,
        hashes,
        _metadata(),
    )
    repository = ManifestRepository(config.foundry.workspace_root)
    return repository, repository.asset_directory("native_api_test_001"), outputs, texture, artifacts


def test_api_intake_retains_exact_provider_roots_and_derived_texture(config, prompt, tmp_path):
    repository, root, _outputs_value, texture, artifacts = _candidate(config, prompt, tmp_path)
    roots = {item.artifact_id for item in artifacts if not item.derived_from}
    assert roots == API_CHARACTER_SOURCE.root_ids
    texture_artifact = next(item for item in artifacts if item.artifact_id == API_CHARACTER_SOURCE.texture_artifact_id)
    assert texture_artifact.derived_from == ["meshy_native_character_glb_root_001"]
    assert (root / texture_artifact.path).read_bytes() == texture
    report_artifact = next(item for item in artifacts if item.role == "meshy_native_character_intake_report")
    report = json.loads((root / report_artifact.path).read_text(encoding="utf-8"))
    assert report["provider_metadata"] == _metadata()
    assert report["provider_metadata"]["consumed_credits"] == 0
    assert report["license_metadata"] == "not_inspected"
    assert report["signed_urls_retained"] is False
    assert repository.load("native_api_test_001").workflow.state.value == "downloaded"


def test_api_intake_detects_late_source_mutation_before_commit(
    config, prompt, tmp_path, monkeypatch
):
    create_asset(config, _lanes(), "native_api_test_001", "humanoid", "Native API", prompt)
    outputs, _texture = _outputs(tmp_path)
    hashes = {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in outputs.items()}
    original = intake_service._extract_embedded_png

    def mutate(glb_path, destination):
        result = original(glb_path, destination)
        outputs["walking_fbx"].write_bytes(b"mutated after copy")
        return result

    monkeypatch.setattr(intake_service, "_extract_embedded_png", mutate)
    with pytest.raises(FoundryError, match="changed before transaction completion"):
        add_meshy_native_character_api_package(
            config,
            "native_api_test_001",
            outputs,
            hashes,
            _metadata(),
        )
    repository = ManifestRepository(config.foundry.workspace_root)
    assert repository.load("native_api_test_001").artifacts == []
    assert not (repository.asset_directory("native_api_test_001") / "source/meshy_native_character_api_package_001").exists()


def test_api_intake_rejects_incomplete_provider_output_union(config, prompt, tmp_path):
    create_asset(config, _lanes(), "native_api_test_001", "humanoid", "Native API", prompt)
    outputs, _texture = _outputs(tmp_path)
    outputs.pop("running_fbx")
    hashes = {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in outputs.items()}
    with pytest.raises(FoundryError, match="exact four provider outputs"):
        add_meshy_native_character_api_package(
            config,
            "native_api_test_001",
            outputs,
            hashes,
            _metadata(),
        )
    assert ManifestRepository(config.foundry.workspace_root).load("native_api_test_001").artifacts == []


@pytest.mark.parametrize("status", ["event_missing", "event_partial", "event_complete"])
def test_api_intake_preserves_exact_committed_target_after_save_ambiguity(
    config, prompt, tmp_path, monkeypatch, status
):
    create_asset(config, _lanes(), "native_api_test_001", "humanoid", "Native API", prompt)
    outputs, _texture = _outputs(tmp_path)
    hashes = {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in outputs.items()}
    original_save = ManifestRepository.save

    def save_then_raise(self, *args, **kwargs):
        original_save(self, *args, **kwargs)
        raise OSError("simulated lock exit after committed manifest")

    monkeypatch.setattr(ManifestRepository, "save", save_then_raise)
    monkeypatch.setattr(
        ManifestRepository,
        "diagnose_pending_save",
        lambda *_args: SaveDiagnosis(status, "simulated post-replace state"),
    )
    monkeypatch.setattr(
        ManifestRepository,
        "reconcile_pending_save",
        lambda *_args: SaveDiagnosis("complete", "simulated reconciliation"),
    )
    artifacts = add_meshy_native_character_api_package(
        config,
        "native_api_test_001",
        outputs,
        hashes,
        _metadata(),
    )
    repository = ManifestRepository(config.foundry.workspace_root)
    live = repository.load("native_api_test_001")
    root = repository.asset_directory("native_api_test_001")
    assert live.revision == 2
    assert all((root / item.path).is_file() for item in artifacts)
    assert all(
        next(value for value in live.artifacts if value.artifact_id == item.artifact_id)
        == item
        for item in artifacts
    )


def test_api_inspection_requires_and_binds_running_fbx(config, prompt, tmp_path, monkeypatch):
    repository, root, _outputs_value, _texture, _artifacts = _candidate(config, prompt, tmp_path)

    def compatibility(*_args):
        return {"current_canary": "fake"}

    def runner(arguments, *_unused):
        separator = arguments.index("--")
        assert arguments[separator + 3].endswith("running.fbx")
        frames = Path(arguments[separator + 4])
        report = Path(arguments[separator + 5])
        frames.mkdir()
        Image.new("RGB", (4, 4), "white").save(frames / "0000.png")
        Image.new("RGB", (4, 4), "gray").save(frames / "0001.png")
        facts = {
            "armature_count": 1,
            "mesh_count": 1,
            "skinned_mesh_count": 1,
            "joint_count": 24,
            "joint_hierarchy": {"Hips": None, **{f"joint_{i}": "Hips" for i in range(1, 24)}},
            "vertex_count": 3,
            "polygon_count": 1,
            "material_slot_count": 1,
            "image_count": 1,
            "unweighted_vertex_count": 0,
            "bind_signature": "a" * 64,
        }
        report.write_text(
            json.dumps(
                {
                    "schema": "vandrel_foundry_meshy_native_character_adapter/1.0",
                    "blender_version": "Blender-test",
                    "character": {**facts, "actions": []},
                    "walking": {**facts, "actions": [{"name": "Walking", "duration_seconds": 1.0}]},
                    "running": {**facts, "actions": [{"name": "Running", "duration_seconds": 0.8}]},
                    "frame_files": ["0000.png", "0001.png"],
                }
            ),
            encoding="utf-8",
        )
        return ProcessResult(0, "ok", "", False, False, 0.1)

    monkeypatch.setattr(inspection_service, "_canary_compatibility", compatibility)
    report = inspection_service.inspect_meshy_native_character(
        config, "native_api_test_001", runner, "1099/1099"
    )
    data = json.loads((root / report.path).read_text(encoding="utf-8"))
    assert data["source_profile"] == "provider_api_direct"
    assert set(data["source_union"]) == API_CHARACTER_SOURCE.root_ids
    assert data["running"]["actions"][0]["name"] == "Running"
    assert repository.load("native_api_test_001").workflow.state.value == "processed"


def test_api_intake_and_representative_playback_profiles_are_exposed_by_thin_cli():
    result = RUNNER.invoke(
        app,
        ["add-meshy-native-character-api-package", "--help"],
        env={"COLUMNS": "240"},
    )
    assert result.exit_code == 0
    for option in (
        "--character-fbx",
        "--character-glb",
        "--walking-fbx",
        "--running-fbx",
        "--consumed-credits",
        "--stable-vandrel-character-id",
    ):
        assert option in result.output
    result = RUNNER.invoke(
        app,
        ["assemble-meshy-native-character-motion", "--help"],
        env={"COLUMNS": "240"},
    )
    assert result.exit_code == 0
    assert "--playback-profile" in result.output
