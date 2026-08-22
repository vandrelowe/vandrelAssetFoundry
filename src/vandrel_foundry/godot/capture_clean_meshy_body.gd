extends SceneTree

const WIDTH := 1280
const HEIGHT := 720
const PHASES := [0.0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875]

var viewport: SubViewport
var body: Node3D
var player: AnimationPlayer
var camera: Camera3D
var runtime: Dictionary

func _initialize() -> void: call_deferred("_run")

func _run() -> void:
	runtime = JSON.parse_string(FileAccess.get_file_as_string("res://runtime.json"))
	var packed := load("res://input/body.gltf") as PackedScene
	var library := load("res://input/shared_animation_library.res") as AnimationLibrary
	if packed == null or library == null: _fail("Capture inputs are unavailable."); return
	viewport = SubViewport.new(); viewport.size = Vector2i(WIDTH, HEIGHT); viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS; viewport.transparent_bg = false; get_root().add_child(viewport)
	var world := WorldEnvironment.new(); var env := Environment.new(); env.background_mode = Environment.BG_COLOR; env.background_color = Color(0.08,0.075,0.065); env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR; env.ambient_light_color = Color(0.65,0.68,0.7); env.ambient_light_energy = 0.55; world.environment = env; viewport.add_child(world)
	var light := DirectionalLight3D.new(); light.rotation_degrees = Vector3(-48,-28,0); light.shadow_enabled = true; viewport.add_child(light)
	var ground := MeshInstance3D.new(); var plane := PlaneMesh.new(); plane.size = Vector2(6,6); ground.mesh = plane; ground.position.y = -0.002; ground.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_ON; viewport.add_child(ground)
	body = packed.instantiate() as Node3D
	if body == null: _fail("Imported body root is not Node3D."); return
	_sanitize(body); viewport.add_child(body)
	player = AnimationPlayer.new(); body.add_child(player); player.add_animation_library(&"", library)
	camera = Camera3D.new(); camera.fov = 38.0; camera.position = Vector3(0,0.9,4.8); camera.look_at(Vector3(0,0.95,0), Vector3.UP); viewport.add_child(camera)
	var cells: Array[Dictionary] = []
	for view in ["front","side","back"]:
		body.rotation_degrees.y = 0.0 if view == "front" else (-90.0 if view == "side" else 180.0)
		player.stop()
		await RenderingServer.frame_post_draw
		cells.append(_save_cell("rest_" + view + ".png", "rest", view, []))
	body.rotation_degrees.y = 0.0
	for semantic_value in runtime.shared_semantics:
		var semantic := str(semantic_value); var animation := library.get_animation(semantic)
		if animation == null: _fail("Shared semantic is missing: " + semantic); return
		var sheet := Image.create(WIDTH * 4, HEIGHT * 2, false, Image.FORMAT_RGBA8)
		for index in range(PHASES.size()):
			player.play(StringName(semantic)); player.seek(animation.length * PHASES[index], true); player.pause()
			await RenderingServer.frame_post_draw
			var frame := viewport.get_texture().get_image()
			sheet.blit_rect(frame, Rect2i(0,0,WIDTH,HEIGHT), Vector2i((index % 4)*WIDTH,(index >> 2)*HEIGHT))
		var path := "res://output/motion_" + semantic + ".png"
		if sheet.save_png(path) != OK:
			_fail("Cannot save motion sheet.")
			return
		cells.append(_cell(path, "motion", semantic, PHASES))
	var manifest := {"schema_version":"vandrel_foundry_clean_body_capture/1.0","processed_body_sha256":runtime.processed_body_sha256,"shared_animation_library_sha256":runtime.shared_animation_library.sha256,"shared_animation_library_descriptor_sha256":runtime.shared_animation_library.descriptor_sha256,"camera_policy":runtime.camera_policy,"camera_config_sha256":runtime.camera_config_sha256,"review_status":"manual_review_required","manual_result":null,"cells":cells}
	_write_json("res://output/clean-body-capture-manifest.json", manifest); quit(0)

func _save_cell(name: String, kind: String, label: String, phases: Array) -> Dictionary:
	var path := "res://output/" + name
	var image := viewport.get_texture().get_image()
	if image.save_png(path) != OK: _fail("Cannot save rest evidence."); return {}
	return _cell(path, kind, label, phases)

func _cell(path: String, kind: String, label: String, phases: Array) -> Dictionary:
	var absolute := ProjectSettings.globalize_path(path)
	return {"kind":kind,"label":label,"phases":phases,"path":path.get_file(),"sha256":FileAccess.get_sha256(absolute),"size_bytes":FileAccess.get_size(absolute),"result":null}

func _sanitize(node: Node) -> void:
	for child in node.get_children():
		if child is Camera3D or child is WorldEnvironment or child is Light3D or child is AnimationPlayer or child is AnimationTree:
			child.free()
		else: _sanitize(child)

func _write_json(path: String, value: Dictionary) -> void:
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null: _fail("Cannot write capture manifest."); return
	file.store_string(JSON.stringify(value,"  ")+"\n"); file.flush()

func _fail(message: String) -> void: push_error(message); quit(1)
