@tool
extends SceneTree

const REQUEST_PATH := "res://animation-library-runtime.json"
const OUTPUT_PATH := "res://output/animation_library.res"
const REPORT_PATH := "res://output/animation-library-technical.json"
const HIPS_HORIZONTAL_POLICY := "hold_hips_xz_at_first_key_preserve_y_time_interpolation_v1"
const REST_LEAF_COMPLETION_POLICY := "restore_optimized_identity_hand_rotation_tracks_v1"
const ORDINARY_IMPORT_POLICY := "godot_skeleton_profile_humanoid_meshy_bone_map_rest_fixer_v1"
const CARRIER_BAKE_IMPORT_POLICY := "godot_skeleton_profile_humanoid_meshy_bone_map_rest_fixer_carrier_bake_v2"
const CARRIER_REMOVE_POLICY := "remove_single_armature_rotation_carrier_v1"
const CARRIER_BAKE_POLICY := "bake_single_armature_rotation_into_hips_skeleton_space_v1"
const QUATERNION_TOLERANCE := 0.00001
const HORIZONTAL_TOLERANCE := 0.0001
const REST_LEAF_BONES := ["LeftHand", "RightHand"]
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
	var import_policy := str(request.get("import_policy", ""))
	if import_policy not in [ORDINARY_IMPORT_POLICY, CARRIER_BAKE_IMPORT_POLICY]:
		_fail("runtime import policy is unsupported")
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
		var carrier_policy := str(motion.get("carrier_orientation_policy", CARRIER_REMOVE_POLICY))
		if (
			(import_policy == ORDINARY_IMPORT_POLICY and carrier_policy != CARRIER_REMOVE_POLICY)
			or (import_policy == CARRIER_BAKE_IMPORT_POLICY and carrier_policy != CARRIER_BAKE_POLICY)
		):
			failures.append({"semantic": semantic, "reason": "carrier_policy_import_policy_mismatch"})
			continue
		var carrier := (
			_bake_known_armature_carrier_into_hips(animation)
			if carrier_policy == CARRIER_BAKE_POLICY
			else _strip_known_armature_carrier(animation)
		)
		var rest_leaf_completion := _complete_optimized_rest_leaf_tracks(animation)
		var horizontal_transform := _hold_hips_horizontal_at_first_key(animation)
		var fact := _probe(semantic, motion, animation)
		fact["known_carrier_track_recognized_count"] = carrier.recognized_count
		fact["known_carrier_track_removed_count"] = carrier.removed_count
		fact["known_carrier_tracks"] = carrier.tracks
		if carrier_policy == CARRIER_BAKE_POLICY:
			fact["carrier_orientation_policy"] = carrier_policy
			fact["carrier_orientation_bake"] = carrier.bake
		fact["optimized_rest_leaf_completion_policy"] = REST_LEAF_COMPLETION_POLICY
		fact["optimized_rest_leaf_animation_length"] = rest_leaf_completion.animation_length
		fact["optimized_rest_leaf_tracks_added"] = rest_leaf_completion.tracks_added
		fact["optimized_rest_leaf_completion_passed"] = rest_leaf_completion.passed
		fact["hips_horizontal_transform_policy"] = HIPS_HORIZONTAL_POLICY
		fact["hips_horizontal_transform_applied"] = horizontal_transform.applied
		fact["hips_vertical_time_interpolation_preserved"] = horizontal_transform.preserved
		fact["hips_horizontal_pre_transform"] = horizontal_transform.pre_transform
		fact["hips_horizontal_post_transform"] = horizontal_transform.post_transform
		fact["hips_preservation_pre_transform"] = horizontal_transform.preservation_pre
		fact["hips_preservation_post_transform"] = horizontal_transform.preservation_post
		fact["passed"] = (
			bool(fact.passed)
			and bool(horizontal_transform.passed)
			and bool(rest_leaf_completion.passed)
			and bool(carrier.get("passed", true))
		)
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
		"import_policy": import_policy,
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


func _complete_optimized_rest_leaf_tracks(animation: Animation) -> Dictionary:
	var tracks_added: Array[Dictionary] = []
	var animation_length := animation.length
	var passed := is_finite(animation_length) and animation_length >= 0.0
	for bone_value in REST_LEAF_BONES:
		var bone: String = str(bone_value)
		var path: String = "%GeneralSkeleton:" + bone
		var matching_tracks: Array[int] = []
		for track_index in animation.get_track_count():
			if (
				animation.track_get_type(track_index) == Animation.TYPE_ROTATION_3D
				and str(animation.track_get_path(track_index)) == path
			):
				matching_tracks.append(track_index)
		if not matching_tracks.is_empty():
			continue
		var track_index := animation.add_track(Animation.TYPE_ROTATION_3D)
		animation.track_set_path(track_index, NodePath(path))
		animation.track_set_interpolation_type(track_index, Animation.INTERPOLATION_LINEAR)
		animation.track_insert_key(track_index, 0.0, Quaternion.IDENTITY)
		if animation.length > 0.0:
			animation.track_insert_key(track_index, animation.length, Quaternion.IDENTITY)
		var keys: Array[Dictionary] = []
		var track_passed: bool = (
			animation.track_get_type(track_index) == Animation.TYPE_ROTATION_3D
			and str(animation.track_get_path(track_index)) == path
			and animation.track_get_interpolation_type(track_index) == Animation.INTERPOLATION_LINEAR
			and animation.track_get_key_count(track_index) == (2 if animation_length > 0.0 else 1)
		)
		for key_index in animation.track_get_key_count(track_index):
			var key_time := animation.track_get_key_time(track_index, key_index)
			var key_value = animation.track_get_key_value(track_index, key_index)
			var key_finite: bool = (
				is_finite(key_time)
				and key_value is Quaternion
				and key_value.is_finite()
			)
			var key_identity: bool = key_finite and key_value == Quaternion.IDENTITY
			keys.append({
				"time": key_time,
				"value_x": key_value.x if key_value is Quaternion else 0.0,
				"value_y": key_value.y if key_value is Quaternion else 0.0,
				"value_z": key_value.z if key_value is Quaternion else 0.0,
				"value_w": key_value.w if key_value is Quaternion else 0.0,
				"finite": key_finite,
				"identity_rotation": key_identity,
			})
			track_passed = track_passed and key_identity
		if not keys.is_empty():
			track_passed = (
				track_passed
				and float(keys[0].time) == 0.0
				and float(keys[-1].time) == animation_length
			)
		passed = passed and track_passed
		tracks_added.append({
			"bone": bone,
			"path": path,
			"track_index": track_index,
			"track_type": int(animation.track_get_type(track_index)),
			"interpolation_type": int(animation.track_get_interpolation_type(track_index)),
			"key_count": animation.track_get_key_count(track_index),
			"keys": keys,
			"passed": track_passed,
		})
	return {
		"animation_length": animation_length,
		"tracks_added": tracks_added,
		"passed": passed,
	}


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
		"passed": matches.size() <= 1 and removed_count == matches.size(),
	}


func _bake_known_armature_carrier_into_hips(animation: Animation) -> Dictionary:
	var carriers: Array[int] = []
	var hips_rotations: Array[int] = []
	var hips_positions: Array[int] = []
	var carrier_position_track_count := 0
	var carrier_scale_track_count := 0
	var carrier_other_track_count := 0
	for track_index in animation.get_track_count():
		var track_type := animation.track_get_type(track_index)
		var track_path := str(animation.track_get_path(track_index))
		if track_path == "Armature":
			if track_type == Animation.TYPE_ROTATION_3D:
				carriers.append(track_index)
			elif track_type == Animation.TYPE_POSITION_3D:
				carrier_position_track_count += 1
			elif track_type == Animation.TYPE_SCALE_3D:
				carrier_scale_track_count += 1
			else:
				carrier_other_track_count += 1
		elif track_type == Animation.TYPE_ROTATION_3D and track_path == "%GeneralSkeleton:Hips":
			hips_rotations.append(track_index)
		elif track_type == Animation.TYPE_POSITION_3D and track_path == "%GeneralSkeleton:Hips":
			hips_positions.append(track_index)
	var tracks: Array[Dictionary] = []
	for carrier_index in carriers:
		tracks.append({
			"track_index": carrier_index,
			"path": "Armature",
			"type": int(Animation.TYPE_ROTATION_3D),
			"key_count": animation.track_get_key_count(carrier_index),
			"removed": false,
		})
	var failed := {
		"policy": CARRIER_BAKE_POLICY,
		"applied": false,
		"passed": false,
		"rotation_composition_order": "carrier_times_hips",
		"position_transform": "carrier_rotate_hips_position",
		"carrier_position_track_count": carrier_position_track_count,
		"carrier_scale_track_count": carrier_scale_track_count,
		"carrier_other_track_count": carrier_other_track_count,
		"carrier": {},
		"hips_rotation_pre": {},
		"hips_rotation_post": {},
		"hips_root_pre": {},
		"hips_root_post": {},
		"carrier_removed": false,
		"rotation_key_structure_preserved": false,
		"root_key_structure_preserved": false,
		"root_values_transformed": false,
	}
	if (
		carriers.size() != 1
		or carrier_position_track_count != 0
		or carrier_scale_track_count != 0
		or carrier_other_track_count != 0
		or hips_rotations.size() != 1
		or hips_positions.size() != 1
	):
		return {"recognized_count": carriers.size(), "removed_count": 0, "tracks": tracks, "passed": false, "bake": failed}
	var carrier_index := carriers[0]
	if animation.track_get_key_count(carrier_index) != 1:
		return {"recognized_count": 1, "removed_count": 0, "tracks": tracks, "passed": false, "bake": failed}
	var carrier_value = animation.track_get_key_value(carrier_index, 0)
	var carrier_time := animation.track_get_key_time(carrier_index, 0)
	if not carrier_value is Quaternion or not carrier_value.is_finite() or not is_finite(carrier_time):
		return {"recognized_count": 1, "removed_count": 0, "tracks": tracks, "passed": false, "bake": failed}
	var carrier_quaternion: Quaternion = carrier_value
	if abs(carrier_quaternion.length() - 1.0) > QUATERNION_TOLERANCE:
		return {"recognized_count": 1, "removed_count": 0, "tracks": tracks, "passed": false, "bake": failed}
	var rotation_index := hips_rotations[0]
	var position_index := hips_positions[0]
	var rotation_pre := _rotation_track_fact(animation, rotation_index)
	var root_pre := _position_track_fact(animation, position_index)
	if not bool(rotation_pre.get("passed", false)) or not bool(root_pre.get("passed", false)):
		return {"recognized_count": 1, "removed_count": 0, "tracks": tracks, "passed": false, "bake": failed}
	rotation_pre.erase("passed")
	root_pre.erase("passed")
	for key_index in animation.track_get_key_count(rotation_index):
		var before_rotation: Quaternion = animation.track_get_key_value(rotation_index, key_index)
		var baked := (carrier_quaternion * before_rotation).normalized()
		animation.track_set_key_value(rotation_index, key_index, baked)
	for key_index in animation.track_get_key_count(position_index):
		var before_position: Vector3 = animation.track_get_key_value(position_index, key_index)
		animation.track_set_key_value(
			position_index,
			key_index,
			carrier_quaternion * before_position,
		)
	var rotation_post := _rotation_track_fact(animation, rotation_index)
	var root_post := _position_track_fact(animation, position_index)
	var post_rotation_valid := bool(rotation_post.get("passed", false))
	var post_root_valid := bool(root_post.get("passed", false))
	rotation_post.erase("passed")
	root_post.erase("passed")
	var structure_preserved := _track_structure(rotation_pre) == _track_structure(rotation_post)
	var root_structure_preserved := _track_structure(root_pre) == _track_structure(root_post)
	var exact_transform := post_rotation_valid and _rotation_bake_matches(rotation_pre, rotation_post, carrier_quaternion)
	var root_values_transformed := post_root_valid and _position_bake_matches(root_pre, root_post, carrier_quaternion)
	var passed := structure_preserved and root_structure_preserved and exact_transform and root_values_transformed
	var carrier_fact := {
		"track_index": carrier_index,
		"path": "Armature",
		"type": int(Animation.TYPE_ROTATION_3D),
		"key_count": 1,
		"key_time": carrier_time,
		"interpolation_type": int(animation.track_get_interpolation_type(carrier_index)),
		"interpolation_loop_wrap": animation.track_get_interpolation_loop_wrap(carrier_index),
		"quaternion": _quaternion_fact(carrier_quaternion),
	}
	if passed:
		animation.remove_track(carrier_index)
		tracks[0]["removed"] = true
	failed = {
		"policy": CARRIER_BAKE_POLICY,
		"applied": true,
		"passed": passed,
		"rotation_composition_order": "carrier_times_hips",
		"position_transform": "carrier_rotate_hips_position",
		"carrier_position_track_count": carrier_position_track_count,
		"carrier_scale_track_count": carrier_scale_track_count,
		"carrier_other_track_count": carrier_other_track_count,
		"carrier": carrier_fact,
		"hips_rotation_pre": rotation_pre,
		"hips_rotation_post": rotation_post,
		"hips_root_pre": root_pre,
		"hips_root_post": root_post,
		"carrier_removed": passed,
		"rotation_key_structure_preserved": structure_preserved,
		"root_key_structure_preserved": root_structure_preserved,
		"root_values_transformed": root_values_transformed,
	}
	return {"recognized_count": 1, "removed_count": 1 if passed else 0, "tracks": tracks, "passed": passed, "bake": failed}


func _rotation_track_fact(animation: Animation, track_index: int) -> Dictionary:
	var keys: Array[Dictionary] = []
	var passed := true
	for key_index in animation.track_get_key_count(track_index):
		var value = animation.track_get_key_value(track_index, key_index)
		var key_time := animation.track_get_key_time(track_index, key_index)
		var transition := animation.track_get_key_transition(track_index, key_index)
		if not value is Quaternion or not value.is_finite() or not is_finite(key_time) or not is_finite(transition) or abs(value.length() - 1.0) > QUATERNION_TOLERANCE:
			passed = false
		keys.append({"time": key_time, "transition": transition, "quaternion": _quaternion_fact(value) if value is Quaternion else {}})
	return {
		"track_index": track_index,
		"path": str(animation.track_get_path(track_index)),
		"type": int(animation.track_get_type(track_index)),
		"key_count": animation.track_get_key_count(track_index),
		"interpolation_type": int(animation.track_get_interpolation_type(track_index)),
		"interpolation_loop_wrap": animation.track_get_interpolation_loop_wrap(track_index),
		"keys": keys,
		"passed": passed and not keys.is_empty(),
	}


func _position_track_fact(animation: Animation, track_index: int) -> Dictionary:
	var keys: Array[Dictionary] = []
	var passed := true
	for key_index in animation.track_get_key_count(track_index):
		var value = animation.track_get_key_value(track_index, key_index)
		var key_time := animation.track_get_key_time(track_index, key_index)
		var transition := animation.track_get_key_transition(track_index, key_index)
		var finite: bool = value is Vector3 and value.is_finite() and is_finite(key_time) and is_finite(transition)
		passed = passed and finite
		keys.append({"time": key_time, "transition": transition, "x": value.x if value is Vector3 else 0.0, "y": value.y if value is Vector3 else 0.0, "z": value.z if value is Vector3 else 0.0, "finite": finite})
	return {
		"track_index": track_index,
		"path": str(animation.track_get_path(track_index)),
		"type": int(animation.track_get_type(track_index)),
		"key_count": animation.track_get_key_count(track_index),
		"interpolation_type": int(animation.track_get_interpolation_type(track_index)),
		"interpolation_loop_wrap": animation.track_get_interpolation_loop_wrap(track_index),
		"keys": keys,
		"passed": passed and not keys.is_empty(),
	}


func _track_structure(fact: Dictionary) -> Dictionary:
	return {
		"track_index": fact.track_index,
		"path": fact.path,
		"type": fact.type,
		"key_count": fact.key_count,
		"interpolation_type": fact.interpolation_type,
		"interpolation_loop_wrap": fact.interpolation_loop_wrap,
		"times": fact["keys"].map(func(key): return key.time),
		"transitions": fact["keys"].map(func(key): return key.transition),
	}


func _rotation_bake_matches(pre: Dictionary, post: Dictionary, carrier: Quaternion) -> bool:
	if pre["keys"].size() != post["keys"].size():
		return false
	for index in pre["keys"].size():
		var before := _quaternion_from_fact(pre["keys"][index].quaternion)
		var after := _quaternion_from_fact(post["keys"][index].quaternion)
		if not _quaternion_close((carrier * before).normalized(), after):
			return false
	return true


func _position_bake_matches(pre: Dictionary, post: Dictionary, carrier: Quaternion) -> bool:
	if pre["keys"].size() != post["keys"].size():
		return false
	for index in pre["keys"].size():
		var before := _vector_from_fact(pre["keys"][index])
		var after := _vector_from_fact(post["keys"][index])
		if not _vector_close(carrier * before, after):
			return false
	return true


func _quaternion_fact(value: Quaternion) -> Dictionary:
	var length := value.length()
	return {"x": value.x, "y": value.y, "z": value.z, "w": value.w, "length": length, "finite": value.is_finite(), "unit": value.is_finite() and abs(length - 1.0) <= QUATERNION_TOLERANCE}


func _quaternion_from_fact(value: Dictionary) -> Quaternion:
	return Quaternion(float(value.x), float(value.y), float(value.z), float(value.w))


func _quaternion_close(left: Quaternion, right: Quaternion) -> bool:
	return abs(left.x - right.x) <= QUATERNION_TOLERANCE and abs(left.y - right.y) <= QUATERNION_TOLERANCE and abs(left.z - right.z) <= QUATERNION_TOLERANCE and abs(left.w - right.w) <= QUATERNION_TOLERANCE


func _vector_from_fact(value: Dictionary) -> Vector3:
	return Vector3(float(value.x), float(value.y), float(value.z))


func _vector_close(left: Vector3, right: Vector3) -> bool:
	return left.distance_to(right) <= QUATERNION_TOLERANCE


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
