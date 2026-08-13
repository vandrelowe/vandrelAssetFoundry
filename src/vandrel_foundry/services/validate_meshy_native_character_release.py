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
from vandrel_foundry.domain.meshy_native_release import (
    RELEASE_REVIEW_CLIPS,
    REPAIR_ASSEMBLY_SCHEMA,
    REPAIR_PROFILE,
    REPAIR_REVIEW_CLIPS,
    REPRESENTATIVE_ASSEMBLY_SCHEMA,
    REPRESENTATIVE_PROFILE,
    MeshyNativeReleaseReport,
    representative_review_clips,
)
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.domain.workflow_policy import invalidate_approval
from vandrel_foundry.services.inspect_glb import inspect_glb
from vandrel_foundry.services.inspect_glb_skin import (
    GlbSkinProof,
    inspect_top4_glb_skin,
    inspect_top8_repaired_glb_skin,
)
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
PROCESSOR_VERSION = "4"
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
    if assembly_data.schema_name not in {
        "vandrel_foundry_meshy_native_character_motion/1.2",
        "vandrel_foundry_meshy_native_character_motion/1.3",
        REPRESENTATIVE_ASSEMBLY_SCHEMA,
        REPAIR_ASSEMBLY_SCHEMA,
    }:
        raise FoundryError("Current Meshy-native assembly evidence schema is unsupported.")
    clip_count = len(assembly_data.clips)
    playback_count = len(assembly_data.playback)
    selected = _release_review_selection(assembly_data)
    if (
        assembly_data.output.get("sha256") != model.sha256
        or playback_count > clip_count
    ):
        raise FoundryError("Current Meshy-native assembly evidence is incomplete.")
    roots = [
        item for item in manifest.artifacts if item.stage == "source" and not item.derived_from
    ]
    root_ids = {item.artifact_id for item in roots}
    if (
        len(roots) < 28
        or set(model.derived_from) != root_ids
        or set(assembly_data.source_union) != root_ids
    ):
        raise FoundryError("Current Meshy-native model does not bind its exact source root union.")
    facts = assembly_data.transformation_facts
    is_repair = assembly_data.schema_name == REPAIR_ASSEMBLY_SCHEMA
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
    godot_binding_artifacts = []
    character_texture = None
    inspection = None
    skin = None
    if is_repair:
        godot_binding_artifacts = _current_godot_import_artifacts(
            manifest,
            standard_check,
            model,
            asset_root,
            asset_id,
        )
        character_texture = _character_texture_artifact(manifest, root_ids)
        inputs.extend([*godot_binding_artifacts, character_texture])
        for artifact in [*godot_binding_artifacts, character_texture]:
            _verify(contained_path(asset_root, artifact.path), artifact)
        inspection = inspect_glb(model_path)
        skin = inspect_top8_repaired_glb_skin(model_path)
        _require_repaired_release_proof(
            assembly_data,
            inspection,
            skin,
            character_texture.sha256,
        )
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
        godot = _load_godot_report(temporary / "result.json", clip_count)
        if not is_repair:
            inspection = inspect_glb(model_path)
            skin = inspect_top4_glb_skin(model_path)
            expected_skin = facts.get("independent_final_top4_skin")
            expected_skin_facts = expected_skin if isinstance(expected_skin, dict) else {}
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
                inspection.animation_count != clip_count
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
        assert inspection is not None
        assert skin is not None
        h4_global = float(facts.get("maximum_sampled_global_orientation_delta_degrees", math.inf))
        h4_local = float(
            facts.get("maximum_sampled_parent_local_orientation_delta_degrees", math.inf)
        )
        if h4_global > 0.001 or h4_local > 0.001:
            raise FoundryError("H4 orientation reconstruction exceeds release tolerance.")
        playback_names = [str(item["exact_name"]) for item in assembly_data.playback]
        report_value = MeshyNativeReleaseReport(
            schema=(
                "vandrel_foundry_meshy_native_character_release/1.2"
                if assembly_data.schema_name.endswith("/1.4")
                else "vandrel_foundry_meshy_native_character_release/1.3"
                if assembly_data.schema_name.endswith("/1.5")
                else
                "vandrel_foundry_meshy_native_character_release/1.1"
                if assembly_data.schema_name.endswith("/1.3")
                else "vandrel_foundry_meshy_native_character_release/1.0"
            ),
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
                **(
                    {
                        "current_model_binding_passed": True,
                        "current_import_artifacts": [
                            {
                                "artifact_id": artifact.artifact_id,
                                "role": artifact.role,
                                "sha256": artifact.sha256,
                                "size_bytes": artifact.size_bytes,
                            }
                            for artifact in godot_binding_artifacts
                        ],
                    }
                    if is_repair
                    else {}
                ),
            },
            skin=_skin_facts(skin),
            material_texture={
                "material_count": inspection.material_count,
                "texture_count": inspection.texture_count,
                "image_count": inspection.image_count,
                "material_binding_sha256": skin.material_binding_sha256,
                "embedded_texture_sha256s": list(skin.embedded_image_sha256s),
                **(
                    {
                        "character_texture_artifact": {
                            "artifact_id": character_texture.artifact_id,
                            "sha256": character_texture.sha256,
                            "size_bytes": character_texture.size_bytes,
                        }
                    }
                    if character_texture is not None
                    else {}
                ),
            },
            h4_transfer={
                "policy": facts.get("semantic_transfer_policy"),
                "maximum_global_orientation_delta_degrees": h4_global,
                "maximum_parent_local_orientation_delta_degrees": h4_local,
                "target_bind_matrices_preserved": facts.get("bind_matrices_preserved"),
                "material_texture_preserved": facts.get("material_texture_preserved"),
                "h4_additional_hand_corruption": False,
            },
            visual_debt=(
                {
                    "status": "pending_consumer_review",
                    "observation": (
                        "Meshy provider-native hands may retain odd orientation or weighting"
                    ),
                    "acceptance_basis": "pending_vandrel_lightweight_f12",
                    "h4_additional_hand_corruption": False,
                    "repair_policy": "no_broad_hand_rig_repair_in_this_release",
                }
                if is_repair
                else {
                    "status": "accepted_bounded_debt",
                    "known_limitation": (
                        "Meshy provider-native hands may retain odd orientation or weighting"
                    ),
                    "acceptance_basis": "user_visual_acceptance",
                    "h4_additional_hand_corruption": False,
                    "repair_policy": "no_broad_hand_rig_repair_in_this_release",
                }
            ),
            readiness={
                "technical_release_ready": True,
                "candidate_only": True,
                "vandrel_runtime_accepted": False,
                "gameplay_mapping_included": False,
                **(
                    {
                        "top8_source_influence_gate_passes": True,
                        "consumer_blocking_reasons": [],
                    }
                    if is_repair
                    else {}
                ),
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
            derived_from=[
                model.artifact_id,
                assembly.artifact_id,
                *(item.artifact_id for item in playback_artifacts),
                *(item.artifact_id for item in godot_binding_artifacts),
                *(
                    [character_texture.artifact_id]
                    if character_texture is not None
                    else []
                ),
            ],
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
            "clip_count": clip_count,
            "source_root_count": len(roots),
            "playback_evidence_count": playback_count,
            "playback_clip_names": playback_names,
            "assembly_evidence_schema": assembly_data.schema_name,
            "playback_evidence_profile": assembly_data.transformation_facts.get(
                "playback_evidence_profile", "release_review"
            ),
            "godot_playback_passed": True,
            "skin_binding_passed": True,
            "zero_unweighted_vertices": skin.unweighted_vertex_count == 0,
            "embedded_texture_sha256s": list(skin.embedded_image_sha256s),
            "h4_additional_hand_corruption": False,
            "accepted_hand_visual_debt": not is_repair,
            **(
                {
                    "top8_independent_skin_passed": True,
                    "top8_source_influence_gate_passes": True,
                    "consumer_blocking_reasons": [],
                    "godot_current_model_binding_passed": True,
                    "visual_debt_status": "pending_consumer_review",
                    "visual_acceptance_basis": "pending_vandrel_lightweight_f12",
                    "consumer_visual_review_pending": True,
                }
                if is_repair
                else {}
            ),
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


def _current_godot_import_artifacts(
    manifest,
    check: Mapping[str, object],
    model: Artifact,
    asset_root: Path,
    asset_id: str,
) -> list[Artifact]:
    report_path = check.get("report")
    if not isinstance(report_path, str):
        raise FoundryError("Schema 1.5 release requires a bound Godot import report.")
    reports = [
        item
        for item in manifest.artifacts
        if item.role == "godot_validation_report" and str(item.path) == report_path
    ]
    if len(reports) != 1:
        raise FoundryError("Schema 1.5 Godot import report binding is ambiguous.")
    report = reports[0]
    _verify(contained_path(asset_root, report.path), report)
    try:
        report_value = json.loads(
            contained_path(asset_root, report.path).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FoundryError(f"Schema 1.5 Godot import report is unreadable: {exc}") from exc
    if not isinstance(report_value, dict):
        raise FoundryError("Schema 1.5 Godot import report is invalid.")
    by_id = {item.artifact_id: item for item in manifest.artifacts}
    project_id = report_value.get("project_artifact_id")
    project = by_id.get(project_id) if isinstance(project_id, str) else None
    if (
        report_value.get("asset_id") != asset_id
        or report_value.get("passed") is not True
        or report_value.get("return_code") != 0
        or report_value.get("timed_out") is not False
        or report_value.get("output_limited") is not False
        or report_value.get("import_cache_created") is not True
        or project is None
        or project.role != "godot_validation_project"
        or report_value.get("project_artifact_sha256") != project.sha256
        or report.derived_from != [project.artifact_id]
    ):
        raise FoundryError("Schema 1.5 Godot import report is not a passing current binding.")
    wrapper = _single_parent(by_id, project, "godot_wrapper_scene")
    staged = _single_parent(by_id, wrapper, "godot_staged_model")
    if (
        staged.derived_from != [model.artifact_id]
        or staged.sha256 != model.sha256
        or staged.size_bytes != model.size_bytes
    ):
        raise FoundryError("Schema 1.5 Godot import is not bound to the current model.")
    values = [report, project, wrapper, staged]
    for artifact in values:
        _verify(contained_path(asset_root, artifact.path), artifact)
    return values


def _single_parent(by_id: dict[str, Artifact], child: Artifact, role: str) -> Artifact:
    if len(child.derived_from) != 1:
        raise FoundryError("Schema 1.5 Godot import lineage is incomplete.")
    parent = by_id.get(child.derived_from[0])
    if parent is None or parent.role != role:
        raise FoundryError("Schema 1.5 Godot import lineage is invalid.")
    return parent


def _character_texture_artifact(manifest, root_ids: set[str]) -> Artifact:
    values = [
        item
        for item in manifest.artifacts
        if item.role == "meshy_native_character_texture"
        and len(item.derived_from) == 1
        and item.derived_from[0] in root_ids
    ]
    if len(values) != 1:
        raise FoundryError("Schema 1.5 release requires one exact character texture.")
    return values[0]


def _skin_facts(skin: GlbSkinProof) -> dict[str, object]:
    return {
        **skin.__dict__,
        "joint_weight_sets": list(skin.joint_weight_sets),
        "embedded_image_sha256s": list(skin.embedded_image_sha256s),
        "alpha_modes": list(skin.alpha_modes),
        "metallic_factors": list(skin.metallic_factors),
        "roughness_factors": list(skin.roughness_factors),
    }


def _require_repaired_release_proof(
    assembly: MeshyNativeCharacterMotionReport,
    inspection,
    skin: GlbSkinProof,
    texture_sha256: str,
) -> None:
    facts = assembly.transformation_facts
    actual = _skin_facts(skin)
    reference = facts.get("independent_skin_reference")
    final = facts.get("independent_final_skin")
    source_maximum = facts.get("source_maximum_influences")
    if (
        inspection.animation_count != 61
        or inspection.skin_count != 1
        or inspection.joint_count != 24
        or inspection.mesh_count < 1
        or inspection.primitive_count < 1
        or inspection.material_count < 1
        or inspection.texture_count < 1
        or inspection.image_count != 1
        or not isinstance(reference, dict)
        or not isinstance(final, dict)
        or reference != actual
        or final != actual
        or facts.get("independent_skin_reference_match") is not True
        or skin.policy != "deterministic_top8_normalized"
        or skin.joint_weight_sets
        != ("JOINTS_0", "JOINTS_1", "WEIGHTS_0", "WEIGHTS_1")
        or skin.maximum_influences > 8
        or skin.unweighted_vertex_count != 0
        or skin.maximum_weight_sum_error > 1e-5
        or skin.inverse_bind_matrices_sha256 != reference.get(
            "inverse_bind_matrices_sha256"
        )
        or skin.geometry_payload_sha256 != reference.get("geometry_payload_sha256")
        or skin.material_binding_sha256 != reference.get("material_binding_sha256")
        or skin.embedded_image_sha256s != (texture_sha256,)
        or skin.material_policy != "opaque_basecolor_only_nonmetal_roughness_0_8"
        or skin.alpha_modes != ("OPAQUE",)
        or any(abs(value) > 1e-6 for value in skin.metallic_factors)
        or any(abs(value - 0.8) > 1e-6 for value in skin.roughness_factors)
        or skin.emissive_factor_maximum > 1e-6
        or skin.emissive_texture_count != 0
        or skin.identical_full_strength_base_emissive_count != 0
        or skin.specular_color_factor_maximum > 1.0 + 1e-6
        or facts.get("semantic_transfer_policy")
        != "native_joint_identity_global_pose_reconstruction"
        or facts.get("bind_matrices_preserved") is not True
        or facts.get("material_texture_preserved") is not True
        or facts.get("processing_profile") != "provider_top8_pbr_v1"
        or facts.get("skin_weight_policy") != "deterministic_top8_normalized"
        or facts.get("material_policy")
        != "opaque_basecolor_only_nonmetal_roughness_0_8"
        or facts.get("base_color_texture_only") is not True
        or facts.get("authored_distinct_emissive_mask_present") is not False
        or facts.get("emissive_factor_zero") is not True
        or facts.get("opaque_body_material") is not True
        or abs(float(facts.get("metallic_factor", math.inf))) > 1e-6
        or abs(float(facts.get("roughness_factor", math.inf)) - 0.8) > 1e-6
        or facts.get("normal_and_tangent_geometry_preservation_required") is not True
        or not isinstance(source_maximum, int)
        or isinstance(source_maximum, bool)
        or source_maximum > 8
        or facts.get("source_vertices_over_8_influences") != 0
        or facts.get("positive_source_influence_count_dropped") != 0
        or abs(float(facts.get("dropped_source_weight_above_8_total", math.inf)))
        > 1e-8
        or facts.get("positive_source_influence_identities_preserved") is not True
        or facts.get("top8_normalized") is not True
        or facts.get("top8_maximum_influences") != skin.maximum_influences
        or facts.get("output_action_count") != 61
        or facts.get("final_unique_runtime_action_count") != 61
        or assembly.runtime_readiness.get("top8_source_influence_gate_passes") is not True
        or assembly.runtime_readiness.get("consumer_blocking_reasons") != []
        or assembly.runtime_readiness.get("vandrel_ready") is not False
    ):
        raise FoundryError(
            "Independent schema 1.5 model, top-eight skin, bind, geometry, material, "
            "texture, source-influence, or readiness proof failed."
        )


def _playback_artifacts(manifest, descriptors):
    by_id = {item.artifact_id: item for item in manifest.artifacts}
    values = []
    for descriptor in descriptors:
        artifact_id = descriptor.get("artifact_id")
        artifact = by_id.get(artifact_id)
        if artifact is None or artifact.role != "meshy_native_character_motion_playback":
            raise FoundryError("Meshy-native playback evidence binding is invalid.")
        values.append(artifact)
    if len({item.artifact_id for item in values}) != len(descriptors):
        raise FoundryError("Meshy-native playback evidence union is incomplete.")
    return values


def _release_review_selection(assembly_data: MeshyNativeCharacterMotionReport) -> list[str]:
    clip_names = [str(item.get("exact_name")) for item in assembly_data.clips]
    playback_names = [str(item.get("exact_name")) for item in assembly_data.playback]
    if assembly_data.schema_name == REPAIR_ASSEMBLY_SCHEMA:
        readiness = assembly_data.runtime_readiness
        expected = list(REPAIR_REVIEW_CLIPS)
        if (
            len(clip_names) != 61
            or len(set(clip_names)) != 61
            or playback_names != expected
            or assembly_data.transformation_facts.get("playback_evidence_profile")
            != REPAIR_PROFILE
            or readiness.get("top8_source_influence_gate_passes") is not True
            or readiness.get("consumer_blocking_reasons") != []
        ):
            raise FoundryError(
                "Schema 1.5 Meshy-native release evidence requires the complete "
                "61-action inventory, exact repair playback clips, and a passing "
                "top-eight source influence gate without consumer blockers."
            )
        return expected
    if assembly_data.schema_name == REPRESENTATIVE_ASSEMBLY_SCHEMA:
        try:
            expected = list(representative_review_clips(clip_names))
        except ValueError as exc:
            raise FoundryError(str(exc)) from exc
        if (
            len(clip_names) != 61
            or len(set(clip_names)) != 61
            or playback_names != expected
            or assembly_data.transformation_facts.get("playback_evidence_profile")
            != REPRESENTATIVE_PROFILE
        ):
            raise FoundryError(
                "Schema 1.4 Meshy-native release evidence requires the complete "
                "61-action inventory and exact representative playback clips."
            )
        return expected
    if (
        len(clip_names) < 29
        or len(playback_names) < 13
        or len(playback_names) > len(clip_names)
    ):
        raise FoundryError("Current Meshy-native assembly evidence is incomplete.")
    return list(dict.fromkeys([*RELEASE_REVIEW_CLIPS, *playback_names]))


def _latest(manifest, role):
    values = [item for item in manifest.artifacts if item.role == role]
    if not values:
        raise FoundryError(f"Meshy-native release artifact is missing: {role}")
    return values[-1]


def _load_godot_report(path, expected_animation_count):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FoundryError(f"Godot Meshy-native report is unreadable: {exc}") from exc
    if (
        value.get("schema") != "vandrel_foundry_godot_meshy_native_release/1.0"
        or value.get("passed") is not True
        or value.get("animation_count") != expected_animation_count
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
