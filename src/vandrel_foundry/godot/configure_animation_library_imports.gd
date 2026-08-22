@tool
extends SceneTree

const REQUEST_PATH := "res://animation-library-runtime.json"
const BONE_MAP_PATH := "res://animation_library_bone_map.tres"
const SKELETON_KEY := "PATH:Armature/Skeleton3D"


func _init() -> void:
	var request := _read_json(REQUEST_PATH)
	var bone_map := load(BONE_MAP_PATH) as BoneMap
	if request.is_empty() or bone_map == null:
		_fail("runtime request or accepted BoneMap is unavailable")
		return
	for motion in request.get("motions", []):
		var source_path := str(motion.get("source_path", ""))
		if not _configure(source_path + ".import", bone_map):
			return
	print("FOUNDRY_ANIMATION_IMPORT_CONFIGURATION_OK motions=%d" % request.motions.size())
	quit(0)


func _configure(import_path: String, bone_map: BoneMap) -> bool:
	var config := ConfigFile.new()
	var load_error := config.load(import_path)
	if load_error != OK:
		_fail("could not load %s: %s" % [import_path, error_string(load_error)])
		return false
	var destination := str(config.get_value("remap", "path", ""))
	if destination.ends_with(".scn"):
		destination = destination.trim_suffix(".scn") + ".res"
	if not destination.ends_with(".res"):
		_fail("animation importer destination is not a Resource: %s" % destination)
		return false
	config.set_value("remap", "importer", "animation_library")
	config.set_value("remap", "type", "AnimationLibrary")
	config.set_value("remap", "path", destination)
	config.set_value("deps", "dest_files", PackedStringArray([destination]))
	config.set_value("params", "animation/trimming", false)
	config.set_value("params", "animation/remove_immutable_tracks", true)
	config.set_value("params", "_subresources", {"nodes": {SKELETON_KEY: {
		"rest_pose/external_animation_library": null,
		"retarget/bone_map": bone_map,
		"retarget/remove_tracks/except_bone_transform": false,
		"retarget/remove_tracks/unimportant_positions": true,
		"retarget/remove_tracks/unmapped_bones": 1,
		"retarget/bone_renamer/rename_bones": true,
		"retarget/bone_renamer/unique_node/make_unique": true,
		"retarget/bone_renamer/unique_node/skeleton_name": "GeneralSkeleton",
		"retarget/rest_fixer/apply_node_transforms": true,
		"retarget/rest_fixer/normalize_position_tracks": true,
		"retarget/rest_fixer/reset_all_bone_poses_after_import": true,
		"retarget/rest_fixer/retarget_method": 1,
		"retarget/rest_fixer/keep_global_rest_on_leftovers": true,
		"retarget/rest_fixer/fix_silhouette/enable": false,
		"retarget/rest_fixer/fix_silhouette/filter": [],
		"retarget/rest_fixer/fix_silhouette/threshold": 15.0,
		"retarget/rest_fixer/fix_silhouette/base_height_adjustment": 0.0,
	}}})
	var save_error := config.save(import_path)
	if save_error != OK:
		_fail("could not save %s: %s" % [import_path, error_string(save_error)])
		return false
	return true


func _read_json(path: String) -> Dictionary:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return {}
	var value = JSON.parse_string(file.get_as_text())
	return value if value is Dictionary else {}


func _fail(message: String) -> void:
	push_error(message)
	quit(1)
