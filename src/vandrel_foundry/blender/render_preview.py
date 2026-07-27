"""Executed inside Blender; arguments follow a ``--`` separator."""

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def main() -> None:
    arguments = sys.argv[sys.argv.index("--") + 1 :]
    if len(arguments) != 3:
        raise RuntimeError("Expected input GLB, output PNG, and report JSON paths.")
    input_path, output_path, report_path = map(Path, arguments)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(input_path))
    meshes = [item for item in bpy.context.scene.objects if item.type == "MESH"]
    if not meshes:
        raise RuntimeError("Imported GLB contains no mesh objects.")

    corners = [item.matrix_world @ Vector(corner) for item in meshes for corner in item.bound_box]
    minimum = Vector(tuple(min(point[index] for point in corners) for index in range(3)))
    maximum = Vector(tuple(max(point[index] for point in corners) for index in range(3)))
    center = (minimum + maximum) / 2
    extent = max(maximum - minimum)
    if extent <= 0:
        raise RuntimeError("Imported GLB has zero-size bounds.")

    camera_data = bpy.data.cameras.new("Foundry Preview Camera")
    camera = bpy.data.objects.new("Foundry Preview Camera", camera_data)
    bpy.context.scene.collection.objects.link(camera)
    direction = Vector((1.4, -1.4, 1.0)).normalized()
    camera.location = center + direction * (extent / math.tan(camera_data.angle / 2) * 1.35)
    camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = camera

    for name, location, energy in (
        ("Key", center + Vector((extent * 2, -extent * 2, extent * 3)), 1200),
        ("Fill", center + Vector((-extent * 2, -extent, extent)), 600),
    ):
        light_data = bpy.data.lights.new(name, "AREA")
        light_data.energy = energy
        light_data.shape = "DISK"
        light_data.size = extent * 2
        light = bpy.data.objects.new(name, light_data)
        light.location = location
        light.rotation_euler = (center - location).to_track_quat("-Z", "Y").to_euler()
        bpy.context.scene.collection.objects.link(light)

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 512
    scene.render.resolution_y = 512
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = True
    scene.render.filepath = str(output_path)
    bpy.ops.render.render(write_still=True)
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "blender_version": bpy.app.version_string,
                "resolution": [512, 512],
                "mesh_objects": len(meshes),
                "transparent_background": True,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
