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
    skinned_meshes = [
        item for item in meshes if any(modifier.type == "ARMATURE" for modifier in item.modifiers)
    ]
    framed_meshes = skinned_meshes or meshes

    corners = [
        item.matrix_world @ Vector(corner) for item in framed_meshes for corner in item.bound_box
    ]
    minimum = Vector(tuple(min(point[index] for point in corners) for index in range(3)))
    maximum = Vector(tuple(max(point[index] for point in corners) for index in range(3)))
    center = (minimum + maximum) / 2
    extent = max(maximum - minimum)
    if extent <= 0:
        raise RuntimeError("Imported GLB has zero-size bounds.")

    asset_minimum = minimum.copy()
    asset_maximum = maximum.copy()
    asset_dimensions = maximum - minimum

    reference_material = bpy.data.materials.new("Foundry Scale Reference")
    reference_material.diffuse_color = (0.18, 0.55, 0.95, 1.0)
    reference_x = maximum.x + max(asset_dimensions.x * 0.2, 0.35)
    reference_y = center.y
    ground_z = minimum.z
    bpy.ops.mesh.primitive_cube_add(
        size=1.0, location=(reference_x + 0.5, reference_y, ground_z + 0.5)
    )
    meter_cube = bpy.context.object
    meter_cube.name = "Foundry 1 Meter Cube"
    meter_cube.data.materials.append(reference_material)
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=16,
        radius=0.18,
        depth=1.36,
        location=(reference_x - 0.35, reference_y, ground_z + 0.68),
    )
    human_body = bpy.context.object
    human_body.name = "Foundry 1.8 Meter Human Body"
    human_body.data.materials.append(reference_material)
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=16,
        ring_count=8,
        radius=0.22,
        location=(reference_x - 0.35, reference_y, ground_z + 1.58),
    )
    human_head = bpy.context.object
    human_head.name = "Foundry 1.8 Meter Human Head"
    human_head.data.materials.append(reference_material)
    reference_objects = [meter_cube, human_body, human_head]
    framing_corners = corners + [
        item.matrix_world @ Vector(corner)
        for item in reference_objects
        for corner in item.bound_box
    ]
    minimum = Vector(tuple(min(point[index] for point in framing_corners) for index in range(3)))
    maximum = Vector(tuple(max(point[index] for point in framing_corners) for index in range(3)))
    center = (minimum + maximum) / 2
    extent = max(maximum - minimum)
    camera_data = bpy.data.cameras.new("Foundry Preview Camera")
    camera_data.clip_start = max(extent / 1000, 0.000001)
    camera_data.clip_end = max(extent * 100, 1.0)
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
        light_data.energy = max(energy * extent * extent, 0.01)
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
                "framed_mesh_objects": len(framed_meshes),
                "excluded_helper_meshes": len(meshes) - len(framed_meshes),
                "transparent_background": True,
                "geometry_bounds": {
                    "minimum": list(asset_minimum),
                    "maximum": list(asset_maximum),
                    "dimensions": list(asset_dimensions),
                    "height_axis": "z",
                    "scale_reference": {"meter_cube": 1.0, "human_height_meters": 1.8},
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
