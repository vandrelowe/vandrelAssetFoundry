@tool
extends SceneTree

const LIBRARY_PATH := "res://output/animation_library.res"
const REQUEST_PATH := "res://animation-library-runtime.json"
const REPORT_PATH := "res://output/animation-library-isolation.json"


func _init() -> void:
	if DirAccess.dir_exists_absolute("res://sources") or DirAccess.dir_exists_absolute("res://.godot/imported"):
		_fail("source FBXs or prior import cache remain during isolated validation")
		return
	var dependencies := ResourceLoader.get_dependencies(LIBRARY_PATH)
	if not dependencies.is_empty():
		_fail("finished AnimationLibrary has external dependencies: %s" % dependencies)
		return
	var library := load(LIBRARY_PATH) as AnimationLibrary
	var request := _read_json(REQUEST_PATH)
	if library == null or request.is_empty():
		_fail("isolated AnimationLibrary or request is unavailable")
		return
	var expected: Array[String] = []
	for motion in request.get("motions", []):
		expected.append(str(motion.get("semantic", "")))
	var actual: Array[String] = []
	for animation_name in library.get_animation_list():
		actual.append(str(animation_name))
	if actual != expected:
		_fail("isolated AnimationLibrary membership differs from request: expected=%s actual=%s" % [expected, actual])
		return
	var report := {
		"schema_version": "vandrel_foundry_animation_library_isolation/1.0",
		"animation_library_sha256": FileAccess.get_sha256(LIBRARY_PATH),
		"selected_semantics": expected,
		"external_dependencies": [],
		"source_fbx_directory_present": false,
		"prior_import_cache_present": false,
		"passed": true,
	}
	var file := FileAccess.open(REPORT_PATH, FileAccess.WRITE)
	if file == null:
		_fail("could not write isolation report")
		return
	file.store_string(JSON.stringify(report, "  ") + "\n")
	file.close()
	print("FOUNDRY_ANIMATION_LIBRARY_ISOLATION_OK")
	quit(0)


func _read_json(path: String) -> Dictionary:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return {}
	var value = JSON.parse_string(file.get_as_text())
	return value if value is Dictionary else {}


func _fail(message: String) -> void:
	push_error(message)
	quit(1)
