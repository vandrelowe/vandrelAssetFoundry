@tool
extends SceneTree

const REQUEST_PATH := "res://animation-library-runtime.json"
const OUTPUT_PATH := "res://output/animation_library.res"
const REPORT_PATH := "res://output/animation-library-technical.json"
const HIPS_HORIZONTAL_POLICY := "hold_hips_xz_at_first_key_preserve_y_time_interpolation_v1"
const HORIZONTAL_TOLERANCE := 0.0001
const EXPECTED_ROTATION_BONES := [
	"Hips", "Spine", "Chest", "UpperChest", "Neck", "Head",
	"LeftShoulder", "LeftUpperArm", "LeftLowerArm", "LeftHand",
	"RightShoulder", "RightUpperArm", "RightLowerArm", "RightHand",
	"LeftUpperLeg", "LeftLowerLeg", "LeftFoot", "LeftToes",
	"RightUpperLeg", "RightLowerLeg", "RightFoot", "RightToes",
]


func _init() -> void:
	var request := _read_json(REQUEST_PATH)
	if request.is_empty():
		_fail("runtime request is unavailable")
		return
	var output := AnimationLibrary.new()
	var facts: Array[Dictionary] = []
	var seen_semantics: Dictionary = {}
	var failures: Array[Dictionary] = []
	for motion in request.get("motions", []):
		var semantic := str(motion.get("semantic", ""))
		var source_path := str(motion.get("source_path", ""))
		if semantic.is_empty() or seen_semantics.has(semantic):
			failures.append({"semantic": semantic, "reason": "invalid_or_duplicate_semantic"})
			continue
		seen_semantics[semantic] = true
		if FileAccess.get_sha256(source_path) != str(motion.get("source_sha256", "")):
			failures.append({"semantic": semantic, "reason": "source_hash_changed"})
			continue
		var source := load(source_path) as AnimationLibrary
		if source == null or source.get_animation_list().size() != 1:
			failures.append({"semantic": semantic, "reason": "source_animation_membership"})
			continue
		var animation := source.get_animation(source.get_animation_list()[0]).duplicate(true) as Animation
		if animation == null:
			failures.append({"semantic": semantic, "reason": "deep_duplicate_failed"})
			continue
		var carrier := _strip_known_armature_carrier(animation)
		var horizontal_transform := _hold_hips_horizontal_at_first_key(animation)
		var fact := _probe(semantic, motion, animation)
		fact["known_carrier_track_recognized_count"] = carrier.recognized_count
		fact["known_carrier_track_removed_count"] = carrier.removed_count
		fact["known_carrier_tracks"] = carrier.tracks
		fact["hips_horizontal_transform_policy"] = HIPS_HORIZONTAL_POLICY
		fact["hips_horizontal_transform_applied"] = horizontal_transform.applied
		fact["hips_vertical_time_interpolation_preserved"] = horizontal_transform.preserved
		fact["hips_horizontal_pre_transform"] = horizontal_transform.pre_transform
		fact["hips_horizontal_post_transform"] = horizontal_transform.post_transform
		fact["hips_preservation_pre_transform"] = horizontal_transform.preservation_pre
		fact["hips_preservation_post_transform"] = horizontal_transform.preservation_post
		fact["passed"] = bool(fact.passed) and bool(horizontal_transform.passed)
		print("FOUNDRY_ANIMATION_TRACK_FACT " + JSON.stringify(fact))
		facts.append(fact)
		if not bool(fact.get("passed", false)):
			failures.append({"semantic": semantic, "reason": "technical_track_contract"})
			continue
		animation.loop_mode = Animation.LOOP_LINEAR if str(motion.get("loop_mode")) == "linear" else Animation.LOOP_NONE
		if output.add_animation(semantic, animation) != OK:
			failures.append({"semantic": semantic, "reason": "output_add_failed"})
	if not failures.is_empty():
		print("FOUNDRY_ANIMATION_FAILURE_SUMMARY " + JSON.stringify(failures))
		_fail("animation technical contract failed for %d selected motions" % failures.size())
		return
	if output.get_animation_list().size() != request.motions.size():
		_fail("output membership count differs from request")
		return
	var save_error := ResourceSaver.save(output, OUTPUT_PATH)
	if save_error != OK:
		_fail("could not save animation library: %s" % error_string(save_error))
		return
	var output_sha := FileAccess.get_sha256(OUTPUT_PATH)
	var output_size := FileAccess.get_file_as_bytes(OUTPUT_PATH).size()
	for fact in facts:
		fact["output_library_sha256"] = output_sha
	var report := {
		"schema_version": "vandrel_foundry_animation_library_technical/1.0",
		"import_policy": "godot_skeleton_profile_humanoid_meshy_bone_map_rest_fixer_v1",
		"horizontal_root_policy": HIPS_HORIZONTAL_POLICY,
		"animation_library_sha256": output_sha,
		"animation_library_size_bytes": output_size,
		"motions": facts,
		"passed": true,
	}
	var report_file := FileAccess.open(REPORT_PATH, FileAccess.WRITE)
	if report_file == null:
		_fail("could not create technical report")
		return
	report_file.store_string(JSON.stringify(report, "  ") + "\n")
	report_file.close()
	print("FOUNDRY_ANIMATION_LIBRARY_OK animations=%d sha256=%s" % [facts.size(), output_sha])
	quit(0)


func _strip_known_armature_carrier(animation: Animation) -> Dictionary:
	var matches: Array[Dictionary] = []
	for track_index in animation.get_track_count():
		var track_type := animation.track_get_type(track_index)
		var track_path := str(animation.track_get_path(track_index))
		if track_type == Animation.TYPE_ROTATION_3D and track_path == "Armature":
			matches.append({
				"track_index": track_index,
				"path": track_path,
				"type": int(track_type),
				"key_count": animation.track_get_key_count(track_index),
				"removed": false,
			})
	var removed_count := 0
	if matches.size() == 1:
		animation.remove_track(int(matches[0].track_index))
		matches[0]["removed"] = true
		removed_count = 1
	return {
		"recognized_count": matches.size(),
		"removed_count": removed_count,
		"tracks": matches,
	}


func _hold_hips_horizontal_at_first_key(animation: Animation) -> Dictionary:
	var track_indices: Array[int] = []
	for track_index in animation.get_track_count():
		if (
			animation.track_get_type(track_index) == Animation.TYPE_POSITION_3D
			and str(animation.track_get_path(track_index)) == "%GeneralSkeleton:Hips"
		):
			track_indices.append(track_index)
	if track_indices.size() != 1:
		var missing_facts := _empty_horizontal_facts(0)
		return {
			"applied": false,
			"preserved": false,
			"pre_transform": missing_facts,
			"post_transform": missing_facts.duplicate(true),
			"preservation_pre": {},
			"preservation_post": {},
			"passed": false,
		}
	var track_index := track_indices[0]
	var pre_transform := _horizontal_facts(animation, track_index)
	var preserved_before := _vertical_time_interpolation_facts(animation, track_index)
	if not bool(pre_transform.finite) or int(pre_transform.key_count) < 1:
		return {
			"applied": false,
			"preserved": false,
			"pre_transform": pre_transform,
			"post_transform": pre_transform.duplicate(true),
			"preservation_pre": preserved_before,
			"preservation_post": preserved_before.duplicate(true),
			"passed": false,
		}
	var first_value: Vector3 = animation.track_get_key_value(track_index, 0)
	for key_index in animation.track_get_key_count(track_index):
		var value: Vector3 = animation.track_get_key_value(track_index, key_index)
		animation.track_set_key_value(
			track_index,
			key_index,
			Vector3(first_value.x, value.y, first_value.z),
		)
	var post_transform := _horizontal_facts(animation, track_index)
	var preserved_after := _vertical_time_interpolation_facts(animation, track_index)
	var preserved := preserved_before == preserved_after
	var passed := (
		bool(post_transform.finite)
		and int(post_transform.key_count) == int(pre_transform.key_count)
		and float(post_transform.initial_offset_x) == float(pre_transform.initial_offset_x)
		and float(post_transform.initial_offset_z) == float(pre_transform.initial_offset_z)
		and float(post_transform.span_x) <= HORIZONTAL_TOLERANCE
		and float(post_transform.span_z) <= HORIZONTAL_TOLERANCE
		and float(post_transform.max_delta_from_first) <= HORIZONTAL_TOLERANCE
		and preserved
	)
	return {
		"applied": true,
		"preserved": preserved,
		"pre_transform": pre_transform,
		"post_transform": post_transform,
		"preservation_pre": preserved_before,
		"preservation_post": preserved_after,
		"passed": passed,
	}


func _horizontal_facts(animation: Animation, track_index: int) -> Dictionary:
	var key_count := animation.track_get_key_count(track_index)
	if key_count < 1:
		return _empty_horizontal_facts(key_count)
	var first_value = animation.track_get_key_value(track_index, 0)
	if not first_value is Vector3 or not first_value.is_finite():
		return _empty_horizontal_facts(key_count)
	var min_x: float = first_value.x
	var max_x: float = first_value.x
	var min_z: float = first_value.z
	var max_z: float = first_value.z
	var max_delta := 0.0
	for key_index in key_count:
		var value = animation.track_get_key_value(track_index, key_index)
		if not value is Vector3 or not value.is_finite():
			return _empty_horizontal_facts(key_count)
		min_x = min(min_x, value.x)
		max_x = max(max_x, value.x)
		min_z = min(min_z, value.z)
		max_z = max(max_z, value.z)
		max_delta = max(
			max_delta,
			Vector2(value.x - first_value.x, value.z - first_value.z).length(),
		)
	return {
		"span_x": max_x - min_x,
		"span_z": max_z - min_z,
		"max_delta_from_first": max_delta,
		"initial_offset_x": first_value.x,
		"initial_offset_z": first_value.z,
		"key_count": key_count,
		"finite": true,
	}


func _empty_horizontal_facts(key_count: int) -> Dictionary:
	return {
		"span_x": 0.0,
		"span_z": 0.0,
		"max_delta_from_first": 0.0,
		"initial_offset_x": 0.0,
		"initial_offset_z": 0.0,
		"key_count": key_count,
		"finite": false,
	}


func _vertical_time_interpolation_facts(
	animation: Animation, track_index: int
) -> Dictionary:
	var values: Array[Dictionary] = []
	for key_index in animation.track_get_key_count(track_index):
		var value = animation.track_get_key_value(track_index, key_index)
		var key_time := animation.track_get_key_time(track_index, key_index)
		var transition := animation.track_get_key_transition(track_index, key_index)
		if (
			not value is Vector3
			or not value.is_finite()
			or not is_finite(key_time)
			or not is_finite(transition)
		):
			return {"finite": false}
		values.append({
			"y": value.y,
			"time": key_time,
			"transition": transition,
		})
	return {
		"track_interpolation_type": int(animation.track_get_interpolation_type(track_index)),
		"track_interpolation_loop_wrap": animation.track_get_interpolation_loop_wrap(track_index),
		"keys": values,
		"finite": true,
	}


func _probe(semantic: String, motion: Dictionary, animation: Animation) -> Dictionary:
	var hips_positions := 0
	var rotations: Dictionary = {}
	var scales := 0
	var non_hips_positions := 0
	var other := 0
	var finite_keys := true
	var unexpected_tracks: Array[Dictionary] = []
	var non_finite_keys: Array[Dictionary] = []
	for track_index in animation.get_track_count():
		var path := str(animation.track_get_path(track_index))
		var bone := path.get_slice(":", 1)
		match animation.track_get_type(track_index):
			Animation.TYPE_POSITION_3D:
				if bone == "Hips" and path == "%GeneralSkeleton:Hips":
					hips_positions += 1
				else:
					non_hips_positions += 1
					unexpected_tracks.append({"track_index": track_index, "path": path, "type": int(Animation.TYPE_POSITION_3D)})
			Animation.TYPE_ROTATION_3D:
				if bone in EXPECTED_ROTATION_BONES and path == "%GeneralSkeleton:" + bone:
					rotations[bone] = int(rotations.get(bone, 0)) + 1
				else:
					other += 1
					unexpected_tracks.append({"track_index": track_index, "path": path, "type": int(Animation.TYPE_ROTATION_3D)})
			Animation.TYPE_SCALE_3D:
				scales += 1
				unexpected_tracks.append({"track_index": track_index, "path": path, "type": int(Animation.TYPE_SCALE_3D)})
			_:
				other += 1
				unexpected_tracks.append({"track_index": track_index, "path": path, "type": int(animation.track_get_type(track_index))})
		for key_index in animation.track_get_key_count(track_index):
			if not _finite(animation.track_get_key_value(track_index, key_index)):
				finite_keys = false
				non_finite_keys.append({"track_index": track_index, "path": path, "key_index": key_index})
	var missing_rotation_bones: Array[String] = []
	var duplicate_rotation_bones: Array[String] = []
	for expected_bone in EXPECTED_ROTATION_BONES:
		var count := int(rotations.get(expected_bone, 0))
		if count == 0:
			missing_rotation_bones.append(expected_bone)
		elif count != 1:
			duplicate_rotation_bones.append(expected_bone)
	var rotation_count := rotations.size() if missing_rotation_bones.is_empty() and duplicate_rotation_bones.is_empty() else -1
	var passed := hips_positions == 1 and rotation_count == 22 and scales == 0 and non_hips_positions == 0 and other == 0 and finite_keys
	return {
		"semantic": semantic,
		"source_sha256": motion.source_sha256,
		"source_size_bytes": motion.source_size_bytes,
		"hips_position_track_count": hips_positions,
		"mapped_rotation_track_count": rotation_count,
		"scale_track_count": scales,
		"non_hips_position_track_count": non_hips_positions,
		"other_track_count": other,
		"finite_keys": finite_keys,
		"missing_rotation_bones": missing_rotation_bones,
		"duplicate_rotation_bones": duplicate_rotation_bones,
		"unexpected_tracks": unexpected_tracks,
		"non_finite_keys": non_finite_keys,
		"passed": passed,
	}


func _finite(value: Variant) -> bool:
	if value is float:
		return is_finite(value)
	if value is Vector3 or value is Quaternion:
		return value.is_finite()
	return false


func _read_json(path: String) -> Dictionary:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return {}
	var value = JSON.parse_string(file.get_as_text())
	return value if value is Dictionary else {}


func _fail(message: String) -> void:
	push_error(message)
	quit(1)
