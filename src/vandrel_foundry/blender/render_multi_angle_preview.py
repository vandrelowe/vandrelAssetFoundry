"""Render four full-resolution inspection views inside Blender."""

import json
import math
import sys
from array import array
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).parent))
from preview_framing import fit_perspective_bounds

FRAME_LIMIT = 0.88
TARGET_ALPHA_SPAN = 0.82
ALPHA_CENTER_TOLERANCE = 0.03
MAX_ALPHA_CORRECTIONS = 2


def rendered_alpha_bounds(path: Path) -> tuple[int, int, int, int]:
    result = bpy.data.images.load(str(path), check_existing=False)
    width, height = result.size
    pixels = array("f", [0.0]) * (width * height * 4)
    result.pixels.foreach_get(pixels)
    visible = [index // 4 for index in range(3, len(pixels), 4) if pixels[index] > 0.0]
    try:
        if not visible:
            raise RuntimeError("Rendered preview has no nonzero alpha.")
        xs = [index % width for index in visible]
        ys = [index // width for index in visible]
        return min(xs), min(ys), max(xs) + 1, max(ys) + 1
    finally:
        bpy.data.images.remove(result)


def main() -> None:
    arguments = sys.argv[sys.argv.index("--") + 1 :]
    if len(arguments) != 3:
        raise RuntimeError("Expected input GLB, output directory, and report JSON.")
    input_path, output_dir, report_path = map(Path, arguments)
    output_dir.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(input_path))
    meshes = [item for item in bpy.context.scene.objects if item.type == "MESH"]
    if not meshes:
        raise RuntimeError("Imported GLB contains no mesh objects.")
    depsgraph = bpy.context.evaluated_depsgraph_get()
    geometry_points = []
    for item in meshes:
        evaluated = item.evaluated_get(depsgraph)
        evaluated_mesh = evaluated.to_mesh()
        try:
            geometry_points.extend(
                evaluated.matrix_world @ vertex.co for vertex in evaluated_mesh.vertices
            )
        finally:
            evaluated.to_mesh_clear()
    if not geometry_points:
        raise RuntimeError("Imported GLB contains no mesh vertices.")
    minimum = Vector(tuple(min(point[index] for point in geometry_points) for index in range(3)))
    maximum = Vector(tuple(max(point[index] for point in geometry_points) for index in range(3)))
    center = (minimum + maximum) / 2
    extent = max(maximum - minimum)
    if extent <= 0:
        raise RuntimeError("Imported GLB has zero-size bounds.")

    camera_data = bpy.data.cameras.new("Foundry Inspection Camera")
    camera_data.clip_start = max(extent / 1000, 0.000001)
    camera_data.clip_end = max(extent * 100, 1.0)
    camera = bpy.data.objects.new("Foundry Inspection Camera", camera_data)
    bpy.context.scene.collection.objects.link(camera)
    bpy.context.scene.camera = camera
    # Fill most of the frame while retaining margin for rectangular silhouettes.

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
    scene.render.resolution_x = 2048
    scene.render.resolution_y = 2048
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = True
    views = {
        "front": Vector((0, -1, 0.45)),
        "right": Vector((1, 0, 0.45)),
        "back": Vector((0, 1, 0.45)),
        "left": Vector((-1, 0, 0.45)),
    }
    outputs = []
    view_reports = []
    geometry_point_tuples = [tuple(point) for point in geometry_points]
    center_tuple = tuple(center)
    for name, direction in views.items():
        framing = fit_perspective_bounds(
            geometry_point_tuples,
            center_tuple,
            tuple(direction),
            camera_data.angle_x,
            camera_data.angle_y,
            FRAME_LIMIT,
        )
        target = center.copy()
        distance = framing.distance
        camera.location = target + direction.normalized() * distance
        camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
        output = output_dir / f"{name}.png"
        scene.render.filepath = str(output)
        bpy.ops.render.render(write_still=True)
        initial_alpha_bounds = rendered_alpha_bounds(output)
        corrections = 0
        for _ in range(MAX_ALPHA_CORRECTIONS):
            alpha_left, alpha_bottom, alpha_right, alpha_top = rendered_alpha_bounds(output)
            width = scene.render.resolution_x
            height = scene.render.resolution_y
            width_span = (alpha_right - alpha_left) / width
            height_span = (alpha_top - alpha_bottom) / height
            x_center = (alpha_left + alpha_right) / width - 1.0
            y_center = (alpha_bottom + alpha_top) / height - 1.0
            if (
                max(width_span, height_span) >= TARGET_ALPHA_SPAN
                and abs(x_center) <= ALPHA_CENTER_TOLERANCE
                and abs(y_center) <= ALPHA_CENTER_TOLERANCE
            ):
                break
            right_vector = Vector(framing.right)
            up_vector = Vector(framing.up)
            target += right_vector * (
                x_center * distance * math.tan(camera_data.angle_x / 2)
            ) + up_vector * (y_center * distance * math.tan(camera_data.angle_y / 2))
            distance *= max(width_span, height_span) / TARGET_ALPHA_SPAN
            camera.location = target + direction.normalized() * distance
            camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
            bpy.ops.render.render(write_still=True)
            corrections += 1
        final_alpha_bounds = rendered_alpha_bounds(output)
        outputs.append(output.name)
        left, right, bottom, top = framing.projected_bounds
        view_reports.append(
            {
                "name": name,
                "output": output.name,
                "camera_direction": list(direction.normalized()),
                "camera_location": list(camera.location),
                "camera_target": list(target),
                "camera_distance": distance,
                "initial_geometry_safe_distance": framing.distance,
                "angle_x_radians": camera_data.angle_x,
                "angle_y_radians": camera_data.angle_y,
                "frame_limit": FRAME_LIMIT,
                "initial_projected_ndc_bounds": [left, right, bottom, top],
                "initial_predicted_ndc_margins": [
                    left + 1.0,
                    1.0 - right,
                    bottom + 1.0,
                    1.0 - top,
                ],
                "initial_geometry_bounds_contained": all(
                    abs(value) <= FRAME_LIMIT + 1e-6 for value in (left, right, bottom, top)
                ),
                "alpha_corrections": corrections,
                "initial_alpha_bounds_pixels": list(initial_alpha_bounds),
                "final_alpha_bounds_pixels": list(final_alpha_bounds),
            }
        )
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "blender_version": bpy.app.version_string,
                "resolution": [2048, 2048],
                "views": outputs,
                "mesh_objects": len(meshes),
                "geometry_point_count": len(geometry_points),
                "transparent_background": True,
                "geometry_bounds": {
                    "minimum": list(minimum),
                    "maximum": list(maximum),
                    "center": list(center),
                    "size": list(maximum - minimum),
                },
                "camera_views": view_reports,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
