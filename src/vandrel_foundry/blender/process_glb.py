"""Executed inside Blender; arguments follow a ``--`` separator."""

import json
import sys
from pathlib import Path

import bpy


def main() -> None:
    arguments = sys.argv[sys.argv.index("--") + 1 :]
    if len(arguments) != 3:
        raise RuntimeError("Expected input GLB, output GLB, and report JSON paths.")
    input_path, output_path, report_path = map(Path, arguments)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(input_path))
    mesh_objects = [item for item in bpy.context.scene.objects if item.type == "MESH"]
    if not mesh_objects:
        raise RuntimeError("Imported GLB contains no mesh objects.")
    for item in mesh_objects:
        item.select_set(True)
    bpy.context.view_layer.objects.active = mesh_objects[0]
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    triangle_count = sum(
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
                "mesh_objects": len(mesh_objects),
                "triangles": triangle_count,
                "operations": ["apply_rotation", "apply_scale", "export_glb"],
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
