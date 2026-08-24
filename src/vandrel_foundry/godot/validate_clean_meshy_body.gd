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
	var skeleton := skeletons[0]; var mapped := 0; var rest_pose_valid := true
	for bone in REQUIRED_BONES:
		var bone_index := skeleton.find_bone(bone)
		if bone_index >= 0:
			mapped += 1
			var rest := skeleton.get_bone_rest(bone_index)
			var pose := skeleton.get_bone_pose(bone_index)
			rest_pose_valid = rest_pose_valid and rest.is_finite() and pose.is_finite() and pose.is_equal_approx(rest)
	var skin_present := false; var binds := 0; var weights := false; var weights_valid := true
	var weighted_vertex_count := 0; var invalid_weight_vertex_count := 0; var zero_weight_vertex_count := 0
	var normalization_failure_count := 0; var invalid_joint_influence_count := 0
	var weight_value_count := 0; var bone_index_value_count := 0; var detected_influences_per_vertex: Array[int] = []
	var lit := not meshes.is_empty(); var shadows := true; var material_surface_count := 0
	for mesh in meshes:
		if mesh.skin != null: skin_present = true; binds += mesh.skin.get_bind_count()
		shadows = shadows and mesh.cast_shadow != GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		for surface in range(mesh.mesh.get_surface_count()):
			material_surface_count += 1
			var arrays := mesh.mesh.surface_get_arrays(surface)
			var surface_weights: PackedFloat32Array = arrays[Mesh.ARRAY_WEIGHTS]
			var surface_bones: PackedInt32Array = arrays[Mesh.ARRAY_BONES]
			var vertex_count := (arrays[Mesh.ARRAY_VERTEX] as PackedVector3Array).size()
			var influences_per_vertex := 8 if surface_weights.size() == vertex_count * 8 else 4
			weight_value_count += surface_weights.size()
			bone_index_value_count += surface_bones.size()
			detected_influences_per_vertex.append(influences_per_vertex)
			if vertex_count <= 0 or surface_weights.size() != vertex_count * influences_per_vertex or surface_bones.size() != surface_weights.size():
				weights_valid = false
				invalid_weight_vertex_count += max(vertex_count, 1)
			else:
				for vertex in range(vertex_count):
					var total := 0.0
					var vertex_valid := true
					for influence in range(influences_per_vertex):
						var index := vertex * influences_per_vertex + influence
						var value := surface_weights[index]
						var joint := surface_bones[index]
						if not is_finite(value) or value < 0.0 or (value > 0.000001 and (joint < 0 or joint >= skeleton.get_bone_count())):
							weights_valid = false
							vertex_valid = false
							invalid_joint_influence_count += 1
						total += value
					weights = weights or total > 0.0
					if total > 0.0: weighted_vertex_count += 1
					else: zero_weight_vertex_count += 1
					# RenderingServer stores four weights as RGBA16UNORM. Accept only
					# the bounded sum error introduced by that engine representation.
					var normalization_tolerance := float(influences_per_vertex) / 65535.0 + 0.000001
					if abs(total - 1.0) > normalization_tolerance:
						weights_valid = false
						vertex_valid = false
						normalization_failure_count += 1
					if not vertex_valid: invalid_weight_vertex_count += 1
			var material := mesh.get_active_material(surface)
			var standard := material as StandardMaterial3D
			lit = lit and standard != null and standard.albedo_texture != null and standard.shading_mode == BaseMaterial3D.SHADING_MODE_PER_PIXEL and not standard.emission_enabled
	var aabb := _combined_aabb(meshes)
	var library_names := Array(library.get_animation_list()).map(func(value): return str(value))
	var expected_names := Array(runtime.shared_semantics).map(func(value): return str(value))
	library_names.sort(); expected_names.sort()
	var horizontal_ok := _horizontal_root_motion_is_held(library)
	var import_policy_valid := _import_policy_is_exact()
	var facts := {
		"schema_version": "vandrel_foundry_clean_body_technical/1.1",
		"processed_body_sha256": runtime.processed_body_sha256,
		"bone_map_sha256": runtime.accepted_bone_map.sha256,
		"sidecar_policy_source_sha256": runtime.sidecar_policy_source_sha256,
		"shared_animation_library_sha256": runtime.shared_animation_library.sha256,
		"shared_animation_library_descriptor_sha256": runtime.shared_animation_library.descriptor_sha256,
		"skeleton_name": skeleton.name, "mapped_bone_count": mapped, "skeleton_count": skeletons.size(),
		"animation_count": embedded_players.reduce(func(count, value): return count + value.get_animation_list().size(), 0),
		"skin_present": skin_present, "bind_count_positive": binds > 0, "weights_present": weights and weights_valid,
		"weight_diagnostics": {
			"weighted_vertex_count": weighted_vertex_count, "invalid_weight_vertex_count": invalid_weight_vertex_count,
			"zero_weight_vertex_count": zero_weight_vertex_count, "normalization_failure_count": normalization_failure_count,
			"invalid_joint_influence_count": invalid_joint_influence_count, "weight_value_count": weight_value_count,
			"bone_index_value_count": bone_index_value_count, "detected_influences_per_vertex": detected_influences_per_vertex,
			"skeleton_bone_count": skeleton.get_bone_count(), "skin_bind_count": binds,
		},
		"rest_pose_valid": rest_pose_valid, "material_surface_count": material_surface_count,
		"import_policy_valid": import_policy_valid,
		"external_lit_albedo": lit and material_surface_count > 0, "casts_shadows": shadows,
		"scale_finite_positive": aabb.size.x > 0.0 and aabb.size.y > 0.0 and aabb.size.z > 0.0 and aabb.size.is_finite(),
		"grounded": abs(aabb.position.y) <= 0.02,
		"shared_animation_pool_compatible": mapped == REQUIRED_BONES.size() and rest_pose_valid and weights_valid and import_policy_valid and library_names == expected_names and horizontal_ok,
		"shared_semantics": Array(library.get_animation_list()).map(func(value): return str(value)),
	}
	root.free()
	_write_json("res://output/clean-body-technical.json", facts); quit(0)

func _import_policy_is_exact() -> bool:
	var config := ConfigFile.new()
	if config.load(ProjectSettings.globalize_path("res://input/body.gltf.import")) != OK:
		return false
	if config.get_value("params", "animation/import", true) != false:
		return false
	var subresources: Dictionary = config.get_value("params", "_subresources", {})
	var nodes: Dictionary = subresources.get("nodes", {})
	var retarget_policy_count := 0
	var exact_policy_found := false
	for node_key in nodes:
		var value = nodes[node_key]
		if not value is Dictionary:
			continue
		var policy := value as Dictionary
		if not policy.has("retarget/bone_map"):
			continue
		retarget_policy_count += 1
		var bone_map := policy.get("retarget/bone_map") as BoneMap
		exact_policy_found = exact_policy_found or (
			str(node_key).begins_with("PATH:")
			and str(node_key).length() > 5
			and bone_map != null
			and bone_map.resource_path == "res://input/bone_map.tres"
			and policy.get("retarget/bone_renamer/rename_bones") == true
			and policy.get("retarget/bone_renamer/unique_node/make_unique") == true
			and policy.get("retarget/bone_renamer/unique_node/skeleton_name") == "GeneralSkeleton"
			and policy.get("retarget/rest_fixer/apply_node_transforms") == true
			and policy.get("retarget/rest_fixer/fix_silhouette/enable") == false
			and policy.get("retarget/rest_fixer/keep_global_rest_on_leftovers") == true
			and policy.get("retarget/rest_fixer/normalize_position_tracks") == true
			and policy.get("retarget/rest_fixer/reset_all_bone_poses_after_import") == true
			and policy.get("retarget/rest_fixer/retarget_method") == 1
		)
	return retarget_policy_count == 1 and exact_policy_found

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
