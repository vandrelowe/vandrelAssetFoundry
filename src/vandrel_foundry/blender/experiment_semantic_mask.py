"""Render a semantic-mask shader isolation experiment in Blender."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).parent))
import experiment_shaders

VARIANTS = (
    ("skin", (1.0, 0.0, 0.0), (0.10, 0.85, 1.0, 1.0)),
    ("fur_hair", (0.0, 1.0, 0.0), (0.10, 1.0, 0.20, 1.0)),
    ("cloth", (0.0, 0.0, 1.0), (0.90, 0.08, 1.0, 1.0)),
    ("accessories", (1.0, 1.0, 1.0), (1.0, 0.80, 0.05, 1.0)),
)


def main() -> None:
    arguments = sys.argv[sys.argv.index("--") + 1 :]
    if len(arguments) != 4:
        raise RuntimeError(
            "Expected input GLB, semantic mask, output directory, and measurements JSON."
        )
    input_path, mask_path, output_root, measurements_path = map(Path, arguments)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(input_path))
    meshes = [item for item in bpy.context.scene.objects if item.type == "MESH"]
    if not meshes:
        raise RuntimeError("Imported GLB contains no mesh objects.")
    experiment_shaders._frame_scene(meshes)
    experiment_shaders._configure_render()
    _tighten_camera(meshes)
    materials = {
        slot.material
        for mesh in meshes
        for slot in mesh.material_slots
        if slot.material is not None
    }
    originals = {
        (mesh.name, index): slot.material
        for mesh in meshes
        for index, slot in enumerate(mesh.material_slots)
    }
    mask_image = bpy.data.images.load(str(mask_path), check_existing=False)
    mask_image.colorspace_settings.name = "Non-Color"

    bpy.context.scene.render.filepath = str(output_root / "baseline.png")
    bpy.ops.render.render(write_still=True)
    for variant_name, palette_color, tint in VARIANTS:
        replacements = {
            material: _masked_material(
                material,
                mask_image,
                palette_color,
                tint,
                variant_name,
            )
            for material in materials
        }
        for mesh in meshes:
            for index, slot in enumerate(mesh.material_slots):
                original = originals[(mesh.name, index)]
                if original is not None:
                    slot.material = replacements[original]
        bpy.context.scene.render.filepath = str(output_root / f"{variant_name}.png")
        bpy.ops.render.render(write_still=True)
        for mesh in meshes:
            for index, slot in enumerate(mesh.material_slots):
                slot.material = originals[(mesh.name, index)]

    measurements_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "blender_version": bpy.app.version_string,
                "resolution": [512, 512],
                "variants": ["baseline", *(name for name, _, _ in VARIANTS)],
                "mask_sampling": "Non-Color, Closest",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _masked_material(material, mask_image, palette_color, tint, variant_name):
    clone = material.copy()
    clone.name = f"{material.name}__semantic_{variant_name}"
    clone.use_nodes = True
    tree = clone.node_tree
    principled = next(
        (node for node in tree.nodes if node.type == "BSDF_PRINCIPLED"),
        None,
    )
    if principled is None:
        return clone
    base = principled.inputs.get("Base Color")
    if base is None or not base.links:
        return clone
    source = base.links[0].from_socket
    tree.links.remove(base.links[0])
    mask = tree.nodes.new("ShaderNodeTexImage")
    mask.image = mask_image
    mask.interpolation = "Closest"
    mask.extension = "CLIP"
    distance = tree.nodes.new("ShaderNodeVectorMath")
    distance.operation = "DISTANCE"
    distance.inputs[1].default_value = palette_color
    threshold = tree.nodes.new("ShaderNodeMath")
    threshold.operation = "LESS_THAN"
    threshold.inputs[1].default_value = 0.05
    mix = tree.nodes.new("ShaderNodeMixRGB")
    mix.blend_type = "MIX"
    mix.inputs[2].default_value = tint
    tree.links.new(mask.outputs["Color"], distance.inputs[0])
    tree.links.new(distance.outputs["Value"], threshold.inputs[0])
    tree.links.new(threshold.outputs[0], mix.inputs[0])
    tree.links.new(source, mix.inputs[1])
    tree.links.new(mix.outputs[0], base)
    return clone


def _tighten_camera(meshes) -> None:
    corners = [item.matrix_world @ Vector(corner) for item in meshes for corner in item.bound_box]
    minimum = Vector(tuple(min(point[axis] for point in corners) for axis in range(3)))
    maximum = Vector(tuple(max(point[axis] for point in corners) for axis in range(3)))
    center = (minimum + maximum) / 2
    camera = bpy.context.scene.camera
    camera.location = center + (camera.location - center) * 0.48
    camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()


if __name__ == "__main__":
    main()
