@tool
extends SceneTree

const RUNTIME_PATH := "res://animation-visual-runtime.json"
const REPORT_PATH := "res://output/capture-report.json"
const EXPECTED_CAMERA_CONFIG_SHA256 := "6852a2bfd195cf5f1f885d166ec92977958668cb6a58ed868c91708fa2923eaf"
const EXPECTED_BONES := [
	"Hips", "Spine", "Chest", "UpperChest", "Neck", "Head",
	"LeftShoulder", "LeftUpperArm", "LeftLowerArm", "LeftHand",
	"RightShoulder", "RightUpperArm", "RightLowerArm", "RightHand",
	"LeftUpperLeg", "LeftLowerLeg", "LeftFoot", "LeftToes",
	"RightUpperLeg", "RightLowerLeg", "RightFoot", "RightToes",
]


func _init() -> void:
	call_deferred("_run")


func _run() -> void:
	var runtime := _read_json(RUNTIME_PATH)
	if runtime.is_empty():
		_fail("visual capture runtime request is unavailable")
		return
	if str(runtime.get("anatomy_acceptance", "")) != "not_assessed":
		_fail("visual capture may not assert anatomy acceptance")
		return
	var library_path := str(runtime.get("animation_library_path", ""))
	var technical_path := str(runtime.get("technical_report_path", ""))
	if FileAccess.get_sha256(library_path) != str(runtime.get("animation_library_sha256", "")):
		_fail("animation library hash differs from the runtime request")
		return
	if FileAccess.get_sha256(technical_path) != str(runtime.get("technical_report_sha256", "")):
		_fail("technical report hash differs from the runtime request")
		return
	var library := load(library_path) as AnimationLibrary
	if library == null:
		_fail("animation library could not be loaded")
		return
	var semantics: Array = runtime.get("selected_semantics", [])
	var actual_semantics: Array[String] = []
	for animation_name in library.get_animation_list():
		actual_semantics.append(str(animation_name))
	if actual_semantics != semantics:
		_fail("loaded animation library membership differs from the request")
		return
	var camera_config: Dictionary = runtime.get("camera_config", {})
	if str(runtime.get("camera_policy", "")) != "vandrel_fixed_animation_review_camera_v1":
		_fail("visual capture camera policy is not canonical")
		return
	if str(runtime.get("camera_config_sha256", "")) != EXPECTED_CAMERA_CONFIG_SHA256:
		_fail("visual capture camera configuration hash differs")
		return
	if (
		_vector3(camera_config.get("position", [])) != Vector3(0.0, 0.28, 5.4)
		or _vector3(camera_config.get("target", [])) != Vector3(0.0, 0.95, 0.0)
		or _vector3(camera_config.get("up", [])) != Vector3.UP
		or float(camera_config.get("fov_degrees", -1.0)) != 38.0
		or bool(camera_config.get("camera_follow_enabled", true))
		or bool(camera_config.get("per_phase_reframing", true))
		or _vector3(camera_config.get("body_origin", [])) != Vector3.ZERO
	):
		_fail("visual capture camera fields differ from the exact fixed policy")
		return
	var tolerance := float(runtime.get("horizontal_root_motion_tolerance", -1.0))
	if tolerance != 0.0001:
		_fail("horizontal root-motion tolerance differs from the contract")
		return
	var root_facts: Dictionary = {}
	for semantic in semantics:
		var animation := library.get_animation(str(semantic))
		var facts := _horizontal_root_facts(animation)
		if not bool(facts.get("passed", false)):
			_fail("horizontal root motion is not capture-safe: %s" % semantic)
			return
		root_facts[str(semantic)] = facts

	var phase_size := Vector2i(
		int(camera_config.phase_view_size[0]),
		int(camera_config.phase_view_size[1])
	)
	var grid := Vector2i(
		int(camera_config.contact_sheet_grid[0]),
		int(camera_config.contact_sheet_grid[1])
	)
	var phases: Array = camera_config.get("fixed_phases", [])
	if phases != [0.0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875]:
		_fail("visual capture phases differ from the exact contract")
		return
	if phase_size != Vector2i(1280, 720) or grid != Vector2i(4, 2):
		_fail("visual capture resolution or contact-sheet grid differs")
		return
	var output_global := ProjectSettings.globalize_path("res://output/cells")
	if DirAccess.make_dir_recursive_absolute(output_global) != OK:
		_fail("could not create visual capture cell directory")
		return

	var viewport := SubViewport.new()
	viewport.size = phase_size
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	viewport.transparent_bg = false
	get_root().add_child(viewport)
	var world := Node3D.new()
	viewport.add_child(world)
	_build_world(world, camera_config)
	var cells: Array[Dictionary] = []
	var body_bindings: Array[Dictionary] = []
	for body in runtime.get("bodies", []):
		var body_id := str(body.get("body_id", ""))
		var body_path := str(body.get("path", ""))
		var body_sha := str(body.get("payload_sha256", ""))
		if FileAccess.get_sha256(body_path) != body_sha:
			_fail("body payload hash differs: %s" % body_id)
			return
		var sidecar_path := str(body.get("import_sidecar_resource_path", ""))
		var sidecar_sha := str(body.get("import_sidecar_sha256", ""))
		var bone_map_path := str(body.get("bone_map_resource_path", ""))
		var bone_map_sha := str(body.get("bone_map_sha256", ""))
		if (
			str(body.get("staging_policy", ""))
			!= "accepted_exact_unchanged_godot_body_import_v1"
			or str(body.get("staged_payload_sha256", "")) != body_sha
			or int(body.get("staged_payload_size_bytes", -1))
			!= int(body.get("size_bytes", -2))
			or sidecar_path != body_path + ".import"
			or FileAccess.get_sha256(sidecar_path) != sidecar_sha
			or str(body.get("staged_import_sidecar_sha256", "")) != sidecar_sha
			or int(body.get("staged_import_sidecar_size_bytes", -1))
			!= int(body.get("import_sidecar_size_bytes", -2))
			or FileAccess.get_sha256(bone_map_path) != bone_map_sha
			or str(body.get("staged_bone_map_sha256", "")) != bone_map_sha
			or int(body.get("staged_bone_map_size_bytes", -1))
			!= int(body.get("bone_map_size_bytes", -2))
		):
			_fail("body import sidecar or BoneMap binding differs: %s" % body_id)
			return
		body_bindings.append({
			"body_id": body_id,
			"payload_sha256": body_sha,
			"payload_size_bytes": int(body.get("size_bytes", -1)),
			"staged_payload_sha256": str(body.staged_payload_sha256),
			"staged_payload_size_bytes": int(body.staged_payload_size_bytes),
			"resource_path": body_path,
			"staging_policy": str(body.staging_policy),
			"import_sidecar_resource_path": sidecar_path,
			"import_sidecar_sha256": sidecar_sha,
			"import_sidecar_size_bytes": int(body.import_sidecar_size_bytes),
			"staged_import_sidecar_sha256": str(body.staged_import_sidecar_sha256),
			"staged_import_sidecar_size_bytes": int(body.staged_import_sidecar_size_bytes),
			"bone_map_resource_path": bone_map_path,
			"bone_map_sha256": bone_map_sha,
			"bone_map_size_bytes": int(body.bone_map_size_bytes),
			"staged_bone_map_sha256": str(body.staged_bone_map_sha256),
			"staged_bone_map_size_bytes": int(body.staged_bone_map_size_bytes),
		})
		for semantic in semantics:
			var scene := load(body_path) as PackedScene
			if scene == null:
				_fail("body payload did not import as PackedScene: %s" % body_id)
				return
			var instance := scene.instantiate()
			var body_root := instance as Node3D
			if body_root == null:
				_fail("body payload root is not Node3D: %s" % body_id)
				return
			if not _sanitize_imported_body(body_root):
				_fail("body contains unsupported presentation/control nodes: %s" % body_id)
				return
			body_root.name = "Body"
			world.add_child(body_root)
			body_root.position = Vector3.ZERO
			var skeleton := _find_skeleton(body_root)
			if (
				skeleton == null
				or skeleton.name != "GeneralSkeleton"
				or not _has_expected_bones(skeleton)
			):
				_fail("body does not expose the exact humanoid review skeleton: %s" % body_id)
				return
			skeleton.unique_name_in_owner = true
			_apply_neutral_material(body_root)
			var player := AnimationPlayer.new()
			player.name = "CaptureAnimationPlayer"
			world.add_child(player)
			player.root_node = player.get_path_to(body_root)
			if player.add_animation_library("", library) != OK:
				_fail("could not attach animation library to review body")
				return
			var animation := library.get_animation(str(semantic))
			var sheet := Image.create(phase_size.x * grid.x, phase_size.y * grid.y, false, Image.FORMAT_RGBA8)
			for phase_index in phases.size():
				var phase := float(phases[phase_index])
				player.play(str(semantic))
				player.seek(animation.length * phase, true)
				player.advance(0.0)
				await process_frame
				await RenderingServer.frame_post_draw
				var frame := viewport.get_texture().get_image()
				if frame == null or frame.is_empty() or frame.get_size() != phase_size:
					_fail("Godot produced an invalid fixed-phase frame")
					return
				var tile := Vector2i(phase_index % grid.x, phase_index / grid.x)
				var tile_origin := tile * phase_size
				sheet.blit_rect(frame, Rect2i(Vector2i.ZERO, phase_size), tile_origin)
				sheet.fill_rect(Rect2i(tile_origin, Vector2i(phase_size.x, 3)), Color.WHITE)
				sheet.fill_rect(Rect2i(tile_origin, Vector2i(3, phase_size.y)), Color.WHITE)
			var filename := "%s--%s.png" % [str(semantic), body_id]
			var relative := "cells/%s" % filename
			var evidence_path := "res://output/%s" % relative
			if sheet.save_png(evidence_path) != OK:
				_fail("could not save visual capture contact sheet")
				return
			var facts: Dictionary = root_facts[str(semantic)]
			cells.append({
				"semantic": str(semantic),
				"body_id": body_id,
				"observed_phases": phases,
				"evidence": {
					"path": relative,
					"sha256": FileAccess.get_sha256(evidence_path),
					"size_bytes": FileAccess.get_file_as_bytes(evidence_path).size(),
				},
				"horizontal_root_motion_span_x": facts.span_x,
				"horizontal_root_motion_span_z": facts.span_z,
				"horizontal_root_motion_initial_offset_x": facts.initial_offset_x,
				"horizontal_root_motion_initial_offset_z": facts.initial_offset_z,
				"horizontal_root_motion_max_delta_from_first": facts.max_delta_from_first,
				"camera_follow_enabled": false,
				"per_phase_reframing": false,
			})
			player.queue_free()
			body_root.queue_free()
			await process_frame
	var report := {
		"schema_version": "vandrel_foundry_animation_visual_capture_result/1.0",
		"animation_library_sha256": str(runtime.animation_library_sha256),
		"technical_report_sha256": str(runtime.technical_report_sha256),
		"selected_semantics": semantics,
		"bodies": body_bindings,
		"camera_policy": str(runtime.camera_policy),
		"camera_config_sha256": str(runtime.camera_config_sha256),
		"observed_phases": phases,
		"camera_follow_enabled": false,
		"per_phase_reframing": false,
		"anatomy_acceptance": "not_assessed",
		"cells": cells,
		"capture_passed": true,
	}
	var report_file := FileAccess.open(REPORT_PATH, FileAccess.WRITE)
	if report_file == null:
		_fail("could not create visual capture report")
		return
	report_file.store_string(JSON.stringify(report, "  ") + "\n")
	report_file.close()
	print("FOUNDRY_ANIMATION_VISUAL_CAPTURE_OK cells=%d" % cells.size())
	quit(0)


func _build_world(world: Node3D, config: Dictionary) -> void:
	var environment_node := WorldEnvironment.new()
	var environment := Environment.new()
	environment.background_mode = Environment.BG_COLOR
	environment.background_color = Color(0.16, 0.18, 0.2, 1.0)
	environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	environment.ambient_light_color = Color.WHITE
	environment.ambient_light_energy = 0.75
	environment_node.environment = environment
	world.add_child(environment_node)
	for rotation in [Vector3(-0.65, -0.6, 0.0), Vector3(-0.35, 2.35, 0.0)]:
		var light := DirectionalLight3D.new()
		light.rotation = rotation
		light.light_energy = 1.15
		world.add_child(light)
	_build_fixed_ground_grid(world)
	var camera := Camera3D.new()
	camera.position = _vector3(config.position)
	camera.fov = float(config.fov_degrees)
	camera.current = true
	world.add_child(camera)
	camera.look_at(_vector3(config.target), _vector3(config.up))


func _horizontal_root_facts(animation: Animation) -> Dictionary:
	if animation == null:
		return {"passed": false}
	var track_index := -1
	for index in animation.get_track_count():
		if (
			animation.track_get_type(index) == Animation.TYPE_POSITION_3D
			and str(animation.track_get_path(index)) == "%GeneralSkeleton:Hips"
		):
			if track_index != -1:
				return {"passed": false}
			track_index = index
	if track_index == -1 or animation.track_get_key_count(track_index) < 1:
		return {"passed": false}
	var min_x := INF
	var max_x := -INF
	var min_z := INF
	var max_z := -INF
	var initial_x := 0.0
	var initial_z := 0.0
	var max_delta_from_first := 0.0
	for key_index in animation.track_get_key_count(track_index):
		var value = animation.track_get_key_value(track_index, key_index)
		if not value is Vector3 or not value.is_finite():
			return {"passed": false}
		if key_index == 0:
			initial_x = value.x
			initial_z = value.z
		min_x = min(min_x, value.x)
		max_x = max(max_x, value.x)
		min_z = min(min_z, value.z)
		max_z = max(max_z, value.z)
		max_delta_from_first = max(
			max_delta_from_first,
			Vector2(value.x - initial_x, value.z - initial_z).length()
		)
	var span_x := max_x - min_x
	var span_z := max_z - min_z
	return {
		"span_x": span_x,
		"span_z": span_z,
		"initial_offset_x": initial_x,
		"initial_offset_z": initial_z,
		"max_delta_from_first": max_delta_from_first,
		"passed": max(max(span_x, span_z), max_delta_from_first) <= 0.0001,
	}


func _build_fixed_ground_grid(world: Node3D) -> void:
	var ground := MeshInstance3D.new()
	var plane := PlaneMesh.new()
	plane.size = Vector2(8.0, 8.0)
	ground.mesh = plane
	var ground_material := StandardMaterial3D.new()
	ground_material.albedo_color = Color(0.22, 0.24, 0.25, 1.0)
	ground_material.roughness = 1.0
	ground.material_override = ground_material
	world.add_child(ground)
	var line_material := StandardMaterial3D.new()
	line_material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	line_material.albedo_color = Color(0.58, 0.62, 0.64, 1.0)
	for index in range(-4, 5):
		var lines := ImmediateMesh.new()
		lines.surface_begin(Mesh.PRIMITIVE_LINES, line_material)
		lines.surface_add_vertex(Vector3(float(index), 0.003, -4.0))
		lines.surface_add_vertex(Vector3(float(index), 0.003, 4.0))
		lines.surface_add_vertex(Vector3(-4.0, 0.003, float(index)))
		lines.surface_add_vertex(Vector3(4.0, 0.003, float(index)))
		lines.surface_end()
		var grid_lines := MeshInstance3D.new()
		grid_lines.mesh = lines
		world.add_child(grid_lines)


func _find_skeleton(node: Node) -> Skeleton3D:
	if node is Skeleton3D:
		return node
	for child in node.get_children():
		var found := _find_skeleton(child)
		if found != null:
			return found
	return null


func _has_expected_bones(skeleton: Skeleton3D) -> bool:
	for bone in EXPECTED_BONES:
		if skeleton.find_bone(bone) < 0:
			return false
	return true


func _apply_neutral_material(node: Node) -> void:
	if node is MeshInstance3D:
		var material := StandardMaterial3D.new()
		material.albedo_color = Color(0.62, 0.58, 0.52, 1.0)
		material.roughness = 0.82
		(node as MeshInstance3D).material_override = material
	for child in node.get_children():
		_apply_neutral_material(child)


func _sanitize_imported_body(node: Node) -> bool:
	if not _is_passive_body_node(node):
		return false
	node.set_script(null)
	for child in node.get_children():
		if (
			child is Camera3D
			or child is WorldEnvironment
			or child is Light3D
			or child is AnimationTree
			or child is AnimationPlayer
		):
			node.remove_child(child)
			child.free()
		else:
			if not _sanitize_imported_body(child):
				return false
	return true


func _is_passive_body_node(node: Node) -> bool:
	return (
		node.get_class() == "Node3D"
		or node is MeshInstance3D
		or node is Skeleton3D
		or node is BoneAttachment3D
	)


func _vector3(value: Array) -> Vector3:
	if value.size() != 3:
		return Vector3(INF, INF, INF)
	return Vector3(float(value[0]), float(value[1]), float(value[2]))


func _read_json(path: String) -> Dictionary:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return {}
	var value = JSON.parse_string(file.get_as_text())
	return value if value is Dictionary else {}


func _fail(message: String) -> void:
	push_error(message)
	quit(1)
