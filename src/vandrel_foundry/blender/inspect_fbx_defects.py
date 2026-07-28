"""Bounded DM-005 source-FBX inspection executed inside Blender."""

import json
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector


def _camera(name: str, target: Vector, direction: Vector, scale: float) -> bpy.types.Object:
    data = bpy.data.cameras.new(name)
    data.type = "ORTHO"
    data.ortho_scale = scale
    data.clip_start = 0.001
    data.clip_end = scale * 100
    camera = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(camera)
    camera.location = target + direction.normalized() * scale * 5
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    return camera


def _diagnose(meshes: list[bpy.types.Object]) -> dict[str, object]:
    totals = {
        "vertices": 0,
        "edges": 0,
        "faces": 0,
        "boundary_edges": 0,
        "nonmanifold_edges": 0,
        "loose_edges": 0,
        "degenerate_faces": 0,
    }
    objects = []
    for item in meshes:
        mesh = item.data
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bm.normal_update()
        boundary = [edge for edge in bm.edges if edge.is_boundary]
        nonmanifold = [edge for edge in bm.edges if not edge.is_manifold]
        loose = [edge for edge in bm.edges if len(edge.link_faces) == 0]
        degenerate = [face for face in bm.faces if face.calc_area() <= 1.0e-12]
        facts = {
            "name": item.name,
            "vertices": len(bm.verts),
            "edges": len(bm.edges),
            "faces": len(bm.faces),
            "boundary_edges": len(boundary),
            "nonmanifold_edges": len(nonmanifold),
            "loose_edges": len(loose),
            "degenerate_faces": len(degenerate),
            "materials": [
                slot.material.name if slot.material else None for slot in item.material_slots
            ],
            "armature_modifiers": [
                modifier.object.name if modifier.object else None
                for modifier in item.modifiers
                if modifier.type == "ARMATURE"
            ],
            "vertex_groups": len(item.vertex_groups),
            "uv_layers": len(mesh.uv_layers),
            "has_custom_normals": mesh.has_custom_normals,
        }
        objects.append(facts)
        for key in totals:
            totals[key] += facts[key]
        bm.free()
    return {"totals": totals, "objects": objects}


def _material(backface: bool = False) -> bpy.types.Material:
    material = bpy.data.materials.new("DM005 Geometry Evidence")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.inputs["Roughness"].default_value = 0.8
    if backface:
        geometry = nodes.new("ShaderNodeNewGeometry")
        mix = nodes.new("ShaderNodeMixRGB")
        mix.blend_type = "MIX"
        mix.inputs[1].default_value = (0.08, 0.55, 0.12, 1.0)
        mix.inputs[2].default_value = (0.8, 0.03, 0.03, 1.0)
        links.new(geometry.outputs["Backfacing"], mix.inputs[0])
        links.new(mix.outputs[0], shader.inputs["Base Color"])
    else:
        shader.inputs["Base Color"].default_value = (0.48, 0.48, 0.48, 1.0)
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    return material


def _render(path: Path, camera: bpy.types.Object) -> None:
    scene = bpy.context.scene
    scene.camera = camera
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def main() -> None:
    arguments = sys.argv[sys.argv.index("--") + 1 :]
    if len(arguments) != 2:
        raise RuntimeError("Expected exact input FBX and a new output directory.")
    input_path = Path(arguments[0])
    output = Path(arguments[1])
    output.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(input_path), use_anim=True)

    meshes = [item for item in bpy.context.scene.objects if item.type == "MESH"]
    armatures = [item for item in bpy.context.scene.objects if item.type == "ARMATURE"]
    if not meshes or not armatures:
        raise RuntimeError("Expected at least one mesh and armature.")
    corners = [item.matrix_world @ Vector(corner) for item in meshes for corner in item.bound_box]
    minimum = Vector(tuple(min(point[i] for point in corners) for i in range(3)))
    maximum = Vector(tuple(max(point[i] for point in corners) for i in range(3)))
    center = (minimum + maximum) / 2
    height = maximum.z - minimum.z
    if height <= 0:
        raise RuntimeError("Imported FBX has zero height.")
    head_target = Vector((center.x, center.y, minimum.z + height * 0.78))
    close_scale = height * 0.42
    full_scale = height * 1.15

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 2048
    scene.render.resolution_y = 2048
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    if scene.world is None:
        scene.world = bpy.data.worlds.new("DM005 World")
    scene.world.color = (0.035, 0.035, 0.035)

    for name, direction in (
        ("front", Vector((0, -1, 0))),
        ("right", Vector((1, 0, 0))),
        ("back", Vector((0, 1, 0))),
        ("left", Vector((-1, 0, 0))),
    ):
        camera = _camera(f"Full {name}", center, direction, full_scale)
        _render(output / f"material_full_{name}.png", camera)
        if name in {"front", "right"}:
            close = _camera(f"Close {name}", head_target, direction, close_scale)
            _render(output / f"material_close_{name}.png", close)

    original_materials = [[slot.material for slot in item.material_slots] for item in meshes]
    for mode, evidence_material in (
        ("geometry", _material()),
        ("backface", _material(backface=True)),
    ):
        for item in meshes:
            for slot in item.material_slots:
                slot.material = evidence_material
        for name, direction in (
            ("front", Vector((0, -1, 0))),
            ("right", Vector((1, 0, 0))),
        ):
            close = _camera(f"{mode} close {name}", head_target, direction, close_scale)
            _render(output / f"{mode}_close_{name}.png", close)

    for item, materials in zip(meshes, original_materials, strict=True):
        for slot, material in zip(item.material_slots, materials, strict=True):
            slot.material = material

    armature_facts = []
    for item in armatures:
        armature_facts.append(
            {
                "name": item.name,
                "bone_count": len(item.data.bones),
                "bones": [
                    {"name": bone.name, "parent": bone.parent.name if bone.parent else None}
                    for bone in item.data.bones
                ],
                "scale": list(item.scale),
            }
        )
    report = {
        "schema_version": 1,
        "experiment": "dm005_source_fbx_phase_a",
        "blender_version": bpy.app.version_string,
        "input": str(input_path.name),
        "bounds": {"minimum": list(minimum), "maximum": list(maximum), "height": height},
        "mesh": _diagnose(meshes),
        "armatures": armature_facts,
        "modifiers": {
            item.name: [
                {"name": modifier.name, "type": modifier.type} for modifier in item.modifiers
            ]
            for item in meshes
        },
        "images": sorted(path.name for path in output.glob("*.png")),
        "limitations": [
            "Global topology counts locate structural risk but do not classify artistic intent.",
            "Image review is required; counts alone do not prove a visible defect.",
        ],
    }
    (output / "phase-a-report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
