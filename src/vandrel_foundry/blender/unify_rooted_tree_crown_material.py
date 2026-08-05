"""Unify crown materials on exact rooted wide-canopy candidate 010."""

import hashlib
import json
import struct
import sys
from pathlib import Path

import bpy

INPUT_SHA256 = "4080fcd3e4d29958908e17bae67a33bcd99d5a1dc1f51ffba467d773ddc8d066"
CANOPY_Z = 0.58
SOIL_Z = -0.45
GREEN_RED_RATIO = 0.80
GREEN_BLUE_RATIO = 1.05
GREEN_MINIMUM = 0.04
MINIMUM_GREEN_FRACTION = 0.25


def main() -> None:
    args = sys.argv[sys.argv.index("--") + 1 :]
    if len(args) != 3:
        raise RuntimeError("Expected input GLB, output GLB, report JSON.")
    input_path, output_path, report_path = map(Path, args)
    if _sha256(input_path) != INPUT_SHA256:
        raise RuntimeError("Input is not exact candidate 010 geometry.")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(input_path))
    meshes = sorted(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: obj.name,
    )
    before = _scene_fingerprint(meshes)
    source = max(meshes, key=lambda obj: len(obj.data.vertices))
    if len(source.data.vertices) < 1000 or not source.data.uv_layers.active:
        raise RuntimeError("Unique largest textured source mesh was not found.")

    foliage_materials = (
        _material("UnifiedFoliageDark", (0.014, 0.055, 0.007, 1.0), 1.0),
        _material("UnifiedFoliageMid", (0.014, 0.055, 0.007, 1.0), 1.0),
        _material("UnifiedFoliageLight", (0.014, 0.055, 0.007, 1.0), 1.0),
    )
    selected, rejected_wood, bucket_counts = _split_source_crown(source, foliage_materials)
    authored_counts = _remap_authored_leaves(meshes, foliage_materials)

    after = _scene_fingerprint(meshes)
    if before != after:
        raise RuntimeError("Material correction changed candidate geometry or transforms.")
    total_triangles = sum(_triangles(obj) for obj in meshes)
    if total_triangles > 20_000:
        raise RuntimeError(f"Triangle budget exceeded: {total_triangles}.")

    bpy.ops.export_scene.gltf(filepath=str(output_path), export_format="GLB", export_apply=True)
    report = {
        "schema_version": 1,
        "blender_version": bpy.app.version_string,
        "blender_args": ["--background", "--factory-startup", "--disable-autoexec"],
        "input_sha256": INPUT_SHA256,
        "method": "material_only_verified_upper_green_atlas_crown_split",
        "mask": {
            "object": source.name,
            "minimum_world_z": CANOPY_Z,
            "samples": "all UV corners plus centroid",
            "green_over_red_ratio": GREEN_RED_RATIO,
            "green_over_blue_ratio": GREEN_BLUE_RATIO,
            "green_minimum": GREEN_MINIMUM,
            "minimum_green_sample_fraction": MINIMUM_GREEN_FRACTION,
            "selected_face_count": selected,
            "rejected_below_canopy_face_count": rejected_wood,
            "selected_palette_bucket_counts": bucket_counts,
            "wood_safety": "all source faces below Z=0.58 retain original material; authored branch objects retain AuthoredCrownWood",
        },
        "material_provenance": "manually chosen local olive palette; no external texture, network, or provider input",
        "palette": [
            {"name": "UnifiedFoliageDark", "rgba": [0.014, 0.055, 0.007, 1.0], "roughness": 1.0},
            {"name": "UnifiedFoliageMid", "rgba": [0.014, 0.055, 0.007, 1.0], "roughness": 1.0},
            {"name": "UnifiedFoliageLight", "rgba": [0.014, 0.055, 0.007, 1.0], "roughness": 1.0},
        ],
        "authored_leaf_object_counts": authored_counts,
        "geometry_before": before,
        "geometry_after": after,
        "root_subset_sha256": _subset_sha256(source, lambda vertex: vertex.co.z < SOIL_Z),
        "trunk_subset_sha256": _subset_sha256(source, lambda vertex: vertex.co.z < CANOPY_Z),
        "root_vertex_count": sum(vertex.co.z < SOIL_Z for vertex in source.data.vertices),
        "trunk_vertex_count": sum(vertex.co.z < CANOPY_Z for vertex in source.data.vertices),
        "evaluated_triangles": total_triangles,
        "mesh_object_count": len(meshes),
        "output_sha256": _sha256(output_path),
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def _split_source_crown(source, materials):
    if not source.data.uv_layers.active:
        raise RuntimeError("Source crown has no active UV layer.")
    image = _base_color_image(source)
    pixels = list(image.pixels)
    width, height = image.size
    for material in materials:
        source.data.materials.append(material)
    selected = 0
    rejected_below = 0
    buckets = [0, 0, 0]
    uv_data = source.data.uv_layers.active.data
    matrix = source.matrix_world
    for polygon in source.data.polygons:
        world_z = min((matrix @ source.data.vertices[index].co).z for index in polygon.vertices)
        if world_z < CANOPY_Z:
            rejected_below += 1
            continue
        samples = [_sample(image, pixels, width, height, uv_data[index].uv) for index in polygon.loop_indices]
        centroid = sum((uv_data[index].uv for index in polygon.loop_indices), uv_data[polygon.loop_indices[0]].uv.copy() * 0.0) / len(polygon.loop_indices)
        samples.append(_sample(image, pixels, width, height, centroid))
        green = [rgb for rgb in samples if rgb[1] >= GREEN_MINIMUM and rgb[1] >= rgb[0] * GREEN_RED_RATIO and rgb[1] >= rgb[2] * GREEN_BLUE_RATIO]
        if len(green) / len(samples) < MINIMUM_GREEN_FRACTION:
            continue
        average_green = sum(rgb[1] for rgb in green) / len(green)
        bucket = 0 if average_green < 0.32 else 1 if average_green < 0.52 else 2
        polygon.material_index = len(source.data.materials) - 3 + bucket
        selected += 1
        buckets[bucket] += 1
    if selected < 100:
        raise RuntimeError(f"Crown mask selected too few faces: {selected}.")
    return selected, rejected_below, buckets


def _remap_authored_leaves(meshes, materials):
    counts = [0, 0, 0]
    for obj in meshes:
        if not (obj.name.startswith("Leaf") or obj.name.startswith("Terminal")):
            continue
        bucket = int(hashlib.sha256(obj.name.encode()).hexdigest()[:2], 16) % 3
        obj.data.materials.clear()
        obj.data.materials.append(materials[bucket])
        for polygon in obj.data.polygons:
            polygon.material_index = 0
        counts[bucket] += 1
    if sum(counts) < 1000:
        raise RuntimeError("Expected candidate-010 authored leaf population was not found.")
    return counts


def _base_color_image(source):
    for material in source.data.materials:
        if not material or not material.use_nodes:
            continue
        principled = material.node_tree.nodes.get("Principled BSDF")
        if principled is None:
            continue
        for link in material.node_tree.links:
            if (
                link.to_node == principled
                and link.to_socket == principled.inputs["Base Color"]
                and link.from_node.type == "TEX_IMAGE"
                and link.from_node.image is not None
            ):
                return link.from_node.image
    raise RuntimeError("Source base-color image not found.")


def _sample(image, pixels, width, height, uv):
    x = min(width - 1, max(0, int((uv.x % 1.0) * width)))
    y = min(height - 1, max(0, int((uv.y % 1.0) * height)))
    offset = (y * width + x) * image.channels
    return tuple(pixels[offset : offset + 3])


def _material(name, rgba, roughness):
    material = bpy.data.materials.new(name=name)
    material.diffuse_color = rgba
    material.use_nodes = True
    node = material.node_tree.nodes.get("Principled BSDF")
    node.inputs["Base Color"].default_value = rgba
    node.inputs["Roughness"].default_value = roughness
    return material


def _scene_fingerprint(meshes):
    digest = hashlib.sha256()
    for obj in meshes:
        digest.update(obj.name.encode())
        digest.update(struct.pack("<16d", *(value for row in obj.matrix_world for value in row)))
        for vertex in obj.data.vertices:
            digest.update(struct.pack("<3d", *vertex.co))
        for polygon in obj.data.polygons:
            digest.update(struct.pack("<I", len(polygon.vertices)))
            for index in polygon.vertices:
                digest.update(struct.pack("<I", index))
    return digest.hexdigest()


def _subset_sha256(obj, predicate):
    digest = hashlib.sha256()
    for vertex in obj.data.vertices:
        if predicate(vertex):
            digest.update(struct.pack("<I3d", vertex.index, *vertex.co))
    return digest.hexdigest()


def _triangles(obj):
    obj.data.calc_loop_triangles()
    return len(obj.data.loop_triangles)


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    main()
