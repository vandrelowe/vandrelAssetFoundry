import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

import vandrel_foundry.storage.manifests as manifest_storage
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.lanes import LaneConfiguration
from vandrel_foundry.domain.manifest import Artifact, Processor
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.add_compound_creature_sources import (
    add_compound_creature_sources,
)
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.render_creature_playback import render_creature_playback
from vandrel_foundry.services.user_local_use_custody import bind_user_local_use_custody
from vandrel_foundry.services.validate_godot import ProcessResult
from vandrel_foundry.storage.locks import AssetLock
from vandrel_foundry.storage.manifests import ManifestRepository


def _lanes() -> LaneConfiguration:
    return LaneConfiguration.model_validate(
        {
            "lanes": {
                "creature": {
                    "wrapper_template": "creature_candidate",
                    "collision_policy": "manual_review",
                    "requires_materials": True,
                    "requires_skeleton": True,
                    "release_enabled": True,
                }
            }
        }
    )


def _inputs(tmp_path: Path) -> tuple[Path, list[Path], Path]:
    mesh = tmp_path / "doe.fbx"
    textures = [tmp_path / "base.png", tmp_path / "normal.png"]
    donor = tmp_path / "Deer.gltf"
    for path, content in [
        (mesh, b"mesh"),
        (textures[0], b"base"),
        (textures[1], b"normal"),
        (donor, b"donor"),
    ]:
        path.write_bytes(content)
    return mesh, textures, donor


def _candidate(config, prompt: Path, tmp_path: Path):
    create_asset(config, _lanes(), "doe_service_001", "creature", "Doe", prompt)
    values = _inputs(tmp_path)
    return values, ManifestRepository(config.foundry.workspace_root)


def test_source_intake_direct_and_retry_are_exact(config, prompt, tmp_path):
    values, repository = _candidate(config, prompt, tmp_path)
    first = add_compound_creature_sources(config, "doe_service_001", *values)
    second = add_compound_creature_sources(config, "doe_service_001", *values)

    assert [item.model_dump() for item in second] == [item.model_dump() for item in first]
    assert repository.load("doe_service_001").workflow.state is WorkflowState.DOWNLOADED


def test_source_intake_retry_rehashes_manifest_owned_destination(
    config, prompt, tmp_path
):
    values, repository = _candidate(config, prompt, tmp_path)
    roots = add_compound_creature_sources(config, "doe_service_001", *values)
    root = repository.asset_directory("doe_service_001")
    (root / roots[0].path).write_bytes(b"changed")

    with pytest.raises(FoundryError, match="Manifest-owned compound root"):
        add_compound_creature_sources(config, "doe_service_001", *values)


def test_source_intake_precommit_failure_rolls_back(config, prompt, tmp_path, monkeypatch):
    values, repository = _candidate(config, prompt, tmp_path)
    monkeypatch.setattr(ManifestRepository, "save", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("precommit")))

    with pytest.raises(OSError, match="precommit"):
        add_compound_creature_sources(config, "doe_service_001", *values)

    root = repository.asset_directory("doe_service_001")
    assert not (root / "source" / "compound_roots_001").exists()


def test_source_intake_ambiguous_live_state_preserves_promoted_bytes(
    config, prompt, tmp_path, monkeypatch
):
    values, repository = _candidate(config, prompt, tmp_path)
    original_load = ManifestRepository.load
    calls = 0

    def fail_save(*args, **kwargs):
        raise OSError("ambiguous save")

    def ambiguous_load(self, asset_id):
        nonlocal calls
        live = original_load(self, asset_id)
        calls += 1
        if calls > 1:
            live.revision += 99
        return live

    monkeypatch.setattr(ManifestRepository, "save", fail_save)
    monkeypatch.setattr(ManifestRepository, "load", ambiguous_load)
    with pytest.raises(OSError, match="ambiguous save"):
        add_compound_creature_sources(config, "doe_service_001", *values)
    root = repository.asset_directory("doe_service_001")
    assert (root / "source" / "compound_roots_001").is_dir()


@pytest.mark.parametrize("failure", ["post_replace", "partial_event", "lock_exit"])
def test_source_intake_committed_save_ambiguity_preserves_and_reconciles(
    config, prompt, tmp_path, monkeypatch, failure
):
    values, repository = _candidate(config, prompt, tmp_path)
    if failure == "post_replace":
        original = manifest_storage.os.replace

        def replace_then_fail(source, destination):
            original(source, destination)
            if Path(destination).name == "manifest.json":
                raise OSError("post replace")

        monkeypatch.setattr(manifest_storage.os, "replace", replace_then_fail)
    elif failure == "partial_event":
        def partial(path, value):
            with path.open("ab") as stream:
                stream.write(value[: len(value) // 2])
            raise OSError("partial event")

        monkeypatch.setattr(manifest_storage, "append_event_bytes", partial)
    else:
        original_exit = AssetLock.__exit__

        def exit_then_fail(self, *args):
            original_exit(self, *args)
            raise OSError("lock exit")

        monkeypatch.setattr(AssetLock, "__exit__", exit_then_fail)

    artifacts = add_compound_creature_sources(config, "doe_service_001", *values)
    live = repository.load("doe_service_001")
    assert all(any(item.artifact_id == expected.artifact_id for item in live.artifacts) for expected in artifacts)
    assert (repository.asset_directory("doe_service_001") / "source" / "compound_roots_001").is_dir()


def _bind(config, prompt, tmp_path):
    values, repository = _candidate(config, prompt, tmp_path)
    roots = add_compound_creature_sources(config, "doe_service_001", *values)
    declaration = tmp_path / "declaration.txt"
    declaration.write_text("user-directed exact local use", encoding="utf-8")
    meshy = [item.artifact_id for item in roots if item.artifact_id != "compound_rig_donor_root_001"]
    donor = ["compound_rig_donor_root_001"]
    return repository, declaration, meshy, donor


def test_local_use_custody_direct_and_retry_are_exact(config, prompt, tmp_path):
    repository, declaration, meshy, donor = _bind(config, prompt, tmp_path)
    first = bind_user_local_use_custody(config, "doe_service_001", declaration, meshy, donor)
    second = bind_user_local_use_custody(config, "doe_service_001", declaration, meshy, donor)
    assert second.model_dump() == first.model_dump()
    assert repository.load("doe_service_001").custody == first


@pytest.mark.parametrize("mutation", ["missing", "corrupt"])
def test_local_use_retry_rehashes_manifest_owned_evidence(
    config, prompt, tmp_path, mutation
):
    repository, declaration, meshy, donor = _bind(config, prompt, tmp_path)
    bind_user_local_use_custody(config, "doe_service_001", declaration, meshy, donor)
    manifest = repository.load("doe_service_001")
    artifact = next(item for item in manifest.artifacts if item.role == "custody_license_evidence")
    evidence_path = repository.asset_directory("doe_service_001") / artifact.path
    if mutation == "missing":
        evidence_path.unlink()
    else:
        evidence_path.write_bytes(b"corrupt")

    with pytest.raises(FoundryError, match="Manifest-owned user local-use evidence"):
        bind_user_local_use_custody(config, "doe_service_001", declaration, meshy, donor)


def test_local_use_retry_rejects_swapped_contribution_partition(config, prompt, tmp_path):
    _, declaration, meshy, donor = _bind(config, prompt, tmp_path)
    bind_user_local_use_custody(config, "doe_service_001", declaration, meshy, donor)

    with pytest.raises(FoundryError, match="does not match retry inputs"):
        bind_user_local_use_custody(
            config,
            "doe_service_001",
            declaration,
            [*meshy[:-1], donor[0]],
            [meshy[-1]],
        )


@pytest.mark.parametrize("failure", ["post_replace", "partial_event", "lock_exit"])
def test_local_use_committed_save_ambiguity_preserves_and_reconciles(
    config, prompt, tmp_path, monkeypatch, failure
):
    repository, declaration, meshy, donor = _bind(config, prompt, tmp_path)
    if failure == "post_replace":
        original = manifest_storage.os.replace

        def replace_then_fail(source, destination):
            original(source, destination)
            if Path(destination).name == "manifest.json":
                raise OSError("post replace")

        monkeypatch.setattr(manifest_storage.os, "replace", replace_then_fail)
    elif failure == "partial_event":
        def partial(path, value):
            with path.open("ab") as stream:
                stream.write(value[: len(value) // 2])
            raise OSError("partial event")

        monkeypatch.setattr(manifest_storage, "append_event_bytes", partial)
    else:
        original_exit = AssetLock.__exit__

        def exit_then_fail(self, *args):
            original_exit(self, *args)
            raise OSError("lock exit")

        monkeypatch.setattr(AssetLock, "__exit__", exit_then_fail)

    assertion = bind_user_local_use_custody(
        config, "doe_service_001", declaration, meshy, donor
    )
    live = repository.load("doe_service_001")
    assert live.custody == assertion
    assert any(item.role == "custody_license_evidence" for item in live.artifacts)


def test_local_use_precommit_failure_rolls_back(config, prompt, tmp_path, monkeypatch):
    repository, declaration, meshy, donor = _bind(config, prompt, tmp_path)
    original = ManifestRepository.save

    def fail_custody(self, manifest, event_type="manifest.updated", expected_revision=None):
        if event_type == "custody.user_local_use_bound":
            raise OSError("precommit")
        return original(self, manifest, event_type, expected_revision)

    monkeypatch.setattr(ManifestRepository, "save", fail_custody)
    with pytest.raises(OSError, match="precommit"):
        bind_user_local_use_custody(config, "doe_service_001", declaration, meshy, donor)
    root = repository.asset_directory("doe_service_001")
    assert not list((root / "custody" / "evidence").glob("user-local-use-*.txt"))


def test_local_use_ambiguous_live_state_preserves_evidence(
    config, prompt, tmp_path, monkeypatch
):
    repository, declaration, meshy, donor = _bind(config, prompt, tmp_path)
    original_load = ManifestRepository.load
    calls = 0

    def fail_save(*args, **kwargs):
        raise OSError("ambiguous save")

    def ambiguous_load(self, asset_id):
        nonlocal calls
        live = original_load(self, asset_id)
        calls += 1
        if calls > 1:
            live.revision += 99
        return live

    monkeypatch.setattr(ManifestRepository, "save", fail_save)
    monkeypatch.setattr(ManifestRepository, "load", ambiguous_load)
    with pytest.raises(OSError, match="ambiguous save"):
        bind_user_local_use_custody(config, "doe_service_001", declaration, meshy, donor)
    root = repository.asset_directory("doe_service_001")
    assert list((root / "custody" / "evidence").glob("user-local-use-*.txt"))


def _playback_candidate(config, prompt, tmp_path, processor: str):
    create_asset(config, _lanes(), "doe_service_001", "creature", "Doe", prompt)
    root = config.foundry.workspace_root / "assets" / "doe_service_001"
    model_path = root / "processed" / "model.glb"
    model_path.parent.mkdir(exist_ok=True)
    model_path.write_bytes(b"model")
    executable = tmp_path / "blender.exe"
    executable.write_bytes(b"exe")
    config.tools.blender_executable = executable
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load("doe_service_001")
    manifest.artifacts.append(
        Artifact(
            artifact_id="processed_model_001",
            role="processed_model",
            stage="processed",
            format="glb",
            path="processed/model.glb",
            sha256=hashlib.sha256(b"model").hexdigest(),
            size_bytes=5,
            processor=Processor(name=processor, version="1"),
        )
    )
    manifest.workflow.state = WorkflowState.PROCESSED
    manifest.revision += 1
    repository.save(manifest, "test.processed", expected_revision=manifest.revision - 1)
    return repository


def test_playback_rejects_noncompound_creature_model(config, prompt, tmp_path):
    _playback_candidate(config, prompt, tmp_path, "blender_cleanup")
    with pytest.raises(FoundryError, match="compound-creature derivation"):
        render_creature_playback(config, "doe_service_001", lambda *args: None)


def test_playback_direct_service_records_complete_evidence(config, prompt, tmp_path):
    repository = _playback_candidate(
        config, prompt, tmp_path, "blender_compound_creature_derivation"
    )
    result = render_creature_playback(config, "doe_service_001", _playback_runner)
    live = repository.load("doe_service_001")
    assert result.role == "creature_playback_report"
    assert len([item for item in live.artifacts if item.role == "creature_playback_video"]) == 8
    assert any(item.get("name") == "creature_continuous_playback" for item in live.validation.checks)


@pytest.mark.parametrize("failure", ["post_replace", "partial_event", "lock_exit"])
def test_playback_committed_save_ambiguity_preserves_and_reconciles(
    config, prompt, tmp_path, monkeypatch, failure
):
    repository = _playback_candidate(
        config, prompt, tmp_path, "blender_compound_creature_derivation"
    )
    if failure == "post_replace":
        original = manifest_storage.os.replace

        def replace_then_fail(source, destination):
            original(source, destination)
            if Path(destination).name == "manifest.json":
                raise OSError("post replace")

        monkeypatch.setattr(manifest_storage.os, "replace", replace_then_fail)
    elif failure == "partial_event":
        def partial(path, value):
            with path.open("ab") as stream:
                stream.write(value[: len(value) // 2])
            raise OSError("partial event")

        monkeypatch.setattr(manifest_storage, "append_event_bytes", partial)
    else:
        original_exit = AssetLock.__exit__

        def exit_then_fail(self, *args):
            original_exit(self, *args)
            raise OSError("lock exit")

        monkeypatch.setattr(AssetLock, "__exit__", exit_then_fail)

    report = render_creature_playback(config, "doe_service_001", _playback_runner)
    live = repository.load("doe_service_001")
    assert any(item.artifact_id == report.artifact_id for item in live.artifacts)
    assert (repository.asset_directory("doe_service_001") / report.path).is_file()


def test_playback_precommit_failure_rolls_back_outputs(config, prompt, tmp_path, monkeypatch):
    repository = _playback_candidate(
        config, prompt, tmp_path, "blender_compound_creature_derivation"
    )
    original = ManifestRepository.save

    def fail_playback(self, manifest, event_type="manifest.updated", expected_revision=None):
        if event_type == "creature.playback_rendered":
            raise OSError("precommit")
        return original(self, manifest, event_type, expected_revision)

    monkeypatch.setattr(ManifestRepository, "save", fail_playback)
    with pytest.raises(OSError, match="precommit"):
        render_creature_playback(config, "doe_service_001", _playback_runner)
    root = repository.asset_directory("doe_service_001")
    assert not (root / "preview" / "creature-playback-001").exists()
    assert not (root / "reports" / "creature-playback-001.json").exists()


def _playback_runner(arguments, *args):
    separator = arguments.index("--")
    directory = Path(arguments[separator + 2])
    report = Path(arguments[separator + 3])
    clips = []
    for family in ["idle", "eating", "walk", "gallop", "jump", "hit", "attack", "death"]:
        frame_dir = directory / family
        frame_dir.mkdir(parents=True)
        frames = []
        for index in range(2):
            frame = frame_dir / f"{index}.png"
            Image.new("RGB", (2, 2), "gray").save(frame)
            frames.append(str(frame.relative_to(directory)).replace("\\", "/"))
        clips.append(
            {
                "name": family,
                "family": family,
                "video": f"{family}.webp",
                "frame_files": frames,
                "frame_duration_ms": 33,
            }
        )
    report.write_text(
        json.dumps({"schema": "vandrel_foundry_creature_playback/1.0", "clips": clips}),
        encoding="utf-8",
    )
    return ProcessResult(0, "", "", False, False, 0.1)
