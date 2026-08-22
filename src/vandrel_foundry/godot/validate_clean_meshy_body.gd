extends SceneTree

const REQUIRED_BONES := [&"Hips", &"Spine", &"Chest", &"UpperChest", &"Neck", &"Head", &"LeftShoulder", &"LeftUpperArm", &"LeftLowerArm", &"LeftHand", &"RightShoulder", &"RightUpperArm", &"RightLowerArm", &"RightHand", &"LeftUpperLeg", &"LeftLowerLeg", &"LeftFoot", &"LeftToes", &"RightUpperLeg", &"RightLowerLeg", &"RightFoot", &"RightToes"]

func _initialize() -> void: call_deferred("_run")

func _run() -> void:
	var runtime: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://runtime.json"))
	var packed := load("res://input/body.gltf") as PackedScene
	var library := load("res://input/shared_animation_library.res") as AnimationLibrary
	if packed == null or library == null: _fail("Clean-body or shared library import failed."); return
	var root := packed.instantiate(); var skeletons: Array[Skeleton3D] = []; var meshes: Array[MeshInstance3D] = []; var embedded_players: Array[AnimationPlayer] = []
	_collect(root, skeletons, meshes, embedded_players)
	if skeletons.size() != 1: root.free(); _fail("Clean body requires one skeleton."); return
	var skeleton := skeletons[0]; var mapped := 0
	for bone in REQUIRED_BONES:
		if skeleton.find_bone(bone) >= 0: mapped += 1
	var skin_present := false; var binds := 0; var weights := false; var lit := false; var shadows := true
	for mesh in meshes:
		if mesh.skin != null: skin_present = true; binds += mesh.skin.get_bind_count()
		shadows = shadows and mesh.cast_shadow != GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		for surface in range(mesh.mesh.get_surface_count()):
			var arrays := mesh.mesh.surface_get_arrays(surface)
			var surface_weights: PackedFloat32Array = arrays[Mesh.ARRAY_WEIGHTS]
			for value in surface_weights:
				if is_finite(value) and value > 0.0: weights = true
			var material := mesh.get_active_material(surface)
			lit = lit or (material is StandardMaterial3D and (material as StandardMaterial3D).albedo_texture != null and (material as StandardMaterial3D).shading_mode == BaseMaterial3D.SHADING_MODE_PER_PIXEL)
	var aabb := _combined_aabb(meshes)
	var library_names := Array(library.get_animation_list()).map(func(value): return str(value))
	var expected_names := Array(runtime.shared_semantics).map(func(value): return str(value))
	library_names.sort(); expected_names.sort()
	var horizontal_ok := _horizontal_root_motion_is_held(library)
	var facts := {
		"schema_version": "vandrel_foundry_clean_body_technical/1.0",
		"processed_body_sha256": runtime.processed_body_sha256,
		"bone_map_sha256": runtime.accepted_bone_map.sha256,
		"sidecar_policy_source_sha256": runtime.sidecar_policy_source_sha256,
		"shared_animation_library_sha256": runtime.shared_animation_library.sha256,
		"shared_animation_library_descriptor_sha256": runtime.shared_animation_library.descriptor_sha256,
		"skeleton_name": skeleton.name, "mapped_bone_count": mapped, "skeleton_count": skeletons.size(),
		"animation_count": embedded_players.reduce(func(count, value): return count + value.get_animation_list().size(), 0),
		"skin_present": skin_present, "bind_count_positive": binds > 0, "weights_present": weights,
		"external_lit_albedo": lit, "casts_shadows": shadows,
		"scale_finite_positive": aabb.size.x > 0.0 and aabb.size.y > 0.0 and aabb.size.z > 0.0 and aabb.size.is_finite(),
		"grounded": abs(aabb.position.y) <= 0.02,
		"shared_animation_pool_compatible": mapped == REQUIRED_BONES.size() and library_names == expected_names and horizontal_ok,
		"shared_semantics": Array(library.get_animation_list()).map(func(value): return str(value)),
	}
	root.free()
	_write_json("res://output/clean-body-technical.json", facts); quit(0)

func _collect(node: Node, skeletons: Array[Skeleton3D], meshes: Array[MeshInstance3D], players: Array[AnimationPlayer]) -> void:
	if node is Skeleton3D: skeletons.append(node as Skeleton3D)
	if node is MeshInstance3D: meshes.append(node as MeshInstance3D)
	if node is AnimationPlayer: players.append(node as AnimationPlayer)
	for child in node.get_children(): _collect(child, skeletons, meshes, players)

func _horizontal_root_motion_is_held(library: AnimationLibrary) -> bool:
	for name in library.get_animation_list():
		var animation := library.get_animation(name)
		var found := false
		for track in range(animation.get_track_count()):
			if animation.track_get_type(track) != Animation.TYPE_POSITION_3D or not str(animation.track_get_path(track)).ends_with(":Hips"): continue
			found = true
			if animation.track_get_key_count(track) < 1: return false
			var first: Vector3 = animation.track_get_key_value(track, 0)
			for key in range(animation.track_get_key_count(track)):
				var value: Vector3 = animation.track_get_key_value(track, key)
				if Vector2(value.x-first.x,value.z-first.z).length() > 0.0001: return false
		if not found: return false
	return true

func _combined_aabb(meshes: Array[MeshInstance3D]) -> AABB:
	var result := AABB(); var first := true
	for mesh in meshes:
		var value := mesh.global_transform * mesh.get_aabb()
		result = value if first else result.merge(value); first = false
	return result

func _write_json(path: String, value: Dictionary) -> void:
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null: _fail("Cannot write technical report."); return
	file.store_string(JSON.stringify(value, "  ") + "\n"); file.flush()

func _fail(message: String) -> void: push_error(message); quit(1)
