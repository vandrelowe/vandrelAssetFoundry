import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, utc_now
from vandrel_foundry.domain.meshy_native_character_motion import (
    MeshyNativeCharacterMotionReport,
)
from vandrel_foundry.domain.meshy_native_release import MeshyNativeReleaseReport
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.domain.workflow_policy import invalidate_approval
from vandrel_foundry.services.inspect_glb import inspect_glb
from vandrel_foundry.services.inspect_glb_skin import inspect_top4_glb_skin
from vandrel_foundry.services.validate_godot import (
    SAFE_ENVIRONMENT_KEYS,
    ProcessResult,
    ProcessRunner,
    run_bounded_process,
)
from vandrel_foundry.services.windows_acl_policy import apply_candidate_acl
from vandrel_foundry.storage.atomic import json_bytes
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path

PROCESSOR_NAME = "godot_meshy_native_character_release_validation"
PROCESSOR_VERSION = "1"
ASSEMBLY_PROCESSOR = "blender_meshy_native_character_motion_assembly"
REPORT_ROLE = "meshy_native_character_release_report"
CHECK_NAME = "meshy_native_character_release_playback"

PROJECT_TEXT = """; Generated Foundry validation project. Not a runtime project.
config_version=5

[application]
config/name="Vandrel Foundry Meshy Native Release Validation"

[rendering]
renderer/rendering_method="gl_compatibility"
"""

GODOT_SCRIPT = r'''extends SceneTree

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	var expected_file := FileAccess.open("res://expected.json", FileAccess.READ)
	if expected_file == null:
		_finish({"passed": false, "error": "expected inventory unavailable"})
		return
	var expected = JSON.parse_string(expected_file.get_as_text())
	if not expected is Dictionary:
		_finish({"passed": false, "error": "expected inventory invalid"})
		return
	var packed := load("res://model.glb") as PackedScene
	if packed == null:
		_finish({"passed": false, "error": "model failed to import"})
		return
	var instance := packed.instantiate()
	root.add_child(instance)
	await process_frame
	var player := _best_player(instance)
	var skeleton := _first_skeleton(instance)
	var mesh_count := 0
	var visible_skinned_mesh_count := 0
	var textured_material_count := 0
	for node in instance.find_children("*", "MeshInstance3D", true, false):
		var mesh_instance := node as MeshInstance3D
		if mesh_instance.mesh == null:
			continue
		mesh_count += 1
		var bound_skeleton := mesh_instance.get_node_or_null(mesh_instance.skeleton)
		if mesh_instance.is_visible_in_tree() and mesh_instance.skin != null and bound_skeleton is Skeleton3D:
			visible_skinned_mesh_count += 1
		for surface_index in mesh_instance.mesh.get_surface_count():
			var material := mesh_instance.get_active_material(surface_index)
			if material is BaseMaterial3D and (material as BaseMaterial3D).albedo_texture != null:
				textured_material_count += 1
	var expected_clips: Dictionary = expected.get("clips", {})
	var actual_names: Array[String] = []
	if player != null:
		for value in player.get_animation_list():
			var name := str(value)
			if name != "RESET":
				actual_names.append(name)
	actual_names.sort()
	var expected_names: Array[String] = []
	for value in expected_clips.keys():
		expected_names.append(str(value))
	expected_names.sort()
	var missing: Array[String] = []
	var unexpected: Array[String] = []
	for name in expected_names:
		if not actual_names.has(name):
			missing.append(name)
	for name in actual_names:
		if not expected_names.has(name):
			unexpected.append(name)
	var maximum_duration_delta := 0.0
	var duration_deltas: Dictionary = {}
	var finite_samples := true
	if player != null and skeleton != null:
		for name in expected_names:
			if not player.has_animation(name):
				continue
			var animation := player.get_animation(name)
			var duration_delta: float = abs(
				animation.length - float(expected_clips[name])
			)
			duration_deltas[name] = duration_delta
			maximum_duration_delta = max(maximum_duration_delta, duration_delta)
			for sample in [0.0, animation.length * 0.5, animation.length]:
				player.play(name)
				player.seek(sample, true)
				player.pause()
				await process_frame
				for bone_index in skeleton.get_bone_count():
					finite_samples = finite_samples and _finite_transform(
						skeleton.get_bone_global_pose(bone_index)
					)
	var dead_hold_delta := 999.0
	var dead_name := "target_character|Dead"
	if player != null and skeleton != null and player.has_animation(dead_name):
		var dead := player.get_animation(dead_name)
		player.play(dead_name)
		player.seek(dead.length, true)
		player.pause()
		await process_frame
		var before := skeleton.get_bone_global_pose(0)
		await process_frame
		await process_frame
		var after := skeleton.get_bone_global_pose(0)
		dead_hold_delta = before.origin.distance_to(after.origin)
	var bone_count := skeleton.get_bone_count() if skeleton != null else 0
	var passed := player != null and skeleton != null and bone_count == 24
	passed = passed and mesh_count > 0 and visible_skinned_mesh_count > 0
	passed = passed and textured_material_count > 0 and missing.is_empty()
	passed = passed and unexpected.is_empty() and maximum_duration_delta <= 0.033334
	passed = passed and finite_samples and dead_hold_delta <= 0.000001
	_finish({
		"schema": "vandrel_foundry_godot_meshy_native_release/1.0",
		"passed": passed,
		"bone_count": bone_count,
		"mesh_count": mesh_count,
		"visible_skinned_mesh_count": visible_skinned_mesh_count,
		"textured_material_count": textured_material_count,
		"animation_count": actual_names.size(),
		"animation_names": actual_names,
		"missing_animations": missing,
		"unexpected_animations": unexpected,
		"maximum_duration_delta_seconds": maximum_duration_delta,
		"duration_tolerance_policy": "godot_import_may_quantize_by_at_most_one_30fps_frame",
		"duration_tolerance_seconds": 0.033334,
		"duration_deltas_seconds": duration_deltas,
		"finite_sampled_bone_transforms": finite_samples,
		"dead_final_hold_root_delta": dead_hold_delta,
	})

func _best_player(node: Node) -> AnimationPlayer:
	var best: AnimationPlayer = null
	for candidate in node.find_children("*", "AnimationPlayer", true, false):
		var player := candidate as AnimationPlayer
		if best == null or player.get_animation_list().size() > best.get_animation_list().size():
			best = player
	return best

func _first_skeleton(node: Node) -> Skeleton3D:
	for candidate in node.find_children("*", "Skeleton3D", true, false):
		return candidate as Skeleton3D
	return null

func _finite_transform(value: Transform3D) -> bool:
	var values := [
		value.origin.x, value.origin.y, value.origin.z,
		value.basis.x.x, value.basis.x.y, value.basis.x.z,
		value.basis.y.x, value.basis.y.y, value.basis.y.z,
		value.basis.z.x, value.basis.z.y, value.basis.z.z,
	]
	for number in values:
		if not is_finite(number):
			return false
	return true

func _finish(value: Dictionary) -> void:
	var output := FileAccess.open("res://result.json", FileAccess.WRITE)
	if output != null:
		output.store_string(JSON.stringify(value, "\t"))
	quit(0 if value.get("passed", false) else 1)
'''


@dataclass(frozen=True)
class MeshyNativeReleaseValidationResult:
    report: Artifact
    process_log: Artifact
    import_result: ProcessResult
    playback_result: ProcessResult


def validate_meshy_native_character_release(
    config: FoundryConfig,
    asset_id: str,
    runner: ProcessRunner | None = None,
    environment: Mapping[str, str] | None = None,
) -> MeshyNativeReleaseValidationResult:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.asset.lane != "humanoid" or manifest.workflow.state is not WorkflowState.REVIEW:
        raise FoundryError("Meshy-native release validation requires a reviewed humanoid.")
    model = _latest(manifest, "processed_model")
    if model.processor is None or model.processor.name != ASSEMBLY_PROCESSOR:
        raise FoundryError("Meshy-native release validation requires the current H4 assembly.")
    assembly = _latest(manifest, "meshy_native_character_motion_report")
    asset_root = repository.asset_directory(asset_id)
    model_path = contained_path(asset_root, model.path)
    assembly_path = contained_path(asset_root, assembly.path)
    _verify(model_path, model)
    _verify(assembly_path, assembly)
    assembly_data = MeshyNativeCharacterMotionReport.model_validate(
        json.loads(assembly_path.read_text(encoding="utf-8"))
    )
    if (
        assembly_data.schema_name != "vandrel_foundry_meshy_native_character_motion/1.2"
        or assembly_data.output.get("sha256") != model.sha256
        or len(assembly_data.clips) != 29
        or len(assembly_data.playback) != 13
    ):
        raise FoundryError("Current Meshy-native assembly evidence is incomplete.")
    roots = [
        item for item in manifest.artifacts if item.stage == "source" and not item.derived_from
    ]
    if len(roots) != 28 or set(model.derived_from) != {item.artifact_id for item in roots}:
        raise FoundryError("Current Meshy-native model does not bind the exact 28-root union.")
    playback_artifacts = _playback_artifacts(manifest, assembly_data.playback)
    inputs = [model, assembly, *roots, *playback_artifacts]
    for artifact in inputs:
        _verify(contained_path(asset_root, artifact.path), artifact)
    standard_check = next(
        (
            item
            for item in reversed(manifest.validation.checks)
            if item.get("name") == "godot_sandbox_import" and item.get("passed")
        ),
        None,
    )
    if standard_check is None:
        raise FoundryError("Meshy-native release validation requires passing Godot import.")
    executable = config.tools.godot_executable
    if executable is None or not executable.is_absolute() or not executable.is_file():
        raise FoundryError("Configure an absolute Godot executable for release validation.")
    number = sum(item.role == REPORT_ROLE for item in manifest.artifacts) + 1
    report_relative = RelativeManifestPath(
        f"reports/meshy-native-character-release-{number:03d}.json"
    )
    process_relative = RelativeManifestPath(
        f"reports/meshy-native-character-release-{number:03d}.process.json"
    )
    report_final = contained_path(asset_root, report_relative)
    process_final = contained_path(asset_root, process_relative)
    if report_final.exists() or process_final.exists():
        raise FoundryError("Meshy-native release evidence destination already exists.")
    temporary = Path(tempfile.mkdtemp(prefix=".meshy-native-release-", dir=asset_root))
    promoted: list[Path] = []
    source_revision = manifest.revision
    try:
        apply_candidate_acl(config, temporary)
        _copy_new(model_path, temporary / "model.glb")
        _write_new(temporary / "project.godot", PROJECT_TEXT.encode())
        _write_new(temporary / "validate.gd", GODOT_SCRIPT.encode())
        clip_durations = {
            str(item["exact_name"]): float(item["duration_seconds"])
            for item in assembly_data.clips
        }
        _write_new(
            temporary / "expected.json",
            json_bytes({"clips": clip_durations}),
        )
        safe_environment = {
            key: value
            for key, value in (environment or os.environ).items()
            if key.upper() in SAFE_ENVIRONMENT_KEYS
        }
        process_runner = runner or run_bounded_process
        import_result = process_runner(
            [str(executable), "--headless", "--path", str(temporary), "--import", "--quit"],
            temporary,
            safe_environment,
            config.tools.godot_timeout_seconds,
            config.tools.maximum_output_bytes,
        )
        _require_success(import_result, "Godot Meshy-native import")
        playback_result = process_runner(
            [
                str(executable),
                "--headless",
                "--path",
                str(temporary),
                "--script",
                "res://validate.gd",
            ],
            temporary,
            safe_environment,
            config.tools.godot_timeout_seconds,
            config.tools.maximum_output_bytes,
        )
        _require_success(playback_result, "Godot Meshy-native playback")
        godot = _load_godot_report(temporary / "result.json")
        inspection = inspect_glb(model_path)
        skin = inspect_top4_glb_skin(model_path)
        facts = assembly_data.transformation_facts
        expected_skin = facts.get("independent_final_top4_skin")
        expected_skin_facts = (
            expected_skin if isinstance(expected_skin, dict) else {}
        )
        actual_skin_facts = {
            "policy": skin.policy,
            "skin_payload_sha256": skin.skin_payload_sha256,
            "inverse_bind_matrices_sha256": skin.inverse_bind_matrices_sha256,
            "material_binding_sha256": skin.material_binding_sha256,
            "embedded_image_sha256s": list(skin.embedded_image_sha256s),
            "unweighted_vertex_count": skin.unweighted_vertex_count,
            "maximum_influences": skin.maximum_influences,
        }
        if (
            inspection.animation_count != 29
            or inspection.skin_count != 1
            or inspection.joint_count != 24
            or inspection.material_count < 1
            or inspection.image_count < 1
            or facts.get("semantic_transfer_policy")
            != "native_joint_identity_global_pose_reconstruction"
            or facts.get("bind_matrices_preserved") is not True
            or facts.get("material_texture_preserved") is not True
            or facts.get("independent_top4_reference_match") is not True
            or any(
                expected_skin_facts.get(key) != value
                for key, value in actual_skin_facts.items()
            )
        ):
            raise FoundryError(
                "Independent Meshy-native model, skin, bind, material, or texture proof failed."
            )
        h4_global = float(facts.get("maximum_sampled_global_orientation_delta_degrees", math.inf))
        h4_local = float(
            facts.get("maximum_sampled_parent_local_orientation_delta_degrees", math.inf)
        )
        if h4_global > 0.001 or h4_local > 0.001:
            raise FoundryError("H4 orientation reconstruction exceeds release tolerance.")
        selected = [
            "target_character|019fe8ca-a6c4-7968-822f-92efebbab5a4",
            "target_character|019fe8d7-ed16-7b82-a594-728d821ee711",
            "target_character|Idle_6",
            "target_character|Dead",
            "target_character|Stand_To_Side_Lying",
            "target_character|Walking",
            "target_character|Running",
            "target_character|Angry_Ground_Stomp",
            "target_character|Hit_Reaction_1",
            "target_character|Carry_Heavy_Object_Walk",
            "target_character|Collect_Object",
            "target_character|Female_Crouch_Pick_Fruit_Basket_Stand",
            "target_character|Female_Stand_Pick_Fruit_Basket",
        ]
        report_value = MeshyNativeReleaseReport(
            schema="vandrel_foundry_meshy_native_character_release/1.0",
            asset_id=asset_id,
            processed_model={
                "artifact_id": model.artifact_id,
                "sha256": model.sha256,
                "size_bytes": model.size_bytes,
            },
            assembly_report={
                "artifact_id": assembly.artifact_id,
                "sha256": assembly.sha256,
                "size_bytes": assembly.size_bytes,
            },
            source_union=sorted(item.artifact_id for item in roots),
            clip_inventory=assembly_data.clips,
            playback_evidence=[
                {
                    "artifact_id": artifact.artifact_id,
                    "sha256": artifact.sha256,
                    "size_bytes": artifact.size_bytes,
                    "exact_name": descriptor["exact_name"],
                    "duration_seconds": descriptor["duration_seconds"],
                }
                for artifact, descriptor in zip(
                    playback_artifacts, assembly_data.playback, strict=True
                )
            ],
            selected_review_clips=selected,
            godot={
                **godot,
                "standard_import_check": standard_check,
                "processed_model_sha256": model.sha256,
            },
            skin={
                **skin.__dict__,
                "joint_weight_sets": list(skin.joint_weight_sets),
                "embedded_image_sha256s": list(skin.embedded_image_sha256s),
            },
            material_texture={
                "material_count": inspection.material_count,
                "texture_count": inspection.texture_count,
                "image_count": inspection.image_count,
                "material_binding_sha256": skin.material_binding_sha256,
                "embedded_texture_sha256s": list(skin.embedded_image_sha256s),
            },
            h4_transfer={
                "policy": facts.get("semantic_transfer_policy"),
                "maximum_global_orientation_delta_degrees": h4_global,
                "maximum_parent_local_orientation_delta_degrees": h4_local,
                "target_bind_matrices_preserved": facts.get("bind_matrices_preserved"),
                "material_texture_preserved": facts.get("material_texture_preserved"),
                "h4_additional_hand_corruption": False,
            },
            visual_debt={
                "status": "accepted_bounded_debt",
                "known_limitation": (
                    "Meshy provider-native hands may retain odd orientation or weighting"
                ),
                "acceptance_basis": "user_visual_acceptance",
                "h4_additional_hand_corruption": False,
                "repair_policy": "no_broad_hand_rig_repair_in_this_release",
            },
            readiness={
                "technical_release_ready": True,
                "candidate_only": True,
                "vandrel_runtime_accepted": False,
                "gameplay_mapping_included": False,
            },
        )
        report_temp = temporary / "release-report.json"
        _write_new(
            report_temp,
            json_bytes(report_value.model_dump(mode="json", by_alias=True)),
        )
        process_temp = temporary / "process.json"
        _write_new(
            process_temp,
            json_bytes(
                {
                    "schema": "vandrel_foundry_bounded_process_set/1.0",
                    "processor": {"name": PROCESSOR_NAME, "version": PROCESSOR_VERSION},
                    "tool_version": "Godot reported in bounded output",
                    "logical_arguments": [
                        "--headless --path <operation-root> --import --quit",
                        "--headless --path <operation-root> --script res://validate.gd",
                    ],
                    "import": _process_result(import_result),
                    "playback": _process_result(playback_result),
                }
            ),
        )
        for artifact in inputs:
            _verify(contained_path(asset_root, artifact.path), artifact)
        report_hash, report_size = _hash(report_temp)
        process_hash, process_size = _hash(process_temp)
        processor = Processor(name=PROCESSOR_NAME, version=PROCESSOR_VERSION)
        report_artifact = Artifact(
            artifact_id=f"meshy_native_character_release_report_{number:03d}",
            role=REPORT_ROLE,
            stage="review",
            format="json",
            path=report_relative,
            sha256=report_hash,
            size_bytes=report_size,
            derived_from=[model.artifact_id, assembly.artifact_id, *(x.artifact_id for x in playback_artifacts)],
            processor=processor,
        )
        process_artifact = Artifact(
            artifact_id=f"meshy_native_character_release_process_log_{number:03d}",
            role="meshy_native_character_release_process_log",
            stage="validation",
            format="json",
            path=process_relative,
            sha256=process_hash,
            size_bytes=process_size,
            derived_from=[report_artifact.artifact_id],
            processor=processor,
        )
        _promote(report_temp, report_final)
        promoted.append(report_final)
        _promote(process_temp, process_final)
        promoted.append(process_final)
        for artifact in inputs:
            _verify(contained_path(asset_root, artifact.path), artifact)
        _verify(report_final, report_artifact)
        _verify(process_final, process_artifact)
        manifest.artifacts.extend([report_artifact, process_artifact])
        check = {
            "name": CHECK_NAME,
            "passed": True,
            "report": str(report_relative),
            "report_sha256": report_artifact.sha256,
            "processed_model_sha256": model.sha256,
            "assembly_report_sha256": assembly.sha256,
            "clip_count": 29,
            "playback_evidence_count": 13,
            "godot_playback_passed": True,
            "skin_binding_passed": True,
            "zero_unweighted_vertices": skin.unweighted_vertex_count == 0,
            "embedded_texture_sha256s": list(skin.embedded_image_sha256s),
            "h4_additional_hand_corruption": False,
            "accepted_hand_visual_debt": True,
        }
        manifest.validation.checks = [
            item for item in manifest.validation.checks if item.get("name") != CHECK_NAME
        ] + [check]
        manifest.validation.result = (
            "passed" if all(item.get("passed") for item in manifest.validation.checks) else "failed"
        )
        invalidate_approval(manifest)
        manifest.revision += 1
        manifest.asset.updated_at = utc_now()
        target_revision = manifest.revision
        try:
            repository.save(
                manifest,
                "validation.meshy_native_character_release_passed",
                expected_revision=source_revision,
            )
        except BaseException:
            live = repository.load(asset_id)
            if _exact_target(live, target_revision, [report_artifact, process_artifact]):
                diagnosis = repository.diagnose_pending_save(asset_id)
                if diagnosis.status in {"event_missing", "event_partial", "event_complete"}:
                    repository.reconcile_pending_save(asset_id)
            elif live.revision == source_revision and not _references(
                live, [report_artifact, process_artifact]
            ):
                for path in promoted:
                    path.unlink(missing_ok=True)
                raise
            else:
                raise
        _verify(report_final, report_artifact)
        _verify(process_final, process_artifact)
        return MeshyNativeReleaseValidationResult(
            report_artifact,
            process_artifact,
            import_result,
            playback_result,
        )
    except BaseException:
        live = repository.load(asset_id)
        if live.revision == source_revision:
            for path in promoted:
                path.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def _playback_artifacts(manifest, descriptors):
    by_id = {item.artifact_id: item for item in manifest.artifacts}
    values = []
    for descriptor in descriptors:
        artifact_id = descriptor.get("artifact_id")
        artifact = by_id.get(artifact_id)
        if artifact is None or artifact.role != "meshy_native_character_motion_playback":
            raise FoundryError("Meshy-native playback evidence binding is invalid.")
        values.append(artifact)
    if len({item.artifact_id for item in values}) != 13:
        raise FoundryError("Meshy-native playback evidence union is incomplete.")
    return values


def _latest(manifest, role):
    values = [item for item in manifest.artifacts if item.role == role]
    if not values:
        raise FoundryError(f"Meshy-native release artifact is missing: {role}")
    return values[-1]


def _load_godot_report(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FoundryError(f"Godot Meshy-native report is unreadable: {exc}") from exc
    if (
        value.get("schema") != "vandrel_foundry_godot_meshy_native_release/1.0"
        or value.get("passed") is not True
        or value.get("animation_count") != 29
        or value.get("bone_count") != 24
        or value.get("visible_skinned_mesh_count", 0) < 1
        or value.get("textured_material_count", 0) < 1
        or value.get("finite_sampled_bone_transforms") is not True
        or float(value.get("maximum_duration_delta_seconds", math.inf)) > 0.033334
        or value.get("duration_tolerance_policy")
        != "godot_import_may_quantize_by_at_most_one_30fps_frame"
        or float(value.get("dead_final_hold_root_delta", math.inf)) > 0.000001
    ):
        raise FoundryError(f"Godot Meshy-native playback evidence failed: {value}")
    return value


def _require_success(result, label):
    if result.return_code or result.timed_out or result.output_limited:
        detail = (result.stderr or result.stdout or "no output")[-2000:]
        raise FoundryError(f"{label} failed: {detail}")


def _process_result(result):
    return {
        "return_code": result.return_code,
        "duration_seconds": result.duration_seconds,
        "timed_out": result.timed_out,
        "output_limited": result.output_limited,
        "stdout": _redact(result.stdout),
        "stderr": _redact(result.stderr),
    }


def _redact(value):
    value = re.sub(r"(?i)[a-z]:[\\/][^\r\n]*", "<local-path>", value)
    return re.sub(
        r"(?i)(authorization\s*:\s*bearer|api[_-]?key|token|secret)\s*[=:]\s*\S+",
        r"\1=<redacted>",
        value,
    )


def _copy_new(source, destination):
    with source.open("rb") as first, destination.open("xb") as second:
        shutil.copyfileobj(first, second, 1024 * 1024)
        second.flush()
        os.fsync(second.fileno())


def _write_new(path, value):
    with path.open("xb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def _promote(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except FileExistsError as exc:
        raise FoundryError("Meshy-native release evidence destination appeared concurrently.") from exc


def _verify(path, artifact):
    if not path.is_file() or _hash(path) != (artifact.sha256, artifact.size_bytes):
        raise FoundryError(f"Meshy-native release input/output changed: {artifact.artifact_id}")


def _hash(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _references(manifest, artifacts):
    by_id = {item.artifact_id: item for item in manifest.artifacts}
    return all(
        item.artifact_id in by_id
        and by_id[item.artifact_id].model_dump(mode="json") == item.model_dump(mode="json")
        for item in artifacts
    )


def _exact_target(manifest, revision, artifacts):
    return manifest.revision == revision and _references(manifest, artifacts)
