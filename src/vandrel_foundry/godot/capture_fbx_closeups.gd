extends SceneTree


func _initialize() -> void:
	call_deferred("_capture")


func _capture() -> void:
	var arguments := OS.get_cmdline_user_args()
	if arguments.size() != 1:
		push_error("Expected one absolute output directory.")
		quit(2)
		return
	var output_directory: String = arguments[0]
	DirAccess.make_dir_recursive_absolute(output_directory)
	var packed := load("res://model.fbx") as PackedScene
	if packed == null:
		push_error("Could not load exact FBX scene.")
		quit(3)
		return
	var subject := packed.instantiate()
	root.add_child(subject)
	var bounds := _visual_bounds(subject)
	if bounds.size.length_squared() <= 0.0:
		push_error("Imported FBX has no visible bounds.")
		quit(4)
		return
	var environment := WorldEnvironment.new()
	var environment_resource := Environment.new()
	environment_resource.background_mode = Environment.BG_COLOR
	environment_resource.background_color = Color(0.18, 0.20, 0.22)
	environment_resource.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	environment_resource.ambient_light_color = Color.WHITE
	environment_resource.ambient_light_energy = 0.65
	environment.environment = environment_resource
	root.add_child(environment)
	var light := DirectionalLight3D.new()
	light.rotation_degrees = Vector3(-35.0, -25.0, 0.0)
	light.light_energy = 1.5
	root.add_child(light)
	var camera := Camera3D.new()
	camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	camera.near = 0.001
	camera.far = maxf(bounds.size.y * 100.0, 100.0)
	camera.size = 0.8
	root.add_child(camera)
	camera.current = true
	var target := Vector3(0.0, 1.35, 0.0)
	var distance := 5.0
	for view in [
		{"name": "front", "direction": Vector3(0.0, 0.0, 1.0)},
		{"name": "right", "direction": Vector3(1.0, 0.0, 0.0)},
	]:
		camera.global_position = target + view.direction * distance
		camera.look_at(target, Vector3.UP)
		await process_frame
		await process_frame
		await RenderingServer.frame_post_draw
		var image := root.get_texture().get_image()
		var result := image.save_png(output_directory.path_join(
			"godot_material_close_%s.png" % view.name
		))
		if result != OK:
			push_error("Could not save Godot closeup.")
			quit(5)
			return
	quit()


func _visual_bounds(node: Node) -> AABB:
	var found := false
	var result := AABB()
	for descendant in node.find_children("*", "MeshInstance3D", true, false):
		var mesh_instance := descendant as MeshInstance3D
		if mesh_instance.mesh == null or not mesh_instance.visible:
			continue
		var transformed := mesh_instance.global_transform * mesh_instance.get_aabb()
		if found:
			result = result.merge(transformed)
		else:
			result = transformed
			found = true
	return result
