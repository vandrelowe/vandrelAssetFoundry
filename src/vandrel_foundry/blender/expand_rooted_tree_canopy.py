"""Hand-model a coherent wide crown on the approved inverted-roots tree."""

import hashlib
import json
import math
import random
import struct
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

SOURCE_SHA256 = "9fc4714bc995951d11f4c23d64f4091323f2e58c01f8728865c2828c02be832c"
SOIL_Z = -0.45
CANOPY_Z = 0.58
SEED = 845113


def main() -> None:
    args = sys.argv[sys.argv.index("--") + 1 :]
    if len(args) != 3:
        raise RuntimeError("Expected input GLB, output GLB, report JSON.")
    source_path, output_path, report_path = map(Path, args)
    if _sha256(source_path) != SOURCE_SHA256:
        raise RuntimeError("Approved source hash mismatch.")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source_path))
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if len(meshes) != 1:
        raise RuntimeError(f"Expected one source mesh, found {len(meshes)}.")
    source = meshes[0]
    before = _fingerprints(source)

    wood = _material("AuthoredCrownWood", (0.008, 0.003, 0.001, 1.0), 0.92)
    leaf_dark = _material("AuthoredLeafDark", (0.002, 0.014, 0.0008, 1.0), 0.88)
    leaf_mid = _material("AuthoredLeafMid", (0.006, 0.030, 0.002, 1.0), 0.86)
    objects, branch_records = _build_crown(wood, (leaf_dark, leaf_mid))

    after = _fingerprints(source)
    if before != after:
        raise RuntimeError("Approved source/root/trunk geometry changed.")
    original_triangles = _triangles(source)
    added_triangles = sum(_triangles(obj) for obj in objects)
    total_triangles = original_triangles + added_triangles
    if total_triangles >= 20_000:
        raise RuntimeError(f"Triangle budget exceeded: {total_triangles}.")

    bpy.ops.export_scene.gltf(filepath=str(output_path), export_format="GLB", export_apply=True)
    report = {
        "schema_version": 1,
        "blender_version": bpy.app.version_string,
        "blender_args": ["--background", "--factory-startup", "--disable-autoexec"],
        "source_sha256": SOURCE_SHA256,
        "method": "hand_modeled_radial_branch_network_with_attached_individual_leaf_geometry",
        "copied_source_faces": 0,
        "seed": SEED,
        "material_provenance": "locally authored source-matched flat colors; no external texture or provider input",
        "materials": [
            {"name": "AuthoredCrownWood", "rgba": [0.008, 0.003, 0.001, 1.0]},
            {"name": "AuthoredLeafDark", "rgba": [0.002, 0.014, 0.0008, 1.0]},
            {"name": "AuthoredLeafMid", "rgba": [0.006, 0.030, 0.002, 1.0]},
        ],
        "branch_records": branch_records,
        "original_triangles": original_triangles,
        "constructed_triangles": added_triangles,
        "evaluated_triangles": total_triangles,
        "constructed_object_count": len(objects),
        "preservation": before | {f"{key}_after": value for key, value in after.items()},
        "output_sha256": _sha256(output_path),
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def _build_crown(wood, leaf_materials):
    rng = random.Random(SEED)
    objects = []
    records = []
    hub = Vector((0.0, 0.0, 0.635))
    # Twelve staggered rising limbs broaden both axes and overlap at the hub.
    plans = [
        (0, 0.40, 0.13), (30, 0.33, 0.23), (60, 0.38, 0.16),
        (90, 0.35, 0.27), (120, 0.41, 0.12), (150, 0.34, 0.21),
        (180, 0.39, 0.15), (210, 0.36, 0.25), (240, 0.40, 0.11),
        (270, 0.34, 0.22), (300, 0.39, 0.15), (330, 0.36, 0.26),
    ]
    for branch_index, (degrees, reach, rise) in enumerate(plans):
        angle = math.radians(degrees)
        start = hub + Vector((0.018 * math.cos(angle), 0.018 * math.sin(angle), 0.0))
        elbow = hub + Vector((reach * 0.48 * math.cos(angle), reach * 0.48 * math.sin(angle), rise * 0.45))
        end = hub + Vector((reach * math.cos(angle), reach * math.sin(angle), rise))
        objects.append(_branch(f"MainBranch{branch_index:02d}a", start, elbow, 0.020, 0.013, wood))
        objects.append(_branch(f"MainBranch{branch_index:02d}b", elbow, end, 0.013, 0.006, wood))
        twig_ends = []
        for twig_index, fraction in enumerate((0.40, 0.53, 0.66, 0.78, 0.90)):
            base = elbow.lerp(end, max(0.0, (fraction - 0.48) / 0.52))
            side = -1 if twig_index % 2 == 0 else 1
            tangent = Vector((math.cos(angle), math.sin(angle), 0.0))
            lateral = Vector((-math.sin(angle), math.cos(angle), 0.0))
            tip = base + tangent * rng.uniform(0.025, 0.065) + lateral * side * rng.uniform(0.060, 0.105) + Vector((0, 0, rng.uniform(0.035, 0.11)))
            objects.append(_branch(f"Twig{branch_index:02d}_{twig_index}", base, tip, 0.006, 0.002, wood, sides=5))
            twig_ends.append(tip)
            # Leaves are anchored along each twig rather than floating clusters.
            for leaf_index in range(15):
                t = 0.12 + 0.86 * leaf_index / 14
                anchor = base.lerp(tip, t)
                leaf_angle = angle + side * (0.55 + 0.10 * (leaf_index % 3)) + rng.uniform(-0.18, 0.18)
                length = rng.uniform(0.055, 0.095)
                width = rng.uniform(0.026, 0.044)
                lift = rng.uniform(-0.006, 0.040)
                leaf = _leaf(f"Leaf{branch_index:02d}_{twig_index}_{leaf_index:02d}", anchor, leaf_angle, length, width, lift, leaf_materials[leaf_index % 2], rng)
                objects.append(leaf)
        # Dense attached terminal spray closes the outer silhouette without rosettes.
        for terminal_index in range(18):
            theta = angle + rng.uniform(-0.75, 0.75)
            anchor = end + Vector((rng.uniform(-0.025, 0.025), rng.uniform(-0.025, 0.025), rng.uniform(-0.02, 0.04)))
            objects.append(_leaf(f"Terminal{branch_index:02d}_{terminal_index:02d}", anchor, theta, rng.uniform(0.06, 0.10), rng.uniform(0.028, 0.046), rng.uniform(0.0, 0.050), leaf_materials[terminal_index % 2], rng))
        records.append({"index": branch_index, "azimuth_degrees": degrees, "reach": reach, "rise": rise, "start": list(start), "end": list(end), "twig_ends": [list(v) for v in twig_ends]})
    return objects, records


def _branch(name, start, end, radius_start, radius_end, material, sides=7):
    direction = end - start
    length = direction.length
    vertices = []
    faces = []
    for ring, radius in ((0, radius_start), (1, radius_end)):
        z = ring * length
        for i in range(sides):
            angle = 2 * math.pi * i / sides
            vertices.append((radius * math.cos(angle), radius * math.sin(angle), z))
    for i in range(sides):
        nxt = (i + 1) % sides
        faces.append((i, nxt, sides + nxt, sides + i))
    faces.extend((tuple(range(sides - 1, -1, -1)), tuple(range(sides, 2 * sides))))
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata(vertices, [], faces)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.matrix_world = Matrix.Translation(start) @ direction.to_track_quat("Z", "Y").to_matrix().to_4x4()
    mesh.materials.append(material)
    return obj


def _leaf(name, anchor, angle, length, width, lift, material, rng):
    pitch = rng.uniform(-0.45, 0.60) + lift / max(length, 0.001)
    forward = Vector((math.cos(angle), math.sin(angle), pitch)).normalized()
    side = Vector((-math.sin(angle), math.cos(angle), rng.uniform(-0.22, 0.22))).normalized()
    p1 = anchor + forward * length * 0.28
    p2 = anchor + forward * length * 0.58 + Vector((0, 0, rng.uniform(-0.008, 0.012)))
    tip = anchor + forward * length + Vector((0, 0, rng.uniform(-0.006, 0.014)))
    w1 = width * rng.uniform(0.55, 0.90)
    w2 = width * rng.uniform(0.80, 1.15)
    center = anchor + forward * length * 0.52 + Vector((0, 0, rng.uniform(0.002, 0.012)))
    vertices = [anchor, p1 + side * w1, p2 + side * w2, tip, p2 - side * w2, p1 - side * w1, center]
    faces = [(0, 1, 6), (1, 2, 6), (2, 3, 6), (3, 4, 6), (4, 5, 6), (5, 0, 6)]
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata(vertices, [], faces)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    mesh.materials.append(material)
    return obj


def _material(name, rgba, roughness):
    material = bpy.data.materials.new(name=name)
    material.diffuse_color = rgba
    material.use_nodes = True
    node = material.node_tree.nodes.get("Principled BSDF")
    node.inputs["Base Color"].default_value = rgba
    node.inputs["Roughness"].default_value = roughness
    return material


def _fingerprints(obj):
    return {
        "source_geometry_before": _geometry_sha256(obj),
        "root_subset_before": _subset_sha256(obj, lambda v: v.co.z < SOIL_Z),
        "trunk_subset_before": _subset_sha256(obj, lambda v: v.co.z < CANOPY_Z),
        "root_vertex_count": sum(v.co.z < SOIL_Z for v in obj.data.vertices),
        "trunk_vertex_count": sum(v.co.z < CANOPY_Z for v in obj.data.vertices),
    }


def _geometry_sha256(obj):
    digest = hashlib.sha256()
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
