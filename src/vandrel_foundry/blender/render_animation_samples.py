"""Executed inside Blender; arguments follow a ``--`` separator."""

import json
import math
import re
import sys
from pathlib import Path

import bpy
from mathutils import Vector

PREFERRED_CLIPS = (
    "Axe_Breathe_and_Look_Around",
    "Attack",
    "Running",
    "Walking",
    "Arise",
    "Archery_Shot",
)


def main() -> None:
    arguments = sys.argv[sys.argv.index("--") + 1 :]
    if len(arguments) != 3:
        raise RuntimeError("Expected input GLB, output directory, and report JSON.")
    input_path, output_directory, report_path = map(Path, arguments)
    output_directory.mkdir(parents=True, exist_ok=False)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = 30
    bpy.ops.import_scene.gltf(filepath=str(input_path))
    armatures = [item for item in scene.objects if item.type == "ARMATURE"]
    if len(armatures) != 1:
        raise RuntimeError(f"Expected one armature, found {len(armatures)}.")
    armature = armatures[0]
    meshes = [
        item
        for item in scene.objects
        if item.type == "MESH"
        and any(
            modifier.type == "ARMATURE" and modifier.object == armature
            for modifier in item.modifiers
        )
    ]
    if not meshes:
        raise RuntimeError("Animated preview input has no skinned mesh.")
    actions = _select_actions(list(bpy.data.actions))
    if not actions:
        raise RuntimeError("Animated preview input has no matching actions.")

    camera_data = bpy.data.cameras.new("Foundry Animation Camera")
    camera = bpy.data.objects.new("Foundry Animation Camera", camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    lights = []
    for name, energy in (("Key", 1200), ("Fill", 600)):
        light_data = bpy.data.lights.new(name, "AREA")
        light_data.energy = energy
        light_data.shape = "DISK"
        light = bpy.data.objects.new(name, light_data)
        scene.collection.objects.link(light)
        lights.append(light)

    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 384
    scene.render.resolution_y = 384
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = True
    armature.animation_data_create()
    samples = []

    for action in actions:
        armature.animation_data.action = action
        start = math.floor(action.frame_range[0] + 1e-4)
        end = max(start, math.ceil(action.frame_range[1] - 1e-4))
        frames = sorted({start, round((start + end) / 2), end})
        for frame in frames:
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            minimum, maximum = _deformed_bounds(meshes)
            center = (minimum + maximum) / 2
            extent = max(maximum - minimum)
            if extent <= 0:
                raise RuntimeError(f"Animation sample has zero-size bounds: {action.name}.")
            direction = Vector((1.4, -1.4, 0.8)).normalized()
            camera_data.clip_start = max(extent / 1000, 0.000001)
            camera_data.clip_end = max(extent * 100, 1.0)
            camera.location = center + direction * (
                extent / math.tan(camera_data.angle / 2) * 1.35
            )
            camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
            light_positions = (
                center + Vector((extent * 2, -extent * 2, extent * 3)),
                center + Vector((-extent * 2, -extent, extent)),
            )
            for light, location, energy in zip(lights, light_positions, (1200, 600)):
                light.data.energy = max(energy * extent * extent, 0.01)
                light.data.size = extent * 2
                light.location = location
                light.rotation_euler = (center - location).to_track_quat("-Z", "Y").to_euler()
            filename = f"{_slug(action.name)}-f{frame:04d}.png"
            scene.render.filepath = str(output_directory / filename)
            bpy.ops.render.render(write_still=True)
            samples.append(
                {
                    "animation": action.name,
                    "frame": frame,
                    "frame_range": [start, end],
                    "image": filename,
                    "bounds_min": list(minimum),
                    "bounds_max": list(maximum),
                    "bounds_extent": extent,
                }
            )

    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "blender_version": bpy.app.version_string,
                "resolution": [384, 384],
                "sample_count": len(samples),
                "selected_animation_count": len(actions),
                "samples": samples,
                "review_scope": [
                    "gross deformation",
                    "limb orientation",
                    "root displacement",
                    "foot contact",
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _select_actions(actions):
    selected = []
    for preferred in PREFERRED_CLIPS:
        match = next((action for action in actions if action.name.endswith(preferred)), None)
        if match is not None:
            selected.append(match)
    return selected


def _deformed_bounds(meshes) -> tuple[Vector, Vector]:
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
        raise RuntimeError("Animated preview has no evaluated vertices.")
    minimum = Vector(tuple(min(point[index] for point in points) for index in range(3)))
    maximum = Vector(tuple(max(point[index] for point in points) for index in range(3)))
    return minimum, maximum


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


if __name__ == "__main__":
    main()
