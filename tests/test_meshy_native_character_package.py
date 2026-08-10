import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image

import vandrel_foundry.services.inspect_meshy_native_character as inspection_service
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.lanes import LaneConfiguration
from vandrel_foundry.domain.manifest import Artifact
from vandrel_foundry.services.add_meshy_native_character_package import (
    add_meshy_native_character_package,
)
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.validate_godot import ProcessResult
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.save_journal import SaveDiagnosis


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


def _metadata() -> dict[str, str]:
    return {
        "source_task_id": "source",
        "source_display_name": "Source",
        "remesh_task_id": "remesh",
        "remesh_face_count": "1",
        "rig_task_id": "rig",
        "excluded_duplicate_rig_task_id": "",
    }


def _zip(path: Path, extra: bool = False) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("package/Character_output.fbx", b"character")
        archive.writestr("package/Animation_Walking_withSkin.fbx", b"walking")
        archive.writestr("package/texture_0.png", b"texture")
        if extra:
            archive.writestr("package/unexpected.txt", b"extra")


def _candidate(config, prompt: Path, tmp_path: Path):
    config.tools.blender_executable = prompt
    create_asset(config, _lanes(), "native_character_test_001", "humanoid", "Native", prompt)
    archive = tmp_path / "character.zip"
    _zip(archive)
    add_meshy_native_character_package(
        config,
        "native_character_test_001",
        archive,
        hashlib.sha256(archive.read_bytes()).hexdigest(),
        _metadata(),
    )
    repository = ManifestRepository(config.foundry.workspace_root)
    return repository, repository.asset_directory("native_character_test_001")


def _adapter(*, hierarchy=None, character_bind="a" * 64, walking_bind="a" * 64, duration=1.0):
    hierarchy = hierarchy or {"Hips": None}
    facts = {
        "armature_count": 1,
        "mesh_count": 1,
        "skinned_mesh_count": 1,
        "joint_count": len(hierarchy),
        "joint_hierarchy": hierarchy,
        "vertex_count": 3,
        "polygon_count": 1,
        "material_slot_count": 1,
        "image_count": 1,
        "unweighted_vertex_count": 0,
    }
    return {
        "schema": "vandrel_foundry_meshy_native_character_adapter/1.0",
        "blender_version": "Blender-test",
        "character": {**facts, "bind_signature": character_bind, "actions": []},
        "walking": {
            **facts,
            "bind_signature": walking_bind,
            "actions": [{"name": "walking", "duration_seconds": duration}],
        },
        "frame_files": ["000.png", "0001.png"],
    }


def _runner(adapter):
    def run(arguments, *_unused):
        separator = arguments.index("--")
        frames = Path(arguments[separator + 3])
        report = Path(arguments[separator + 4])
        frames.mkdir()
        Image.new("RGB", (4, 4), "white").save(frames / "000.png")
        Image.new("RGB", (4, 4), "gray").save(frames / "0001.png")
        report.write_text(json.dumps(adapter), encoding="utf-8")
        return ProcessResult(0, "ok", "", False, False, 0.1)

    return run


def _compatibility(*_args):
    return {"current_canary": "fake"}


def test_intake_retains_exact_four_roots_and_user_observed_metadata(config, prompt, tmp_path):
    create_asset(config, _lanes(), "native_character_test_001", "humanoid", "Native", prompt)
    archive = tmp_path / "character.zip"
    _zip(archive)
    artifacts = add_meshy_native_character_package(
        config,
        "native_character_test_001",
        archive,
        hashlib.sha256(archive.read_bytes()).hexdigest().upper(),
        _metadata(),
    )
    assert len(artifacts) == 5
    repository = ManifestRepository(config.foundry.workspace_root)
    root = repository.asset_directory("native_character_test_001")
    report = json.loads((root / "source/meshy_native_character_package_001/intake-report.json").read_text())
    assert report["provider_metadata_observation"] == "user_observed_provider_metadata"
    assert report["provider_metadata"] == _metadata()
    assert report["license_metadata"] == "not_inspected"
    assert report["provider_download"] == "not_performed_by_intake_service"
    assert {item.artifact_id for item in artifacts if not item.derived_from} == {
        "meshy_native_character_archive_root_001",
        "meshy_native_character_fbx_root_001",
        "meshy_native_walking_fbx_root_001",
        "meshy_native_character_texture_root_001",
    }


def test_intake_rejects_extra_zip_member_before_candidate_mutation(config, prompt, tmp_path):
    create_asset(config, _lanes(), "native_character_test_001", "humanoid", "Native", prompt)
    archive = tmp_path / "character.zip"
    _zip(archive, extra=True)
    with pytest.raises(FoundryError, match="exactly three"):
        add_meshy_native_character_package(
            config,
            "native_character_test_001",
            archive,
            hashlib.sha256(archive.read_bytes()).hexdigest(),
            _metadata(),
        )
    repository = ManifestRepository(config.foundry.workspace_root)
    assert repository.load("native_character_test_001").artifacts == []


@pytest.mark.parametrize("mode", ["missing", "extra", "duplicate", "wrong_role"])
def test_inspection_requires_exact_four_root_union(config, prompt, tmp_path, monkeypatch, mode):
    repository, root = _candidate(config, prompt, tmp_path)
    manifest = repository.load("native_character_test_001")
    roots = [item for item in manifest.artifacts if item.stage == "source" and not item.derived_from]
    if mode == "missing":
        manifest.artifacts.remove(roots[0])
    elif mode == "extra":
        path = root / "source/extra.bin"
        path.write_bytes(b"extra")
        manifest.artifacts.append(
            Artifact(
                artifact_id="extra_root_001", role="extra", stage="source", format="bin",
                path="source/extra.bin", sha256=hashlib.sha256(b"extra").hexdigest(), size_bytes=5,
            )
        )
    elif mode == "duplicate":
        manifest.artifacts.append(roots[0].model_copy(update={"path": "source/duplicate.zip"}))
        (root / "source/duplicate.zip").write_bytes((root / roots[0].path).read_bytes())
    else:
        index = manifest.artifacts.index(roots[0])
        manifest.artifacts[index] = roots[0].model_copy(update={"role": "wrong"})
    revision = manifest.revision
    manifest.revision += 1
    repository.save(manifest, expected_revision=revision)
    monkeypatch.setattr(inspection_service, "_canary_compatibility", _compatibility)
    with pytest.raises(FoundryError, match="exact four-root union|roles or formats"):
        inspection_service.inspect_meshy_native_character(config, "native_character_test_001", _runner(_adapter()))
    assert not list((root / "preview").glob("**/*")) if (root / "preview").exists() else True


def test_inspection_rechecks_roots_after_compatibility_before_promotion(config, prompt, tmp_path, monkeypatch):
    repository, root = _candidate(config, prompt, tmp_path)
    before = repository.load("native_character_test_001")
    character_path = root / "source/meshy_native_character_package_001/character.fbx"
    original = character_path.read_bytes()

    def mutate(*_args):
        character_path.write_bytes(b"mutated after first verification")
        return _compatibility()

    monkeypatch.setattr(inspection_service, "_canary_compatibility", mutate)
    with pytest.raises(FoundryError, match="input changed"):
        inspection_service.inspect_meshy_native_character(config, "native_character_test_001", _runner(_adapter()))
    assert repository.load("native_character_test_001").model_dump(mode="json") == before.model_dump(mode="json")
    assert not list((root / "preview").glob("meshy-native-character-*"))
    assert not list((root / "reports").glob("meshy-native-character-inspection-*"))
    character_path.write_bytes(original)


def test_inspection_partial_adapter_output_rolls_back_before_commit(config, prompt, tmp_path, monkeypatch):
    repository, root = _candidate(config, prompt, tmp_path)
    before = repository.load("native_character_test_001")

    def partial(arguments, *_unused):
        separator = arguments.index("--")
        Path(arguments[separator + 3]).mkdir()
        Path(arguments[separator + 4]).write_text("{}", encoding="utf-8")
        return ProcessResult(0, "ok", "", False, False, 0.1)

    monkeypatch.setattr(inspection_service, "_canary_compatibility", _compatibility)
    with pytest.raises(FoundryError, match="adapter report is invalid"):
        inspection_service.inspect_meshy_native_character(config, "native_character_test_001", partial)
    assert repository.load("native_character_test_001").model_dump(mode="json") == before.model_dump(mode="json")
    assert not list((root / "preview").glob("meshy-native-character-*"))


@pytest.mark.parametrize("status", ["event_missing", "event_partial", "event_complete"])
def test_inspection_preserves_exact_committed_targets_after_lock_exit_ambiguity(
    config, prompt, tmp_path, monkeypatch, status
):
    repository, root = _candidate(config, prompt, tmp_path)
    before = repository.load("native_character_test_001")
    original_save = ManifestRepository.save

    def save_then_raise(self, *args, **kwargs):
        original_save(self, *args, **kwargs)
        raise OSError("simulated lock exit after committed manifest")

    monkeypatch.setattr(inspection_service, "_canary_compatibility", _compatibility)
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
    report = inspection_service.inspect_meshy_native_character(
        config, "native_character_test_001", _runner(_adapter())
    )
    live = repository.load("native_character_test_001")
    assert live.revision == before.revision + 1
    assert any(item.artifact_id == report.artifact_id for item in live.artifacts)
    for artifact in [item for item in live.artifacts if item.artifact_id.endswith("_001") and item.stage in {"review", "processing"}]:
        assert (root / artifact.path).is_file()


@pytest.mark.parametrize(
    ("adapter", "message"),
    [
        (_adapter(hierarchy={"Hips": None}), "hierarchies do not match"),
        (_adapter(character_bind="a" * 64, walking_bind="b" * 64), "bind signatures do not match"),
        (_adapter(duration=0.0), "Walking duration is invalid"),
    ],
)
def test_inspection_gates_hierarchy_bind_and_duration_mismatch(
    config, prompt, tmp_path, monkeypatch, adapter, message
):
    if "hierarchies" in message:
        adapter["walking"]["joint_hierarchy"] = {"Other": None}
        adapter["walking"]["joint_count"] = 1
    repository, root = _candidate(config, prompt, tmp_path)
    before = repository.load("native_character_test_001")
    monkeypatch.setattr(inspection_service, "_canary_compatibility", _compatibility)
    with pytest.raises(FoundryError, match=message):
        inspection_service.inspect_meshy_native_character(config, "native_character_test_001", _runner(adapter))
    assert repository.load("native_character_test_001").model_dump(mode="json") == before.model_dump(mode="json")
    assert not list((root / "preview").glob("meshy-native-character-*"))
