"""Executed inside Blender; arguments follow a ``--`` separator."""

import json
import sys
from pathlib import Path

import bpy


def main() -> None:
    arguments = sys.argv[sys.argv.index("--") + 1 :]
    if len(arguments) not in {3, 4}:
        raise RuntimeError(
            "Expected input GLB, output GLB, report JSON, and optional triangle target."
        )
    input_path, output_path, report_path = map(Path, arguments[:3])
    target_triangles = int(arguments[3]) if len(arguments) == 4 else None
    if target_triangles is not None and target_triangles < 1:
        raise RuntimeError("Triangle target must be positive.")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    suffix = input_path.suffix.lower()
    if suffix in {".glb", ".gltf"}:
        bpy.ops.import_scene.gltf(filepath=str(input_path))
    elif suffix == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(input_path), use_image_search=True)
    else:
        raise RuntimeError(f"Unsupported Blender input format: {suffix}")
    mesh_objects = [item for item in bpy.context.scene.objects if item.type == "MESH"]
    if not mesh_objects:
        raise RuntimeError("Imported GLB contains no mesh objects.")
    for item in mesh_objects:
        item.select_set(True)
    bpy.context.view_layer.objects.active = mesh_objects[0]
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    triangles_before = sum(
        len(loop_triangles) for item in mesh_objects for loop_triangles in [_triangles(item)]
    )
    operations = ["apply_rotation", "apply_scale"]
    if target_triangles is not None and triangles_before > target_triangles:
        ratio = target_triangles / triangles_before
        for item in mesh_objects:
            bpy.context.view_layer.objects.active = item
            item.select_set(True)
            modifier = item.modifiers.new(name="Foundry Decimate", type="DECIMATE")
            modifier.ratio = ratio
            bpy.ops.object.modifier_apply(modifier=modifier.name)
            item.select_set(False)
        operations.append("decimate")
    triangles_after = sum(
        len(loop_triangles) for item in mesh_objects for loop_triangles in [_triangles(item)]
    )
    bpy.ops.export_scene.gltf(
        filepath=str(output_path),
        export_format="GLB",
        export_apply=True,
    )
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "blender_version": bpy.app.version_string,
                "input_format": suffix.removeprefix("."),
                "mesh_objects": len(mesh_objects),
                "triangles_before": triangles_before,
                "triangles_after": triangles_after,
                "target_triangles": target_triangles,
                "operations": [*operations, "export_glb"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _triangles(item):
    item.data.calc_loop_triangles()
    return item.data.loop_triangles


if __name__ == "__main__":
    main()
