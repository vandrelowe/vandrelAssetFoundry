@tool
extends SceneTree

const REQUEST_PATH := "res://animation-library-runtime.json"
const OUTPUT_PATH := "res://output/animation_library.res"
const REPORT_PATH := "res://output/animation-library-technical.json"
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
		var fact := _probe(semantic, motion, animation)
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
