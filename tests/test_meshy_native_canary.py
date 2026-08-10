import hashlib
import json
import struct
import zipfile
from pathlib import Path

import pytest
from PIL import Image

import vandrel_foundry.services.add_meshy_native_animation_package as intake_service
import vandrel_foundry.storage.manifests as manifest_storage
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.lanes import LaneConfiguration
from vandrel_foundry.domain.manifest import Artifact
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.add_meshy_native_animation_package import (
    ARCHIVE_ID,
    FBX_ID,
    add_meshy_native_animation_package,
)
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.normalize_meshy_native_animations import (
    normalize_meshy_native_animations,
)
from vandrel_foundry.services.render_meshy_native_playback import (
    render_meshy_native_playback,
)
from vandrel_foundry.services.supersede_meshy_native_intake_provenance import (
    supersede_meshy_native_intake_provenance,
)
from vandrel_foundry.services.validate_godot import ProcessResult
from vandrel_foundry.storage.locks import AssetLock
from vandrel_foundry.storage.manifests import ManifestRepository

ACTIONS = [
    "target_character|019fe8c8-1952-7ce9-a611-33851c9cf0b2",
    "target_character|019fe8ca-a6c4-7968-822f-92efebbab5a4",
    "target_character|019fe8d4-0feb-798a-bcbb-81126f26e17f",
    "target_character|019fe8d7-ed16-7b82-a594-728d821ee711",
    "target_character|Female_Crouch_Pick_Fruit_Basket_Stand",
    "target_character|Female_Stand_Pick_Fruit_Basket",
    "target_character|Female_Walk_Pick_Put_In_Pocket",
    "target_character|Red_Carpet_Walk",
    "target_character|Running",
    "target_character|Walking",
]


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


def _candidate(config, prompt: Path, archive: Path) -> tuple[Path, ManifestRepository]:
    config.tools.blender_executable = prompt
    create_asset(config, _lanes(), "meshy_native_test_001", "humanoid", "Native", prompt)
    archive_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
    fbx_hash = hashlib.sha256(b"fbx-source").hexdigest()
    add_meshy_native_animation_package(
        config,
        "meshy_native_test_001",
        archive,
        archive_hash,
        fbx_hash,
    )
    return (
        config.foundry.workspace_root / "assets" / "meshy_native_test_001",
        ManifestRepository(config.foundry.workspace_root),
    )


@pytest.fixture
def native_archive(tmp_path: Path) -> Path:
    path = tmp_path / "native.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Meshy_AI_biped/merged.fbx", b"fbx-source")
    return path


def _write_glb(path: Path, names: list[str], *, normalized: bool = True) -> None:
    document = {
        "asset": {"version": "2.0"},
        "accessors": [{"count": 6}],
        "meshes": [{"primitives": [{"indices": 0, "material": 0}]}],
        "materials": [{}],
        "nodes": [
            {
                "name": "target_character" if index == 0 else f"joint_{index}",
                **(
                    {"rotation": [2**-0.5, 0.0, 0.0, 2**-0.5]}
                    if index == 0 and normalized
                    else {}
                ),
            }
            for index in range(24)
        ],
        "skins": [{"name": "target_character", "joints": list(range(24))}],
        "animations": [{"name": name} for name in names],
    }
    payload = json.dumps(document, separators=(",", ":")).encode()
    payload += b" " * (-len(payload) % 4)
    path.write_bytes(
        struct.pack("<4sII", b"glTF", 2, 20 + len(payload))
        + struct.pack("<II", len(payload), 0x4E4F534A)
        + payload
    )


def _normalization_runner(arguments, *unused):
    separator = arguments.index("--")
    combined = Path(arguments[separator + 2])
    split = Path(arguments[separator + 3])
    report = Path(arguments[separator + 4])
    split.mkdir()
    _write_glb(combined, ACTIONS)
    outputs = []
    clips = []
    for index, name in enumerate(ACTIONS, start=1):
        filename = f"{index:02d}-clip.glb"
        _write_glb(split / filename, [name])
        outputs.append({"name": name, "file": filename})
        uuid = "|019" in name
        if name.endswith("|Running"):
            assessment = "locomotion_running"
        elif name.endswith("|Walking"):
            assessment = "locomotion_walking"
        elif "Pick_" in name:
            assessment = "foraging_not_eating"
        elif uuid:
            assessment = "unresolved"
        else:
            assessment = "not_butchery"
        clips.append(
            {
                "exact_name": name,
                "frame_range": [1, 30],
                "duration_seconds": 29 / 30,
                "root_baseline": [0.0, 1.0, 0.0],
                "root_displacement": 0.0,
                "sampled_ground_minimum_range": [0.0, 0.01],
                "maximum_sampled_vertex_displacement": 0.5,
                "endpoint_loop_match": name.endswith(("|Running", "|Walking")),
                "endpoint_matrix_max_delta": 0.0,
                "semantic_status": "unresolved_uuid" if uuid else "provider_named",
                "semantic_assessment": assessment,
            }
        )
    report.write_text(
        json.dumps(
            {
                "schema": "vandrel_foundry_meshy_native_blender_adapter/1.0",
                "tool_version": "Blender-test",
                "transformation_facts": {
                    "source_armatures_retained": 1,
                    "source_joint_count": 24,
                    "source_mesh_count": 1,
                    "source_material_count": 1,
                    "source_action_count": 10,
                    "output_action_count": 10,
                    "unweighted_exported_vertex_count": 0,
                    "bind_signature_before": "a" * 64,
                    "bind_signature_after": "a" * 64,
                    "bind_preserved": True,
                    "global_normalization": "world_positive_90_degrees_x_y_up_to_z_up",
                    "normalization_root_strategy": "parent_space_exported_on_armature_root",
                    "rest_axis_policy": "preserve_native_bone_rest_matrices",
                    "root_motion_policy": (
                        "subtract_per_clip_hips_frame_start_and_raise_clip_minimum_ground_to_z_zero"
                    ),
                    "semantic_policy": "retain_exact_action_names_and_unresolved_uuids",
                    "unresolved_uuid_action_count": 4,
                },
                "clips": clips,
                "split_outputs": outputs,
            }
        ),
        encoding="utf-8",
    )
    return ProcessResult(0, "ok C:\\machine\\blender-helper.dll", "", False, False, 0.1)


def _playback_runner(arguments, *unused):
    separator = arguments.index("--")
    output = Path(arguments[separator + 2])
    report = Path(arguments[separator + 3])
    expected = json.loads(Path(arguments[separator + 4]).read_text(encoding="utf-8"))
    output.mkdir()
    clips = []
    for index, name in enumerate(ACTIONS):
        directory = output / f"clip-{index:02d}"
        directory.mkdir()
        frames = []
        for frame in range(2):
            path = directory / f"{frame:04d}.png"
            Image.new("RGB", (4, 4), (index, frame, 0)).save(path)
            frames.append(f"{directory.name}/{path.name}")
        clips.append(
            {
                "exact_name": name,
                "frame_range": [1, 30],
                "frame_step": 1,
                "sampled_frame_count": 2,
                "frame_files": frames,
                "source_timebase_fps": 30,
                "source_duration_seconds": expected[name],
                "bound_normalization_duration_seconds": expected[name],
                "duration_delta_seconds": 0.0,
                "bounds_min": [0, 0, 0],
                "bounds_max": [1, 1, 2],
                "sampled_ground_minimum_range": [0, 0.01],
            }
        )
    report.write_text(
        json.dumps(
            {
                "schema": "vandrel_foundry_meshy_native_playback/1.0",
                "blender_version": "Blender-test",
                "neutral_gray": True,
                "lateral_camera": True,
                "continuous_temporal_output": True,
                "clip_count": 10,
                "clips": clips,
                "review_scope": ["all_exact_actions"],
            }
        ),
        encoding="utf-8",
    )
    return ProcessResult(0, "ok C:\\machine\\blender-helper.dll", "", False, False, 0.1)


def test_exact_archive_and_fbx_are_distinct_immutable_roots(config, prompt, native_archive):
    root, repository = _candidate(config, prompt, native_archive)
    manifest = repository.load("meshy_native_test_001")
    assert manifest.workflow.state is WorkflowState.DOWNLOADED
    roots = [item for item in manifest.artifacts if not item.derived_from]
    assert {item.artifact_id for item in roots} == {ARCHIVE_ID, FBX_ID}
    assert (root / "source/meshy_native_package_001/source.zip").read_bytes() == native_archive.read_bytes()
    assert (root / "source/meshy_native_package_001/merged_animations.fbx").read_bytes() == b"fbx-source"
    intake = json.loads(
        (root / "source/meshy_native_package_001/intake-report.json").read_text()
    )
    assert intake["authority_basis"] == "user_selected_local_source"
    assert intake["provider_task_metadata"] == "not_inspected"
    assert intake["license_metadata"] == "not_inspected"
    assert intake["external_provider_lookup"] == "not_performed_by_intake_service"


def test_archive_traversal_and_hash_mismatch_fail_before_candidate_mutation(
    config, prompt, tmp_path
):
    create_asset(config, _lanes(), "meshy_native_test_001", "humanoid", "Native", prompt)
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as value:
        value.writestr("../escape.fbx", b"fbx-source")
    manifest_path = config.foundry.workspace_root / "assets/meshy_native_test_001/manifest.json"
    before = manifest_path.read_bytes()
    with pytest.raises(FoundryError, match="unsafe"):
        add_meshy_native_animation_package(
            config,
            "meshy_native_test_001",
            archive,
            hashlib.sha256(archive.read_bytes()).hexdigest(),
            hashlib.sha256(b"fbx-source").hexdigest(),
        )
    assert manifest_path.read_bytes() == before
    with pytest.raises(FoundryError, match="hash"):
        add_meshy_native_animation_package(
            config,
            "meshy_native_test_001",
            archive,
            "0" * 64,
            hashlib.sha256(b"fbx-source").hexdigest(),
        )


def test_intake_detects_source_mutation_between_initial_hash_and_copy(
    config, prompt, native_archive, monkeypatch
):
    create_asset(config, _lanes(), "meshy_native_test_001", "humanoid", "Native", prompt)
    original_hash = hashlib.sha256(native_archive.read_bytes()).hexdigest()
    original_copy = intake_service._copy_new

    def mutate_then_copy(source: Path, destination: Path) -> None:
        source.write_bytes(b"changed-after-initial-hash")
        original_copy(source, destination)

    monkeypatch.setattr(intake_service, "_copy_new", mutate_then_copy)
    with pytest.raises(FoundryError, match="changed while it was copied"):
        add_meshy_native_animation_package(
            config,
            "meshy_native_test_001",
            native_archive,
            original_hash,
            hashlib.sha256(b"fbx-source").hexdigest(),
        )
    root = config.foundry.workspace_root / "assets/meshy_native_test_001"
    assert not (root / "source/meshy_native_package_001").exists()


def test_retry_rehashes_manifest_owned_roots(config, prompt, native_archive):
    root, _ = _candidate(config, prompt, native_archive)
    (root / "source/meshy_native_package_001/merged_animations.fbx").write_bytes(b"changed")
    with pytest.raises(FoundryError, match="missing or changed"):
        add_meshy_native_animation_package(
            config,
            "meshy_native_test_001",
            native_archive,
            hashlib.sha256(native_archive.read_bytes()).hexdigest(),
            hashlib.sha256(b"fbx-source").hexdigest(),
        )


def test_intake_provenance_correction_is_new_and_does_not_rewrite_intake(
    config, prompt, native_archive
):
    root, repository = _candidate(config, prompt, native_archive)
    normalize_meshy_native_animations(config, "meshy_native_test_001", _normalization_runner)
    original = root / "source/meshy_native_package_001/intake-report.json"
    original_bytes = original.read_bytes()
    artifact = supersede_meshy_native_intake_provenance(config, "meshy_native_test_001")
    corrected = json.loads((root / artifact.path).read_text())
    assert corrected["license_metadata"] == "not_inspected"
    assert corrected["supersedes_artifact_id"] == "meshy_native_source_intake_report_001"
    assert original.read_bytes() == original_bytes
    assert repository.load("meshy_native_test_001").workflow.state is WorkflowState.PROCESSED


def test_normalization_binds_exact_roots_splits_all_actions_and_keeps_unreleased(
    config, prompt, native_archive
):
    root, repository = _candidate(config, prompt, native_archive)
    result = normalize_meshy_native_animations(
        config, "meshy_native_test_001", _normalization_runner
    )
    assert len(result.clips) == 10
    assert set(result.model.derived_from) == {ARCHIVE_ID, FBX_ID}
    report = json.loads((root / result.report.path).read_text())
    assert [item["exact_name"] for item in report["clips"]] == ACTIONS
    assert report["transformation_facts"]["bind_preserved"] is True
    assert report["transformation_facts"]["unresolved_uuid_action_count"] == 4
    assert all("C:\\" not in item and ".meshy-native-" not in item for item in report["arguments"])
    assert report["process"]["return_code"] == 0
    assert report["process"]["timed_out"] is False
    process_log = root / report["process_log"]["path"]
    process = json.loads(process_log.read_text())
    assert process["stdout"] == "ok <local-path>"
    assert process["logical_arguments"] == report["arguments"]
    manifest = repository.load("meshy_native_test_001")
    assert any(
        item.role == "meshy_native_normalization_process_log" for item in manifest.artifacts
    )
    assert manifest.workflow.state is WorkflowState.PROCESSED
    assert not manifest.approval.approved and not manifest.release.released


def test_normalization_rejects_extra_root_and_toctou_mutation(config, prompt, native_archive):
    root, repository = _candidate(config, prompt, native_archive)
    manifest = repository.load("meshy_native_test_001")
    extra_path = root / "source/extra.bin"
    extra_path.write_bytes(b"extra")
    manifest.artifacts.append(
        Artifact(
            artifact_id="extra_root",
            role="source",
            stage="source",
            format="bin",
            path="source/extra.bin",
            sha256=hashlib.sha256(b"extra").hexdigest(),
            size_bytes=5,
        )
    )
    manifest.revision += 1
    repository.save(manifest, expected_revision=manifest.revision - 1)
    with pytest.raises(FoundryError, match="exact archive and FBX"):
        normalize_meshy_native_animations(config, "meshy_native_test_001", _normalization_runner)

    manifest = repository.load("meshy_native_test_001")
    manifest.artifacts.pop()
    manifest.revision += 1
    repository.save(manifest, expected_revision=manifest.revision - 1)

    def mutate(arguments, *values):
        result = _normalization_runner(arguments, *values)
        (root / "source/meshy_native_package_001/merged_animations.fbx").write_bytes(b"changed")
        return result

    with pytest.raises(FoundryError, match="source changed"):
        normalize_meshy_native_animations(config, "meshy_native_test_001", mutate)
    assert not list((root / "processed/meshy_native").rglob("*.glb"))


def test_normalization_rejects_export_that_loses_axis_root(config, prompt, native_archive):
    root, _ = _candidate(config, prompt, native_archive)

    def lose_axis(arguments, *values):
        result = _normalization_runner(arguments, *values)
        separator = arguments.index("--")
        _write_glb(Path(arguments[separator + 2]), ACTIONS, normalized=False)
        return result

    with pytest.raises(FoundryError, match="axis root"):
        normalize_meshy_native_animations(config, "meshy_native_test_001", lose_axis)
    assert not list((root / "processed/meshy_native").rglob("*.glb"))


def test_playback_binds_all_exact_actions_without_visual_acceptance(
    config, prompt, native_archive
):
    root, repository = _candidate(config, prompt, native_archive)
    normalize_meshy_native_animations(config, "meshy_native_test_001", _normalization_runner)
    artifact = render_meshy_native_playback(
        config, "meshy_native_test_001", _playback_runner
    )
    report = json.loads((root / artifact.path).read_text())
    assert report["clip_count"] == 10
    assert report["visual_acceptance"] is False
    assert "No provider-resolved eating" in report["semantic_decision"]["eating"]
    assert "No provider-resolved kneeling" in report["semantic_decision"]["butchery"]
    assert "frame_files" not in json.dumps(report)
    checked = {
        "target_character|Running",
        "target_character|Walking",
        "target_character|019fe8ca-a6c4-7968-822f-92efebbab5a4",
    }
    for clip in report["clips"]:
        if clip["exact_name"] in checked:
            assert abs(
                clip["encoded_playback_duration_seconds"]
                - clip["bound_normalization_duration_seconds"]
            ) <= 0.002
        evidence = clip["evidence_file"]
        assert (root / evidence["path"]).is_file()
    assert report["process"]["return_code"] == 0
    playback_process_path = root / report["process_log"]["path"]
    assert playback_process_path.is_file()
    assert "C:\\" not in playback_process_path.read_text()
    manifest = repository.load("meshy_native_test_001")
    videos = [item for item in manifest.artifacts if item.role == "meshy_native_playback_video"]
    assert len(videos) == 10
    assert any(item.role == "meshy_native_playback_process_log" for item in manifest.artifacts)
    assert manifest.workflow.state is WorkflowState.PROCESSED
    assert not manifest.approval.approved and not manifest.release.released


def test_playback_rejects_duration_shortening_for_locomotion_and_uuid(
    config, prompt, native_archive
):
    root, _ = _candidate(config, prompt, native_archive)
    normalize_meshy_native_animations(config, "meshy_native_test_001", _normalization_runner)

    def shortened(arguments, *unused):
        result = _playback_runner(arguments, *unused)
        separator = arguments.index("--")
        report_path = Path(arguments[separator + 3])
        report = json.loads(report_path.read_text())
        affected = {
            "target_character|Running",
            "target_character|Walking",
            "target_character|019fe8ca-a6c4-7968-822f-92efebbab5a4",
        }
        for clip in report["clips"]:
            if clip["exact_name"] in affected:
                clip["source_duration_seconds"] *= 0.8
        report_path.write_text(json.dumps(report), encoding="utf-8")
        return result

    with pytest.raises(FoundryError, match="duration changed"):
        render_meshy_native_playback(config, "meshy_native_test_001", shortened)
    assert not (root / "preview/meshy-native-playback-001").exists()
    assert not (root / "reports/meshy-native-playback-001.json").exists()


def test_playback_rehashes_model_after_runner(config, prompt, native_archive):
    root, _ = _candidate(config, prompt, native_archive)
    normalized = normalize_meshy_native_animations(
        config, "meshy_native_test_001", _normalization_runner
    )

    def mutate_model(arguments, *unused):
        result = _playback_runner(arguments, *unused)
        (root / normalized.model.path).write_bytes(b"mutated-during-runner")
        return result

    with pytest.raises(FoundryError, match="playback input changed"):
        render_meshy_native_playback(config, "meshy_native_test_001", mutate_model)
    assert not (root / "preview/meshy-native-playback-001").exists()


def test_playback_partial_adapter_output_never_reaches_final_paths(
    config, prompt, native_archive
):
    root, _ = _candidate(config, prompt, native_archive)
    normalize_meshy_native_animations(config, "meshy_native_test_001", _normalization_runner)

    def partial(arguments, *unused):
        separator = arguments.index("--")
        output = Path(arguments[separator + 2])
        report = Path(arguments[separator + 3])
        output.mkdir()
        (output / "partial").mkdir()
        Image.new("RGB", (2, 2), "gray").save(output / "partial/0000.png")
        report.write_text(json.dumps({"schema": "partial"}), encoding="utf-8")
        return ProcessResult(0, "partial", "", False, False, 0.1)

    with pytest.raises(FoundryError, match="does not match all exact actions"):
        render_meshy_native_playback(config, "meshy_native_test_001", partial)
    assert not (root / "preview/meshy-native-playback-001").exists()
    assert not (root / "reports/meshy-native-playback-001.json").exists()


def test_playback_precommit_failure_rolls_back_promoted_outputs(
    config, prompt, native_archive, monkeypatch
):
    root, _ = _candidate(config, prompt, native_archive)
    normalize_meshy_native_animations(config, "meshy_native_test_001", _normalization_runner)
    original = ManifestRepository.save

    def fail_playback(self, manifest, event_type="manifest.updated", expected_revision=None):
        if event_type == "preview.meshy_native_playback_rendered":
            raise OSError("precommit")
        return original(self, manifest, event_type, expected_revision)

    monkeypatch.setattr(ManifestRepository, "save", fail_playback)
    with pytest.raises(OSError, match="precommit"):
        render_meshy_native_playback(config, "meshy_native_test_001", _playback_runner)
    assert not (root / "preview/meshy-native-playback-001").exists()
    assert not (root / "reports/meshy-native-playback-001.json").exists()
    assert not (root / "reports/meshy-native-playback-001.process.json").exists()


@pytest.mark.parametrize("failure", ["post_replace", "partial_event", "lock_exit"])
def test_playback_committed_save_ambiguity_preserves_exact_outputs(
    config, prompt, native_archive, monkeypatch, failure
):
    root, repository = _candidate(config, prompt, native_archive)
    normalize_meshy_native_animations(config, "meshy_native_test_001", _normalization_runner)
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

    report = render_meshy_native_playback(
        config, "meshy_native_test_001", _playback_runner
    )
    live = repository.load("meshy_native_test_001")
    assert any(item.artifact_id == report.artifact_id for item in live.artifacts)
    assert (root / report.path).is_file()
    assert (root / "preview/meshy-native-playback-001").is_dir()
