extends Node3D

var pivot := Node3D.new()
var model_root := Node3D.new()
var camera := Camera3D.new()
var model_menu := OptionButton.new()
var animation_menu := OptionButton.new()
var play_button := Button.new()
var status := Label.new()
var models: Array = []
var animation_player: AnimationPlayer
var yaw := 0.7
var pitch := -0.25
var distance := 5.0
var focus_y := 0.8


func _ready() -> void:
	_build_world()
	_build_ui()
	_load_catalog()
	_update_camera()


func _build_world() -> void:
	add_child(pivot)
	pivot.add_child(model_root)
	add_child(camera)
	camera.current = true
	var environment := WorldEnvironment.new()
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color("26313a")
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color.WHITE
	env.ambient_light_energy = 0.65
	environment.environment = env
	add_child(environment)
	for rotation in [Vector3(-0.8, -0.6, 0.0), Vector3(-0.45, 2.2, 0.0)]:
		var light := DirectionalLight3D.new()
		light.rotation = rotation
		light.light_energy = 1.2
		add_child(light)
	_build_grid()
	_build_scale_references()


func _build_grid() -> void:
	var material := StandardMaterial3D.new()
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	material.albedo_color = Color(0.48, 0.55, 0.6, 0.42)
	for index in range(-10, 11):
		_add_line(Vector3(index, 0, -10), Vector3(index, 0, 10), material)
		_add_line(Vector3(-10, 0, index), Vector3(10, 0, index), material)


func _add_line(start: Vector3, end: Vector3, material: Material) -> void:
	var mesh := ImmediateMesh.new()
	mesh.surface_begin(Mesh.PRIMITIVE_LINES, material)
	mesh.surface_add_vertex(start)
	mesh.surface_add_vertex(end)
	mesh.surface_end()
	var instance := MeshInstance3D.new()
	instance.mesh = mesh
	add_child(instance)


func _build_scale_references() -> void:
	var meter := MeshInstance3D.new()
	var box := BoxMesh.new()
	box.size = Vector3.ONE
	meter.mesh = box
	meter.position = Vector3(-1.5, 0.5, 0)
	var meter_material := StandardMaterial3D.new()
	meter_material.albedo_color = Color(0.2, 0.65, 1.0, 0.25)
	meter_material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	meter.material_override = meter_material
	add_child(meter)
	var person := MeshInstance3D.new()
	var capsule := CapsuleMesh.new()
	capsule.height = 1.8
	capsule.radius = 0.22
	person.mesh = capsule
	person.position = Vector3(1.5, 0.9, 0)
	var person_material := StandardMaterial3D.new()
	person_material.albedo_color = Color(1.0, 0.65, 0.2, 0.55)
	person_material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	person.material_override = person_material
	add_child(person)


func _build_ui() -> void:
	var panel := VBoxContainer.new()
	panel.position = Vector2(16, 16)
	panel.size = Vector2(430, 190)
	add_child(panel)
	var title := Label.new()
	title.text = "Foundry package preview — visual evidence only"
	panel.add_child(title)
	panel.add_child(model_menu)
	panel.add_child(animation_menu)
	play_button.text = "Play / Pause"
	panel.add_child(play_button)
	status.text = "Drag to orbit • wheel to zoom • 1 grid cell = 1 metre"
	panel.add_child(status)
	model_menu.item_selected.connect(_select_model)
	animation_menu.item_selected.connect(_select_animation)
	play_button.pressed.connect(_toggle_play)


func _load_catalog() -> void:
	var file := FileAccess.open("res://preview_catalog.json", FileAccess.READ)
	if file == null:
		status.text = "Could not open preview catalog."
		return
	var parsed = JSON.parse_string(file.get_as_text())
	if not parsed is Dictionary or not parsed.has("models"):
		status.text = "Preview catalog is invalid."
		return
	models = parsed.models
	for path in models:
		model_menu.add_item(str(path).trim_prefix("package/"))
	if not models.is_empty():
		_select_model(0)


func _select_model(index: int) -> void:
	for child in model_root.get_children():
		child.queue_free()
	model_root.position = Vector3.ZERO
	animation_menu.clear()
	animation_player = null
	var resource = load("res://" + str(models[index]))
	if not resource is PackedScene:
		status.text = "Godot could not import this model as a scene."
		return
	var instance: Node = resource.instantiate()
	model_root.add_child(instance)
	animation_player = _find_animation_player(instance)
	if animation_player != null:
		for library_name in animation_player.get_animation_library_list():
			var library := animation_player.get_animation_library(library_name)
			for animation_name in library.get_animation_list():
				animation_menu.add_item(str(library_name) + "/" + str(animation_name))
	status.text = "%s • %d animation(s)" % [str(models[index]), animation_menu.item_count]
	_frame_model.call_deferred(instance)


func _frame_model(instance: Node) -> void:
	var bounds := _find_bounds(instance, Transform3D.IDENTITY)
	if bounds.size.length_squared() > 0.000001:
		model_root.position = Vector3(-bounds.get_center().x, -bounds.position.y, -bounds.get_center().z)
		focus_y = max(bounds.size.y * 0.5, 0.8)
		distance = max(max(bounds.size.x, bounds.size.y, bounds.size.z) * 2.2, 2.5)
		camera.far = max(1000.0, distance * 4.0)
		_update_camera()
	var meshes := _count_meshes(instance)
	print(
		"FOUNDRY_PREVIEW_READY models=%d selected=%s meshes=%d animations=%d"
		% [models.size(), str(models[model_menu.selected]), meshes, animation_menu.item_count]
	)


func _find_bounds(node: Node, parent_transform: Transform3D) -> AABB:
	var transform := parent_transform
	if node is Node3D:
		transform = parent_transform * (node as Node3D).transform
	var bounds := AABB()
	if node is MeshInstance3D and (node as MeshInstance3D).mesh != null:
		bounds = transform * (node as MeshInstance3D).get_aabb()
	for child in node.get_children():
		var child_bounds := _find_bounds(child, transform)
		if child_bounds.size.length_squared() > 0.000001:
			bounds = child_bounds if bounds.size.length_squared() <= 0.000001 else bounds.merge(child_bounds)
	return bounds


func _count_meshes(node: Node) -> int:
	var count := 1 if node is MeshInstance3D and (node as MeshInstance3D).mesh != null else 0
	for child in node.get_children():
		count += _count_meshes(child)
	return count


func _find_animation_player(node: Node) -> AnimationPlayer:
	if node is AnimationPlayer:
		return node
	for child in node.get_children():
		var found := _find_animation_player(child)
		if found != null:
			return found
	return null


func _select_animation(index: int) -> void:
	if animation_player == null:
		return
	var parts := animation_menu.get_item_text(index).split("/", true, 1)
	var key := parts[0] + "/" + parts[1] if parts[0] != "" else parts[1]
	animation_player.play(key)


func _toggle_play() -> void:
	if animation_player == null:
		return
	if animation_player.is_playing():
		animation_player.pause()
	elif animation_menu.item_count > 0:
		_select_animation(animation_menu.selected)


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseMotion and event.button_mask & MOUSE_BUTTON_MASK_LEFT:
		yaw -= event.relative.x * 0.008
		pitch = clamp(pitch - event.relative.y * 0.008, -1.35, 1.35)
		_update_camera()
	elif event is InputEventMouseButton and event.pressed:
		if event.button_index == MOUSE_BUTTON_WHEEL_UP:
			distance = max(1.0, distance * 0.88)
		elif event.button_index == MOUSE_BUTTON_WHEEL_DOWN:
			distance = min(40.0, distance * 1.14)
		_update_camera()


func _update_camera() -> void:
	camera.position = Vector3(
		distance * cos(pitch) * sin(yaw),
		focus_y + distance * sin(-pitch),
		distance * cos(pitch) * cos(yaw)
	)
	camera.look_at(Vector3(0, focus_y, 0), Vector3.UP)
