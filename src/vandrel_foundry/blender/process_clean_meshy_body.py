"""Blender entry point: remove every motion surface and export a separate glTF body."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import bpy
from mathutils import Vector

BLENDER_DIAGNOSTIC_SCHEMA = "vandrel_foundry_clean_meshy_body_blender/1.0"


def _world_bounds(meshes) -> tuple[list[float], list[float]]:
    points = [mesh.matrix_world @ Vector(corner) for mesh in meshes for corner in mesh.bound_box]
    if not points:
        raise RuntimeError("Clean body has no finite mesh bounds.")
    minimum = [min(point[index] for point in points) for index in range(3)]
    maximum = [max(point[index] for point in points) for index in range(3)]
    return minimum, maximum


def _main() -> None:
    source, albedo, output, report = map(Path, sys.argv[sys.argv.index("--") + 1 :])
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(source), use_anim=False)
    for obj in bpy.data.objects:
        if obj.animation_data is not None:
            obj.animation_data_clear()
    for action in list(bpy.data.actions):
        bpy.data.actions.remove(action)
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if len(armatures) != 1 or not meshes:
        raise RuntimeError("Clean body requires exactly one armature and visible mesh geometry.")
    source_minimum, source_maximum = _world_bounds(meshes)
    for obj in bpy.context.scene.objects:
        if obj.parent is None:
            obj.location.z -= source_minimum[2]
    bpy.context.view_layer.update()
    output_minimum, output_maximum = _world_bounds(meshes)
    material = bpy.data.materials.new("CleanBodyLit")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    principled = next(node for node in nodes if node.type == "BSDF_PRINCIPLED")
    image_node = nodes.new("ShaderNodeTexImage")
    image_node.image = bpy.data.images.load(str(albedo), check_existing=False)
    links.new(image_node.outputs["Color"], principled.inputs["Base Color"])
    principled.inputs["Roughness"].default_value = 0.8
    for mesh in meshes:
        mesh.data.materials.clear()
        mesh.data.materials.append(material)
    output.parent.mkdir(parents=True, exist_ok=True)
    copied_albedo = output.parent / "albedo.png"
    shutil.copyfile(albedo, copied_albedo)
    image_node.image.filepath = str(copied_albedo)
    image_node.image.name = "albedo"
    bpy.ops.export_scene.gltf(
        filepath=str(output),
        export_format="GLTF_SEPARATE",
        export_animations=False,
        export_materials="EXPORT",
        export_image_format="AUTO",
        export_yup=True,
    )
    nla_tracks = sum(
        len(obj.animation_data.nla_tracks)
        for obj in bpy.data.objects
        if obj.animation_data is not None
    )
    value = {
        "schema_version": BLENDER_DIAGNOSTIC_SCHEMA,
        "blender_version": bpy.app.version_string,
        "body_only": True,
        "animation_count": len(bpy.data.actions),
        "action_count": len(bpy.data.actions),
        "nla_track_count": nla_tracks,
        "armature_count": len(armatures),
        "mesh_count": len(meshes),
        "external_albedo": copied_albedo.name,
        "principled_material": True,
        "roughness": 0.8,
        "source_bounds_min": source_minimum,
        "source_bounds_max": source_maximum,
        "output_bounds_min": output_minimum,
        "output_bounds_max": output_maximum,
        "grounded": abs(output_minimum[2]) <= 0.0001,
    }
    report.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    _main()
