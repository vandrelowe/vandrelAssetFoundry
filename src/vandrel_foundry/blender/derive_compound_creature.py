"""Bounded Blender adapter for mesh-to-donor-rig binding."""

import json
import sys
from pathlib import Path

import bpy


def main() -> None:
    values = sys.argv[sys.argv.index("--") + 1 :]
    if len(values) < 5:
        raise RuntimeError("Expected mesh source, rig donor, output GLB, report JSON, and materials.")
    mesh_path, donor_path, output_path, report_path, *material_paths = map(Path, values)
    if any(not path.is_file() for path in material_paths):
        raise RuntimeError("Every declared material dependency must exist.")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    _import(mesh_path)
    source_meshes = [item for item in bpy.context.scene.objects if item.type == "MESH"]
    if not source_meshes:
        raise RuntimeError("Mesh/material contribution contains no mesh.")
    imported_image_paths = {
        Path(bpy.path.abspath(image.filepath)).resolve()
        for image in bpy.data.images
        if image.filepath
    }
    missing_materials = [path for path in material_paths if path.resolve() not in imported_image_paths]
    if missing_materials:
        raise RuntimeError(f"Declared material dependencies are not used: {missing_materials}")
    source_armatures = [item for item in bpy.context.scene.objects if item.type == "ARMATURE"]
    for item in source_armatures:
        bpy.data.objects.remove(item, do_unlink=True)
    for item in source_meshes:
        for modifier in list(item.modifiers):
            item.modifiers.remove(modifier)
        item.vertex_groups.clear()
        item.parent = None
    for action in list(bpy.data.actions):
        bpy.data.actions.remove(action)
    source_objects = set(bpy.context.scene.objects)
    _import(donor_path)
    donor_armatures = [
        item for item in bpy.context.scene.objects
        if item.type == "ARMATURE" and item not in source_objects
    ]
    if len(donor_armatures) != 1:
        raise RuntimeError("Rig/animation donor must contain exactly one armature.")
    donor = donor_armatures[0]
    donor_actions = list(bpy.data.actions)
    if not donor_actions:
        raise RuntimeError("Rig/animation donor must contain animations.")
    donor_meshes = [
        item for item in bpy.context.scene.objects
        if item.type == "MESH" and item not in source_objects
    ]
    for item in donor_meshes:
        bpy.data.objects.remove(item, do_unlink=True)
    bpy.ops.object.select_all(action="DESELECT")
    for item in source_meshes:
        item.select_set(True)
    donor.select_set(True)
    bpy.context.view_layer.objects.active = donor
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    unweighted_vertex_count = sum(
        1
        for item in source_meshes
        for vertex in item.data.vertices
        if not vertex.groups or sum(group.weight for group in vertex.groups) <= 0.0
    )
    if unweighted_vertex_count:
        raise RuntimeError(f"Automatic weighting left {unweighted_vertex_count} vertices unweighted.")
    bpy.ops.object.select_all(action="DESELECT")
    for item in source_meshes:
        item.select_set(True)
    donor.select_set(True)
    bpy.context.view_layer.objects.active = donor
    bpy.ops.export_scene.gltf(
        filepath=str(output_path), export_format="GLB", export_animations=True,
        use_selection=True,
    )
    report_path.write_text(
        json.dumps(
            {
                "tool_version": bpy.app.version_string,
                "transformation_facts": {
                    "factory_startup": True,
                    "mesh_objects_retained": len(source_meshes),
                    "donor_armatures_retained": 1,
                    "source_armatures_removed": len(source_armatures),
                    "donor_mesh_objects_removed": len(donor_meshes),
                    "binding_method": "blender_armature_deform_automatic_weights",
                    "donor_actions_retained": len(donor_actions),
                    "material_dependencies_declared": len(material_paths),
                    "material_dependencies_used": len(material_paths),
                    "output_skin_count": 1,
                    "output_animation_count": len(donor_actions),
                    "unweighted_exported_vertex_count": unweighted_vertex_count,
                    "export_format": "glb",
                    "animations_exported": True,
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _import(path: Path) -> None:
    suffix = path.suffix.lower()
    if suffix in {".glb", ".gltf"}:
        bpy.ops.import_scene.gltf(filepath=str(path))
    elif suffix == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(path))
    else:
        raise RuntimeError(f"Unsupported contribution format: {suffix}")


if __name__ == "__main__":
    main()
