"""Render neutral-gray continuous evidence for every Meshy-native canary action."""

import json
import math
import re
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def main() -> None:
    values = sys.argv[sys.argv.index("--") + 1 :]
    render_profile = "standard"
    if values and values[-1].startswith("profile="):
        render_profile = values.pop().split("=", 1)[1]
    if render_profile not in {"standard", "repair_comparison"}:
        raise RuntimeError("Unsupported Meshy native playback render profile.")
    if len(values) not in {4, 5}:
        raise RuntimeError(
            "Expected input model, output directory, report JSON, bound durations JSON, "
            "and optional target-action GLB."
        )
    source, output, report, durations_path = map(Path, values[:4])
    target_action_source = Path(values[4]) if len(values) == 5 else None
    expected_durations = json.loads(durations_path.read_text(encoding="utf-8"))
    if (
        not isinstance(expected_durations, dict)
        or not expected_durations
        or any(
            not isinstance(name, str)
            or isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or float(duration) <= 0
            for name, duration in expected_durations.items()
        )
    ):
        raise RuntimeError("Bound Meshy native clip durations are invalid.")
    output.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = 30
    scene.render.fps_base = 1.0
    if target_action_source is None:
        bpy.ops.import_scene.gltf(filepath=str(source))
        source_mode = "glb"
    else:
        bpy.ops.import_scene.fbx(filepath=str(source), use_anim=True)
        source_mode = "provider_fbx_with_target_actions"
    armatures = [item for item in scene.objects if item.type == "ARMATURE"]
    if len(armatures) != 1:
        raise RuntimeError("Meshy native playback requires exactly one armature.")
    armature = armatures[0]
    meshes = [
        item
        for item in scene.objects
        if item.type == "MESH"
        and any(mod.type == "ARMATURE" and mod.object == armature for mod in item.modifiers)
    ]
    if target_action_source is not None:
        for action in list(bpy.data.actions):
            bpy.data.actions.remove(action)
        existing_objects = set(scene.objects)
        bpy.ops.import_scene.gltf(filepath=str(target_action_source))
        action_objects = [item for item in scene.objects if item not in existing_objects]
        imported_actions = list(bpy.data.actions)
        for action in imported_actions:
            action.use_fake_user = True
        for item in action_objects:
            bpy.data.objects.remove(item, do_unlink=True)
    else:
        imported_actions = list(bpy.data.actions)
    by_name = {action.name: action for action in imported_actions}
    if not meshes or len(by_name) != len(imported_actions):
        raise RuntimeError("Meshy native playback requires skinned geometry and unique actions.")
    missing = [name for name in expected_durations if name not in by_name]
    if missing:
        raise RuntimeError(f"Imported model is missing bound playback actions: {missing}.")
    actions = [by_name[name] for name in expected_durations]

    camera_data = bpy.data.cameras.new("MeshyNativePlaybackCamera")
    camera = bpy.data.objects.new("MeshyNativePlaybackCamera", camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "SINGLE"
    scene.display.shading.single_color = (0.62, 0.62, 0.62)
    scene.display.shading.background_type = "WORLD"
    if scene.world is None:
        scene.world = bpy.data.worlds.new("MeshyNativePlaybackWorld")
    scene.world.color = (0.0, 0.0, 0.0)
    scene.render.resolution_x = 768 if render_profile == "repair_comparison" else 384
    scene.render.resolution_y = 768 if render_profile == "repair_comparison" else 384
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    armature.animation_data_create()
    clips = []
    for action in actions:
        armature.animation_data.action = action
        source_start = float(action.frame_range[0])
        source_end = float(action.frame_range[1])
        source_duration = (source_end - source_start) / float(scene.render.fps)
        bound_duration = float(expected_durations[action.name])
        if abs(source_duration - bound_duration) > 0.002:
            raise RuntimeError(
                f"Imported clip duration changed for {action.name}: "
                f"{source_duration} != {bound_duration}."
            )
        start = math.floor(source_start)
        end = max(start, math.ceil(source_end))
        maximum_samples = 24 if render_profile == "repair_comparison" else 72
        step = max(1, math.ceil((end - start + 1) / maximum_samples))
        frames = list(range(start, end + 1, step))
        if frames[-1] != end:
            frames.append(end)
        bounds = []
        ground = []
        for frame in frames:
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            minimum, maximum = _bounds(meshes)
            bounds.extend((minimum, maximum))
            ground.append(float(minimum.z))
        minimum = Vector(tuple(min(point[index] for point in bounds) for index in range(3)))
        maximum = Vector(tuple(max(point[index] for point in bounds) for index in range(3)))
        center = (minimum + maximum) / 2
        extent = max(maximum - minimum)
        if extent <= 0:
            raise RuntimeError(f"Meshy native playback has zero extent: {action.name}.")
        camera.location = center + Vector((1.6, -0.12, 0.28)).normalized() * (
            extent / math.tan(camera_data.angle / 2) * 1.45
        )
        camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
        camera_data.clip_start = max(extent / 1000, 0.000001)
        camera_data.clip_end = extent * 100
        directory = output / _slug(action.name)
        directory.mkdir()
        frame_files = []
        for index, frame in enumerate(frames):
            scene.frame_set(frame)
            destination = directory / f"{index:04d}.png"
            scene.render.filepath = str(destination)
            bpy.ops.render.render(write_still=True)
            frame_files.append(f"{directory.name}/{destination.name}")
        clips.append(
            {
                "exact_name": action.name,
                "frame_range": [start, end],
                "frame_step": step,
                "sampled_frame_count": len(frames),
                "frame_files": frame_files,
                "source_timebase_fps": scene.render.fps,
                "source_duration_seconds": source_duration,
                "bound_normalization_duration_seconds": bound_duration,
                "duration_delta_seconds": abs(source_duration - bound_duration),
                "bounds_min": list(minimum),
                "bounds_max": list(maximum),
                "sampled_ground_minimum_range": [min(ground), max(ground)],
            }
        )
    armature.animation_data.action = None
    report.write_text(
        json.dumps(
            {
                "schema": "vandrel_foundry_meshy_native_playback/1.0",
                "blender_version": bpy.app.version_string,
                "source_mode": source_mode,
                "render_profile": render_profile,
                "resolution": [scene.render.resolution_x, scene.render.resolution_y],
                "neutral_gray": True,
                "lateral_camera": True,
                "continuous_temporal_output": True,
                "clip_count": len(clips),
                "clips": clips,
                "review_scope": [
                    "all_selected_exact_actions",
                    "deformation",
                    "root_motion",
                    "ground_contact",
                    "locomotion_loop_closure",
                    "eating_and_butchery_semantic_fit",
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _bounds(meshes):
    graph = bpy.context.evaluated_depsgraph_get()
    points = []
    for item in meshes:
        evaluated = item.evaluated_get(graph)
        mesh = evaluated.to_mesh()
        try:
            points.extend(evaluated.matrix_world @ vertex.co for vertex in mesh.vertices)
        finally:
            evaluated.to_mesh_clear()
    if not points:
        raise RuntimeError("Meshy native playback has no evaluated vertices.")
    return (
        Vector(tuple(min(point[index] for point in points) for index in range(3))),
        Vector(tuple(max(point[index] for point in points) for index in range(3))),
    )


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


if __name__ == "__main__":
    main()
