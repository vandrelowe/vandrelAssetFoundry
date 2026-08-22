extends SceneTree

const BODY := "res://input/body.gltf"
const BONE_MAP := "res://input/bone_map.tres"

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	var packed := load(BODY) as PackedScene
	if packed == null:
		_fail("Initial clean-body import did not produce a PackedScene.")
		return
	var root := packed.instantiate()
	var skeletons: Array[Skeleton3D] = []
	_collect_skeletons(root, skeletons)
	if skeletons.size() != 1:
		root.free(); _fail("Clean body requires exactly one Skeleton3D."); return
	var skeleton_path := str(root.get_path_to(skeletons[0]))
	root.free()
	var config := ConfigFile.new()
	var sidecar_path := ProjectSettings.globalize_path(BODY + ".import")
	if config.load(sidecar_path) != OK:
		_fail("Generated clean-body sidecar is unavailable."); return
	config.set_value("params", "animation/import", false)
	var subresources: Dictionary = config.get_value("params", "_subresources", {})
	var nodes: Dictionary = subresources.get("nodes", {})
	var key := "PATH:" + skeleton_path
	nodes[key] = {
		"retarget/bone_map": ResourceLoader.load(BONE_MAP),
		"retarget/bone_renamer/rename_bones": true,
		"retarget/bone_renamer/unique_node/make_unique": true,
		"retarget/bone_renamer/unique_node/skeleton_name": "GeneralSkeleton",
		"retarget/remove_tracks/except_bone_transform": false,
		"retarget/remove_tracks/unimportant_positions": true,
		"retarget/remove_tracks/unmapped_bones": 0,
		"rest_pose/external_animation_library": null,
		"retarget/rest_fixer/apply_node_transforms": true,
		"retarget/rest_fixer/fix_silhouette/base_height_adjustment": 0.0,
		"retarget/rest_fixer/fix_silhouette/enable": false,
		"retarget/rest_fixer/fix_silhouette/filter": [],
		"retarget/rest_fixer/fix_silhouette/threshold": 15.0,
		"retarget/rest_fixer/keep_global_rest_on_leftovers": true,
		"retarget/rest_fixer/normalize_position_tracks": true,
		"retarget/rest_fixer/reset_all_bone_poses_after_import": true,
		"retarget/rest_fixer/retarget_method": 1,
	}
	subresources["nodes"] = nodes
	config.set_value("params", "_subresources", subresources)
	if config.save(sidecar_path) != OK:
		_fail("Could not save generated clean-body import policy."); return
	print("CLEAN_BODY_IMPORT_CONFIGURED skeleton_path=" + skeleton_path)
	quit(0)

func _collect_skeletons(node: Node, result: Array[Skeleton3D]) -> void:
	if node is Skeleton3D: result.append(node as Skeleton3D)
	for child in node.get_children(): _collect_skeletons(child, result)

func _fail(message: String) -> void:
	push_error(message); quit(1)
