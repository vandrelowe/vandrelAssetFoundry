"""Executed inside Blender; arguments follow a ``--`` separator."""

import hashlib
import json
import sys
from pathlib import Path

import bmesh
import bpy

SOURCE_SHA256 = "15159e002557590ca22b82c8f38420837f0af99933d13d901c0226c6164236ff"
SOURCE_Y_CUTOFF = 0.58
GREEN_R_RATIO = 1.22
GREEN_B_RATIO = 1.15
GREEN_MINIMUM = 70 / 255
MIN_GREEN_SAMPLE_FRACTION = 0.50
MAX_FACE_EDGE = 0.14
TRANSFORMS = (
    {"translation": (-0.25, 0.00, -0.025), "scale": 0.78, "rotation_z": -0.16},
    {"translation": (0.25, 0.00, -0.020), "scale": 0.77, "rotation_z": 0.14},
    {"translation": (0.00, -0.25, -0.030), "scale": 0.76, "rotation_z": 0.08},
    {"translation": (0.00, 0.25, -0.018), "scale": 0.75, "rotation_z": -0.09},
)


def main() -> None:
    arguments = sys.argv[sys.argv.index("--") + 1 :]
    if len(arguments) != 3:
        raise RuntimeError("Expected input GLB, output GLB, and report JSON.")
    input_path, output_path, report_path = map(Path, arguments)
    if _sha256(input_path) != SOURCE_SHA256:
        raise RuntimeError("Input GLB does not match the accepted source hash.")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(input_path))
    meshes = [item for item in bpy.context.scene.objects if item.type == "MESH"]
    if len(meshes) != 1:
        raise RuntimeError(f"Expected exactly one source mesh; found {len(meshes)}.")
    source = meshes[0]
    image = _base_color_image(source)
    pixels = list(image.pixels)
    width, height = image.size
    uv_layer = source.data.uv_layers.active
    if uv_layer is None:
        raise RuntimeError("Source mesh has no active UV layer.")
    selected_indices: list[int] = []
    for polygon in source.data.polygons:
        centroid_z = sum(source.data.vertices[index].co.z for index in polygon.vertices) / len(
            polygon.vertices
        )
        loop_uvs = [uv_layer.data[index].uv for index in polygon.loop_indices]
        sample_uvs = [(uv.x, uv.y) for uv in loop_uvs]
        sample_uvs.append(
            (
                sum(uv.x for uv in loop_uvs) / polygon.loop_total,
                sum(uv.y for uv in loop_uvs) / polygon.loop_total,
            )
        )
        green_samples = sum(
            _is_green(_pixel(pixels, width, height, u, v)) for u, v in sample_uvs
        )
        vertices = [source.data.vertices[index].co for index in polygon.vertices]
        max_edge = max(
            (vertices[index] - vertices[(index + 1) % len(vertices)]).length
            for index in range(len(vertices))
        )
        selected_face = bool(
            centroid_z >= SOURCE_Y_CUTOFF
            and green_samples / len(sample_uvs) >= MIN_GREEN_SAMPLE_FRACTION
            and max_edge <= MAX_FACE_EDGE
        )
        polygon.select = selected_face
        if selected_face:
            selected_indices.append(polygon.index)
    selected = len(selected_indices)
    if not 250 <= selected <= 1600:
        raise RuntimeError(f"Atlas classifier selected an unsafe face count: {selected}.")
    bpy.context.view_layer.objects.active = source
    source.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    edit_mesh = bmesh.from_edit_mesh(source.data)
    edit_mesh.faces.ensure_lookup_table()
    for face in edit_mesh.faces:
        face.select = False
    for index in selected_indices:
        edit_mesh.faces[index].select = True
    bmesh.update_edit_mesh(source.data)
    bpy.ops.mesh.duplicate()
    bpy.ops.mesh.separate(type="SELECTED")
    bpy.ops.object.mode_set(mode="OBJECT")
    crowns = [item for item in bpy.context.selected_objects if item != source and item.type == "MESH"]
    if len(crowns) != 1:
        raise RuntimeError(f"Expected one separated crown mesh; found {len(crowns)}.")
    template = crowns[0]
    template.name = "CanopyStampWest"
    copies = [template]
    for name in ("CanopyStampEast", "CanopyStampSouth", "CanopyStampNorth"):
        copy = template.copy()
        copy.data = template.data
        copy.name = name
        bpy.context.collection.objects.link(copy)
        copies.append(copy)
    for item, transform in zip(copies, TRANSFORMS, strict=True):
        item.location = transform["translation"]
        item.scale = (transform["scale"],) * 3
        item.rotation_euler[2] = transform["rotation_z"]
    original_triangles = _triangles(source)
    crown_triangles = _triangles(template)
    evaluated_triangles = original_triangles + crown_triangles * len(copies)
    if evaluated_triangles >= 20_000:
        raise RuntimeError(f"Expanded canopy exceeds triangle budget: {evaluated_triangles}.")
    bpy.ops.export_scene.gltf(filepath=str(output_path), export_format="GLB", export_apply=True)
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "blender_version": bpy.app.version_string,
                "source_sha256": SOURCE_SHA256,
                "source_y_cutoff": SOURCE_Y_CUTOFF,
                "blender_axis_cutoff": {"axis": "z", "minimum": SOURCE_Y_CUTOFF},
                "green_classifier": {
                    "green_over_red_ratio": GREEN_R_RATIO,
                    "green_over_blue_ratio": GREEN_B_RATIO,
                    "green_minimum": GREEN_MINIMUM,
                    "minimum_green_sample_fraction": MIN_GREEN_SAMPLE_FRACTION,
                    "samples_per_face": "all UV corners plus centroid",
                },
                "geometry_filter": {"maximum_face_edge": MAX_FACE_EDGE},
                "atlas_image": image.name,
                "selected_face_count": selected,
                "transforms": list(TRANSFORMS),
                "original_triangles": original_triangles,
                "crown_triangles": crown_triangles,
                "crown_instances": len(copies),
                "evaluated_triangles": evaluated_triangles,
                "output_sha256": _sha256(output_path),
                "operations": [
                    "multi_sample_uv_atlas_classify",
                    "maximum_edge_filter",
                    "duplicate_selected",
                    "separate",
                    "instance_four_times_radially",
                    "export_glb",
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _base_color_image(item):
    material = item.data.materials[0]
    node = material.node_tree.nodes.get("Principled BSDF")
    if node is None:
        node = next(candidate for candidate in material.node_tree.nodes if candidate.type == "BSDF_PRINCIPLED")
    links = node.inputs["Base Color"].links
    if len(links) != 1 or links[0].from_node.type != "TEX_IMAGE":
        raise RuntimeError("Expected one image texture linked to Principled Base Color.")
    image = links[0].from_node.image
    if image is None:
        raise RuntimeError("Base-color texture has no image.")
    return image


def _pixel(pixels, width, height, u, v):
    x = min(width - 1, max(0, int((u % 1.0) * width)))
    y = min(height - 1, max(0, int((1.0 - (v % 1.0)) * height)))
    offset = (y * width + x) * 4
    return pixels[offset : offset + 4]


def _is_green(pixel) -> bool:
    red, green, blue, _ = pixel
    return bool(
        green > red * GREEN_R_RATIO
        and green > blue * GREEN_B_RATIO
        and green > GREEN_MINIMUM
    )


def _triangles(item) -> int:
    item.data.calc_loop_triangles()
    return len(item.data.loop_triangles)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    main()
