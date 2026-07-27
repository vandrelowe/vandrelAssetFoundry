import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, AssetManifest, Processor, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.validate_godot import (
    SAFE_ENVIRONMENT_KEYS,
    ProcessResult,
    ProcessRunner,
    run_bounded_process,
)
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path

PROCESSOR_NAME = "godot_provider_native_character"
PROCESSOR_VERSION = "1"

PROJECT_TEXT = """; Generated Foundry validation project. Not a Vandrel runtime project.
config_version=5

[application]
config/name="Vandrel Foundry Provider-Native Character Validation"
run/main_scene="res://extract_and_validate.tscn"

[rendering]
renderer/rendering_method="gl_compatibility"
"""

RUNTIME_PROJECT_TEXT = """; Generated Foundry candidate package. Not a Vandrel runtime project.
config_version=5

[application]
config/name="Vandrel Foundry Provider-Native Character Candidate"
run/main_scene="res://wrapper.tscn"

[rendering]
renderer/rendering_method="gl_compatibility"
"""

LOADER_TEXT = """extends AnimationPlayer

func _ready() -> void:
\tvar library := get_animation_library("")
\tfor animation_name in ["Walk", "Run"]:
\t\tvar animation: Animation = load("res://animations/%s.res" % animation_name.to_lower())
\t\tif animation != null and not library.has_animation(animation_name):
\t\t\tlibrary.add_animation(animation_name, animation)
\tvar aliases := {
\t\t"Crouch_Fwd": "Walk",
\t\t"Jog_Fwd": "Run",
\t\t"Sprint": "Run",
\t}
\tfor alias in aliases:
\t\tif library.has_animation(aliases[alias]) and not library.has_animation(alias):
\t\t\tlibrary.add_animation(alias, library.get_animation(aliases[alias]))
"""

WRAPPER_TEXT = """[gd_scene load_steps=3 format=3]

[ext_resource type="PackedScene" path="res://model.fbx" id="1"]
[ext_resource type="Script" path="res://animation_loader.gd" id="2"]

[node name="ProviderNativeCharacterCandidate" instance=ExtResource("1")]

[node name="AnimationPlayer" parent="." index="-1"]
script = ExtResource("2")
"""

EXTRACT_SCENE_TEXT = """[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://extract_and_validate.gd" id="1"]

[node name="ExtractAndValidate" type="Node"]
script = ExtResource("1")
"""

EXTRACT_SCRIPT_TEXT = """extends Node

const SOURCES := {
\t"Walk": "res://walking.fbx",
\t"Run": "res://running.fbx",
}

func _ready() -> void:
\tfor animation_name in SOURCES:
\t\tvar source: PackedScene = load(SOURCES[animation_name])
\t\tif source == null:
\t\t\t_finish({"passed": false, "error": "animation source failed to load"})
\t\t\treturn
\t\tvar instance := source.instantiate()
\t\tvar player := instance.find_child("AnimationPlayer", true, false) as AnimationPlayer
\t\tvar animation := _first_playable_animation(player)
\t\tif animation == null:
\t\t\tinstance.free()
\t\t\t_finish({"passed": false, "error": "playable animation missing"})
\t\t\treturn
\t\tvar portable := animation.duplicate(true) as Animation
\t\tportable.loop_mode = Animation.LOOP_LINEAR
\t\tvar save_result := ResourceSaver.save(
\t\t\tportable,
\t\t\t"res://animations/%s.res" % animation_name.to_lower()
\t\t)
\t\tinstance.free()
\t\tif save_result != OK:
\t\t\t_finish({"passed": false, "error": "animation resource save failed"})
\t\t\treturn

\tvar wrapper: PackedScene = load("res://wrapper.tscn")
\tif wrapper == null:
\t\t_finish({"passed": false, "error": "wrapper failed to load"})
\t\treturn
\tvar character := wrapper.instantiate()
\tadd_child(character)
\tawait get_tree().process_frame
\tvar player := character.find_child("AnimationPlayer", true, false) as AnimationPlayer
\tvar skeleton := character.find_child("Skeleton3D", true, false) as Skeleton3D
\tvar mesh_count := 0
\tvar triangle_count := 0
\tvar material_count := 0
\tvar textured_material_count := 0
\tfor node in character.find_children("*", "MeshInstance3D", true, false):
\t\tvar mesh_instance := node as MeshInstance3D
\t\tif mesh_instance.mesh == null:
\t\t\tcontinue
\t\tmesh_count += 1
\t\tfor surface_index in mesh_instance.mesh.get_surface_count():
\t\t\tvar arrays := mesh_instance.mesh.surface_get_arrays(surface_index)
\t\t\tvar indices: PackedInt32Array = arrays[Mesh.ARRAY_INDEX]
\t\t\tvar vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
\t\t\ttriangle_count += (indices.size() if not indices.is_empty() else vertices.size()) / 3
\t\t\tvar material := mesh_instance.get_active_material(surface_index)
\t\t\tif material != null:
\t\t\t\tmaterial_count += 1
\t\t\t\tif material is BaseMaterial3D and (material as BaseMaterial3D).albedo_texture != null:
\t\t\t\t\ttextured_material_count += 1
\tvar missing: Array[String] = []
\tfor animation_name in ["Walk", "Run", "Jog_Fwd", "Sprint"]:
\t\tif player == null or not player.has_animation(animation_name):
\t\t\tmissing.append(animation_name)
\tvar finite_bones := true
\tif skeleton != null:
\t\tfor bone_index in skeleton.get_bone_count():
\t\t\tvar scale := skeleton.get_bone_pose_scale(bone_index)
\t\t\tfinite_bones = finite_bones and is_finite(scale.x) and is_finite(scale.y) and is_finite(scale.z)
\tfor animation_name in ["Walk", "Run"]:
\t\tif player != null and player.has_animation(animation_name):
\t\t\tplayer.play(animation_name)
\t\t\tplayer.seek(player.current_animation_length * 0.5, true)
\t\t\tawait get_tree().process_frame
\tvar bone_count := skeleton.get_bone_count() if skeleton != null else 0
\t_finish({
\t\t"schema_version": 1,
\t\t"passed": player != null and bone_count >= 20 and mesh_count > 0
\t\t\tand triangle_count > 0 and material_count > 0 and textured_material_count > 0
\t\t\tand missing.is_empty() and finite_bones,
\t\t"bone_count": bone_count,
\t\t"mesh_count": mesh_count,
\t\t"triangle_count": triangle_count,
\t\t"material_count": material_count,
\t\t"textured_material_count": textured_material_count,
\t\t"missing_animations": missing,
\t\t"finite_bone_scales": finite_bones,
\t})

func _first_playable_animation(player: AnimationPlayer) -> Animation:
\tif player == null or not player.has_animation_library(""):
\t\treturn null
\tvar library := player.get_animation_library("")
\tfor animation_name in library.get_animation_list():
\t\tif animation_name != "RESET":
\t\t\treturn library.get_animation(animation_name)
\treturn null

func _finish(report: Dictionary) -> void:
\tvar file := FileAccess.open("res://native-character-report.json", FileAccess.WRITE)
\tif file != null:
\t\tfile.store_string(JSON.stringify(report, "\\t"))
\tget_tree().quit(0 if report.get("passed", false) else 1)
"""


@dataclass(frozen=True)
class NativeCharacterResult:
    model: Artifact
    walk: Artifact
    run: Artifact
    wrapper: Artifact
    loader: Artifact
    report: Artifact
    import_result: ProcessResult
    validation_result: ProcessResult


def prepare_provider_native_character(
    config: FoundryConfig,
    asset_id: str,
    runner: ProcessRunner | None = None,
    environment: Mapping[str, str] | None = None,
) -> NativeCharacterResult:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if _repair_native_artifact_id_collisions(manifest):
        manifest.revision += 1
        manifest.asset.updated_at = utc_now()
        repository.save(
            manifest,
            "asset.provider_native_artifact_ids_repaired",
            expected_revision=manifest.revision - 1,
        )
    if manifest.asset.lane != "humanoid":
        raise FoundryError("Provider-native character preparation requires the humanoid lane.")
    if manifest.workflow.state not in {
        WorkflowState.DOWNLOADED,
        WorkflowState.PROCESSED,
        WorkflowState.REVIEW,
        WorkflowState.BLOCKED,
        WorkflowState.REJECTED,
    }:
        raise FoundryError(
            f"Provider-native character preparation requires downloaded candidate state: {asset_id}"
        )
    executable = config.tools.godot_executable
    if executable is None or not executable.is_absolute() or not executable.is_file():
        raise FoundryError("Configure tools.godot_executable as an existing absolute file.")

    model, walk, run, selection_basis = _select_sources(manifest.artifacts)
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    for artifact in (model, walk, run):
        _verify_artifact(asset_root, artifact)

    number = sum(item.role == "provider_native_character_report" for item in manifest.artifacts) + 1
    directory_name = f"provider-native-{number:03d}-{model.sha256[:12]}"
    final_directory = asset_root / "processed" / directory_name
    final_directory.parent.mkdir(parents=True, exist_ok=True)
    if final_directory.exists():
        raise FoundryError(f"Provider-native output already exists: {directory_name}")
    sandbox = Path(tempfile.mkdtemp(prefix=f".{directory_name}-", dir=final_directory.parent))
    process_runner = runner or run_bounded_process
    safe_environment = {
        key: value
        for key, value in (environment or os.environ).items()
        if key.upper() in SAFE_ENVIRONMENT_KEYS
    }
    try:
        _copy_new(contained_path(asset_root, model.path), sandbox / "model.fbx")
        _copy_new(contained_path(asset_root, walk.path), sandbox / "walking.fbx")
        _copy_new(contained_path(asset_root, run.path), sandbox / "running.fbx")
        (sandbox / "animations").mkdir()
        _write_new_text(sandbox / "project.godot", PROJECT_TEXT)
        _write_new_text(sandbox / "animation_loader.gd", LOADER_TEXT)
        _write_new_text(sandbox / "wrapper.tscn", WRAPPER_TEXT)
        _write_new_text(sandbox / "extract_and_validate.gd", EXTRACT_SCRIPT_TEXT)
        _write_new_text(sandbox / "extract_and_validate.tscn", EXTRACT_SCENE_TEXT)

        import_result = process_runner(
            [
                str(executable),
                "--headless",
                "--path",
                str(sandbox),
                "--import",
                "--quit",
            ],
            sandbox,
            safe_environment,
            config.tools.godot_timeout_seconds,
            config.tools.maximum_output_bytes,
        )
        _require_success(import_result, "Godot provider-native import")
        validation_result = process_runner(
            [
                str(executable),
                "--headless",
                "--path",
                str(sandbox),
                "res://extract_and_validate.tscn",
            ],
            sandbox,
            safe_environment,
            config.tools.godot_timeout_seconds,
            config.tools.maximum_output_bytes,
        )
        _require_success(validation_result, "Godot provider-native playback")
        report_path = sandbox / "native-character-report.json"
        report_data = json.loads(report_path.read_text(encoding="utf-8"))
        if not report_data.get("passed"):
            raise FoundryError("Provider-native character validation report did not pass.")
        report_data.update(
            {
                "asset_id": asset_id,
                "processor": PROCESSOR_NAME,
                "processor_version": PROCESSOR_VERSION,
                "source_selection_basis": selection_basis,
                "source_artifacts": {
                    "model": {"artifact_id": model.artifact_id, "sha256": model.sha256},
                    "walk": {"artifact_id": walk.artifact_id, "sha256": walk.sha256},
                    "run": {"artifact_id": run.artifact_id, "sha256": run.sha256},
                },
                "authority": {
                    "result_is": "provider-native import and same-task playback evidence",
                    "result_is_not": "Vandrel runtime acceptance or shared animation-pool proof",
                },
            }
        )
        report_path.write_text(
            json.dumps(report_data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        for required in (
            "animations/walk.res",
            "animations/run.res",
            "wrapper.tscn",
            "model.fbx",
        ):
            if not (sandbox / required).is_file():
                raise FoundryError(f"Provider-native output is missing: {required}")
        (sandbox / "project.godot").write_text(
            RUNTIME_PROJECT_TEXT,
            encoding="utf-8",
            newline="\n",
        )
        _remove_transient_files(sandbox)
        os.rename(sandbox, final_directory)
    except BaseException:
        if sandbox.exists():
            shutil.rmtree(sandbox)
        raise

    relative_root = f"processed/{directory_name}"
    processor = Processor(name=PROCESSOR_NAME, version=PROCESSOR_VERSION)
    model_number = _next_artifact_number(manifest.artifacts, "processed_fbx")
    walk_number = _next_artifact_number(
        manifest.artifacts,
        "processed_animation_walk",
    )
    run_number = _next_artifact_number(
        manifest.artifacts,
        "processed_animation_run",
    )
    wrapper_number = _next_artifact_number(
        manifest.artifacts,
        "godot_wrapper_scene",
    )
    loader_number = _next_artifact_number(
        manifest.artifacts,
        "godot_animation_loader_script",
    )
    project_number = _next_artifact_number(
        manifest.artifacts,
        "godot_validation_project",
    )
    report_number = _next_artifact_number(
        manifest.artifacts,
        "provider_native_character_report",
    )
    model_artifact = _artifact(
        final_directory / "model.fbx",
        f"processed_fbx_{model_number:03d}",
        "processed_model",
        "fbx",
        RelativeManifestPath(f"{relative_root}/model.fbx"),
        [model.artifact_id],
        model.source_task_key,
        processor,
    )
    walk_artifact = _artifact(
        final_directory / "animations" / "walk.res",
        f"processed_animation_walk_{walk_number:03d}",
        "processed_animation_walk",
        "res",
        RelativeManifestPath(f"{relative_root}/animations/walk.res"),
        [walk.artifact_id, model.artifact_id],
        walk.source_task_key,
        processor,
    )
    run_artifact = _artifact(
        final_directory / "animations" / "run.res",
        f"processed_animation_run_{run_number:03d}",
        "processed_animation_run",
        "res",
        RelativeManifestPath(f"{relative_root}/animations/run.res"),
        [run.artifact_id, model.artifact_id],
        run.source_task_key,
        processor,
    )
    wrapper_artifact = _artifact(
        final_directory / "wrapper.tscn",
        f"godot_wrapper_scene_{wrapper_number:03d}",
        "godot_wrapper_scene",
        "tscn",
        RelativeManifestPath(f"{relative_root}/wrapper.tscn"),
        [model_artifact.artifact_id, walk_artifact.artifact_id, run_artifact.artifact_id],
        model.source_task_key,
        processor,
    )
    loader_artifact = _artifact(
        final_directory / "animation_loader.gd",
        f"godot_animation_loader_script_{loader_number:03d}",
        "godot_animation_loader_script",
        "gd",
        RelativeManifestPath(f"{relative_root}/animation_loader.gd"),
        [walk_artifact.artifact_id, run_artifact.artifact_id],
        model.source_task_key,
        processor,
    )
    project_artifact = _artifact(
        final_directory / "project.godot",
        f"godot_validation_project_{project_number:03d}",
        "godot_validation_project",
        "godot",
        RelativeManifestPath(f"{relative_root}/project.godot"),
        [wrapper_artifact.artifact_id],
        model.source_task_key,
        processor,
    )
    report_artifact = _artifact(
        final_directory / "native-character-report.json",
        f"provider_native_character_report_{report_number:03d}",
        "provider_native_character_report",
        "json",
        RelativeManifestPath(f"{relative_root}/native-character-report.json"),
        [model_artifact.artifact_id, walk_artifact.artifact_id, run_artifact.artifact_id],
        model.source_task_key,
        processor,
    )
    manifest.artifacts.extend(
        [
            model_artifact,
            walk_artifact,
            run_artifact,
            wrapper_artifact,
            loader_artifact,
            project_artifact,
            report_artifact,
        ]
    )
    triangle_budget = manifest.quality.targets.get("max_triangles")
    triangle_count = int(report_data["triangle_count"])
    checks = [
        {
            "name": "provider_native_character_playback",
            "passed": True,
            "report": str(report_artifact.path),
            "processed_model_sha256": model_artifact.sha256,
            "walk_sha256": walk_artifact.sha256,
            "run_sha256": run_artifact.sha256,
            "same_provider_task": (
                model.source_task_key == walk.source_task_key == run.source_task_key
            ),
        },
        {"name": "geometry_present", "passed": int(report_data["mesh_count"]) > 0},
        {
            "name": "triangle_budget",
            "passed": not isinstance(triangle_budget, int) or triangle_count <= triangle_budget,
            "observed": triangle_count,
            "target": triangle_budget,
        },
        {"name": "materials_required", "passed": int(report_data["textured_material_count"]) > 0},
        {"name": "skeleton_required", "passed": int(report_data["bone_count"]) >= 20},
        {"name": "godot_sandbox_import", "passed": True, "report": str(report_artifact.path)},
    ]
    manifest.validation.checks = checks
    manifest.validation.result = "passed" if all(check["passed"] for check in checks) else "failed"
    manifest.quality.observed.update(
        {
            "triangle_count": triangle_count,
            "mesh_count": int(report_data["mesh_count"]),
            "material_count": int(report_data["material_count"]),
            "bone_count": int(report_data["bone_count"]),
            "animation_source": "meshy_same_rigging_task",
            "recommended_fbx_embedded_texture_handling": "embed_basis_universal",
        }
    )
    manifest.approval.approved = False
    manifest.approval.approved_at = None
    manifest.approval.approved_artifact_hashes = {}
    manifest.workflow.state = (
        WorkflowState.REVIEW if manifest.validation.result == "passed" else WorkflowState.BLOCKED
    )
    manifest.workflow.blocked_reason = (
        None
        if manifest.validation.result == "passed"
        else "Provider-native character validation failed a lane check."
    )
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    repository.save(
        manifest,
        "asset.provider_native_character_prepared",
        expected_revision=manifest.revision - 1,
    )
    return NativeCharacterResult(
        model=model_artifact,
        walk=walk_artifact,
        run=run_artifact,
        wrapper=wrapper_artifact,
        loader=loader_artifact,
        report=report_artifact,
        import_result=import_result,
        validation_result=validation_result,
    )


def _select_sources(
    artifacts: list[Artifact],
) -> tuple[Artifact, Artifact, Artifact, str]:
    models = [
        item
        for item in artifacts
        if item.role == "source_model" and item.format == "fbx" and item.source_task_key
    ]
    if not models:
        raise FoundryError("Provider-native character preparation requires a rigged FBX.")
    model = models[-1]
    walk = [
        item
        for item in artifacts
        if item.role == "source_animation_walk"
        and item.format == "fbx"
        and item.source_task_key == model.source_task_key
    ]
    run = [
        item
        for item in artifacts
        if item.role == "source_animation_run"
        and item.format == "fbx"
        and item.source_task_key == model.source_task_key
    ]
    if walk and run:
        return model, walk[-1], run[-1], "semantic_artifact_roles"
    legacy = [
        item
        for item in artifacts
        if item.role == "source_animation_model"
        and item.format == "fbx"
        and item.source_task_key == model.source_task_key
    ]
    if len(legacy) == 2:
        return model, legacy[0], legacy[1], "legacy_downloader_walk_then_run_order"
    raise FoundryError(
        "Provider-native character preparation requires same-task walking and running FBX outputs."
    )


def _repair_native_artifact_id_collisions(manifest: AssetManifest) -> bool:
    seen: set[str] = set()
    active_native_renames: dict[str, str] = {}
    changed = False
    for artifact in manifest.artifacts:
        is_native = (
            artifact.processor is not None
            and artifact.processor.name == PROCESSOR_NAME
        )
        if is_native:
            artifact.derived_from = [
                active_native_renames.get(source_id, source_id)
                for source_id in artifact.derived_from
            ]
        old_id = artifact.artifact_id
        if old_id not in seen:
            seen.add(old_id)
            continue
        if not is_native:
            raise FoundryError(f"Duplicate non-native artifact ID requires manual repair: {old_id}")
        suffix = 1
        while True:
            candidate = f"{old_id}_native_{suffix:03d}"
            if candidate not in seen:
                break
            suffix += 1
        artifact.artifact_id = candidate
        active_native_renames[old_id] = candidate
        seen.add(candidate)
        changed = True
    return changed


def _next_artifact_number(artifacts: list[Artifact], prefix: str) -> int:
    numbers: list[int] = []
    marker = f"{prefix}_"
    for artifact in artifacts:
        if not artifact.artifact_id.startswith(marker):
            continue
        suffix = artifact.artifact_id[len(marker) :]
        if len(suffix) == 3 and suffix.isdigit():
            numbers.append(int(suffix))
    return max(numbers, default=0) + 1


def _require_success(result: ProcessResult, label: str) -> None:
    if result.return_code != 0 or result.timed_out or result.output_limited:
        raise FoundryError(f"{label} failed.")


def _remove_transient_files(sandbox: Path) -> None:
    for name in (
        ".godot",
        "walking.fbx",
        "walking.fbx.import",
        "running.fbx",
        "running.fbx.import",
        "extract_and_validate.gd",
        "extract_and_validate.gd.uid",
        "extract_and_validate.tscn",
        "animation_loader.gd.uid",
    ):
        path = sandbox / name
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    for extracted in sandbox.glob("*_0.png*"):
        extracted.unlink()
    character_import = sandbox / "model.fbx.import"
    if character_import.exists():
        character_import.unlink()


def _artifact(
    path: Path,
    artifact_id: str,
    role: str,
    file_format: str,
    relative: RelativeManifestPath,
    derived_from: list[str],
    source_task_key: str | None,
    processor: Processor,
) -> Artifact:
    digest, size = _hash_file(path)
    return Artifact(
        artifact_id=artifact_id,
        role=role,
        stage="processed",
        format=file_format,
        path=relative,
        sha256=digest,
        size_bytes=size,
        derived_from=derived_from,
        source_task_key=source_task_key,
        processor=processor,
    )


def _verify_artifact(asset_root: Path, artifact: Artifact) -> None:
    digest, size = _hash_file(contained_path(asset_root, artifact.path))
    if digest != artifact.sha256 or size != artifact.size_bytes:
        raise FoundryError(f"Provider-native input changed: {artifact.artifact_id}")


def _copy_new(source: Path, destination: Path) -> None:
    try:
        with source.open("rb") as input_stream, destination.open("xb") as output_stream:
            while chunk := input_stream.read(1024 * 1024):
                output_stream.write(chunk)
            output_stream.flush()
            os.fsync(output_stream.fileno())
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise FoundryError(f"Could not stage provider-native input: {exc}") from exc


def _write_new_text(path: Path, value: str) -> None:
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        path.unlink(missing_ok=True)
        raise FoundryError(f"Could not create provider-native sandbox file: {exc}") from exc


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise FoundryError(f"Could not hash provider-native artifact: {exc}") from exc
    return digest.hexdigest(), size
