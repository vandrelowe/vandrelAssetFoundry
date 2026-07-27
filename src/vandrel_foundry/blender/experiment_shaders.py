"""Executed inside Blender; arguments follow a ``--`` separator."""

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

VARIANTS = ("baseline_pbr", "cool_tint", "matte", "polished")


def main() -> None:
    arguments = sys.argv[sys.argv.index("--") + 1 :]
    if len(arguments) != 3:
        raise RuntimeError("Expected input GLB, output directory, and measurements JSON.")
    input_path, output_root, measurements_path = map(Path, arguments)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(input_path))
    meshes = [item for item in bpy.context.scene.objects if item.type == "MESH"]
    if not meshes:
        raise RuntimeError("Imported GLB contains no mesh objects.")
    skinned_meshes = [
        item for item in meshes if any(modifier.type == "ARMATURE" for modifier in item.modifiers)
    ]
    framed_meshes = skinned_meshes or meshes
    materials = sorted(
        {slot.material for mesh in meshes for slot in mesh.material_slots if slot.material},
        key=lambda material: material.name,
    )
    if not materials:
        raise RuntimeError("Imported GLB contains no materials.")

    _frame_scene(framed_meshes)
    _configure_render()
    original_materials = {
        (mesh.name, slot_index): slot.material
        for mesh in meshes
        for slot_index, slot in enumerate(mesh.material_slots)
    }
    facts = _measure_materials(materials, meshes)
    definitions = {
        "baseline_pbr": "Imported PBR material unchanged.",
        "cool_tint": (
            "Global cool color multiply inserted before each Principled base-color input."
        ),
        "matte": "Imported base color and normals; roughness forced to 0.82, metallic to 0.",
        "polished": (
            "Imported base color and normals; roughness forced to 0.20, metallic to 0.30."
        ),
    }
    for variant in VARIANTS:
        _restore_materials(meshes, original_materials)
        if variant != "baseline_pbr":
            replacements = {
                material: _variant_material(material, variant) for material in materials
            }
            for mesh in meshes:
                for slot in mesh.material_slots:
                    if slot.material in replacements:
                        slot.material = replacements[slot.material]
        bpy.context.scene.render.filepath = str(output_root / f"{variant}.png")
        bpy.ops.render.render(write_still=True)

    measurements_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "blender_version": bpy.app.version_string,
                "resolution": [512, 512],
                "variants": list(VARIANTS),
                "variant_definitions": definitions,
                "measured_material_facts": facts,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _variant_material(material, variant: str):
    clone = material.copy()
    clone.name = f"{material.name}__{variant}"
    clone.use_nodes = True
    tree = clone.node_tree
    principled = next(
        (node for node in tree.nodes if node.type == "BSDF_PRINCIPLED"),
        None,
    )
    if principled is None:
        return clone
    if variant == "cool_tint":
        base = principled.inputs.get("Base Color")
        if base is not None:
            links = list(base.links)
            if links:
                source = links[0].from_socket
                tree.links.remove(links[0])
                multiply = tree.nodes.new("ShaderNodeMixRGB")
                multiply.blend_type = "MULTIPLY"
                multiply.inputs[0].default_value = 1.0
                multiply.inputs[2].default_value = (0.72, 0.88, 1.0, 1.0)
                tree.links.new(source, multiply.inputs[1])
                tree.links.new(multiply.outputs[0], base)
            else:
                red, green, blue, alpha = base.default_value
                base.default_value = (red * 0.72, green * 0.88, blue, alpha)
    elif variant in {"matte", "polished"}:
        roughness = principled.inputs.get("Roughness")
        metallic = principled.inputs.get("Metallic")
        if roughness is not None:
            for link in list(roughness.links):
                tree.links.remove(link)
            roughness.default_value = 0.82 if variant == "matte" else 0.20
        if metallic is not None:
            for link in list(metallic.links):
                tree.links.remove(link)
            metallic.default_value = 0.0 if variant == "matte" else 0.30
    return clone


def _measure_materials(materials, meshes) -> dict:
    image_nodes = []
    principled_nodes = []
    linked = {"base_color": 0, "roughness": 0, "metallic": 0, "normal": 0}
    images = {}
    for material in materials:
        if not material.use_nodes:
            continue
        for node in material.node_tree.nodes:
            if node.type == "TEX_IMAGE":
                image_nodes.append(node)
                if node.image:
                    images[node.image.name] = [int(node.image.size[0]), int(node.image.size[1])]
            if node.type == "BSDF_PRINCIPLED":
                principled_nodes.append(node)
                for key, socket_name in (
                    ("base_color", "Base Color"),
                    ("roughness", "Roughness"),
                    ("metallic", "Metallic"),
                    ("normal", "Normal"),
                ):
                    socket = node.inputs.get(socket_name)
                    linked[key] += int(socket is not None and socket.is_linked)
    slot_count = sum(len(mesh.material_slots) for mesh in meshes)
    return {
        "mesh_objects": len(meshes),
        "material_slot_count": slot_count,
        "unique_material_count": len(materials),
        "principled_node_count": len(principled_nodes),
        "image_texture_node_count": len(image_nodes),
        "unique_images": images,
        "linked_principled_inputs": linked,
    }


def _restore_materials(meshes, original_materials) -> None:
    for mesh in meshes:
        for slot_index, slot in enumerate(mesh.material_slots):
            slot.material = original_materials[(mesh.name, slot_index)]


def _frame_scene(framed_meshes) -> None:
    corners = [
        item.matrix_world @ Vector(corner) for item in framed_meshes for corner in item.bound_box
    ]
    minimum = Vector(tuple(min(point[index] for point in corners) for index in range(3)))
    maximum = Vector(tuple(max(point[index] for point in corners) for index in range(3)))
    center = (minimum + maximum) / 2
    extent = max(maximum - minimum)
    if extent <= 0:
        raise RuntimeError("Imported GLB has zero-size bounds.")
    camera_data = bpy.data.cameras.new("Foundry Shader Experiment Camera")
    camera_data.clip_start = max(extent / 1000, 0.000001)
    camera_data.clip_end = max(extent * 100, 1.0)
    camera = bpy.data.objects.new("Foundry Shader Experiment Camera", camera_data)
    bpy.context.scene.collection.objects.link(camera)
    direction = Vector((1.4, -1.4, 1.0)).normalized()
    camera.location = center + direction * (extent / math.tan(camera_data.angle / 2) * 0.85)
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


def _configure_render() -> None:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 512
    scene.render.resolution_y = 512
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = True


if __name__ == "__main__":
    main()
