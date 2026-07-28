"""Executed inside Blender; arguments follow a ``--`` separator."""

import json
import sys
from pathlib import Path

import bpy
import numpy as np


def main() -> None:
    arguments = sys.argv[sys.argv.index("--") + 1 :]
    if len(arguments) != 5:
        raise RuntimeError(
            "Expected input GLB, mask PNG, output GLB, report JSON, and RGB hex color."
        )
    input_path, mask_path, output_path, report_path = map(Path, arguments[:4])
    target_srgb = _parse_hex(arguments[4])

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(input_path))
    meshes = [item for item in bpy.context.scene.objects if item.type == "MESH"]
    if not meshes:
        raise RuntimeError("Imported GLB contains no mesh objects.")
    image = _base_color_image()
    mask = bpy.data.images.load(str(mask_path), check_existing=False)
    if tuple(image.size) != tuple(mask.size):
        raise RuntimeError(
            f"Texture mask dimensions {tuple(mask.size)} do not match "
            f"base color texture {tuple(image.size)}."
        )

    width, height = image.size
    source = np.empty(width * height * 4, dtype=np.float32)
    mask_pixels = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(source)
    mask.pixels.foreach_get(mask_pixels)
    source = source.reshape((-1, 4))
    mask_pixels = mask_pixels.reshape((-1, 4))
    weights = np.clip(mask_pixels[:, :3].max(axis=1), 0.0, 1.0)
    selected = int(np.count_nonzero(weights > 0.001))
    if selected == 0 or selected == width * height:
        raise RuntimeError("Texture mask must select a nonempty, bounded region.")

    target_linear = np.array([_srgb_to_linear(value) for value in target_srgb])
    luminance = source[:, 0] * 0.2126 + source[:, 1] * 0.7152 + source[:, 2] * 0.0722
    shade = 0.88 + np.clip(luminance, 0.0, 1.0) * 0.12
    recolored = shade[:, None] * target_linear[None, :]
    source[:, :3] = source[:, :3] * (1.0 - weights[:, None]) + recolored * weights[:, None]
    image.pixels.foreach_set(source.reshape(-1))
    image.update()
    image.pack()

    animation_count = len(bpy.data.actions)
    bpy.ops.export_scene.gltf(
        filepath=str(output_path),
        export_format="GLB",
        export_apply=False,
        export_animations=True,
    )
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "blender_version": bpy.app.version_string,
                "texture_dimensions": [width, height],
                "mask_dimensions": [width, height],
                "selected_pixels": selected,
                "coverage_fraction": selected / (width * height),
                "target_color_srgb": [round(value, 6) for value in target_srgb],
                "mesh_objects": len(meshes),
                "animation_count_before": animation_count,
                "operations": [
                    "load_grayscale_region_mask",
                    "colorize_region_preserving_luminance",
                    "pack_modified_base_color",
                    "export_glb",
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _base_color_image():
    matches = []
    for material in bpy.data.materials:
        if not material.use_nodes:
            continue
        for node in material.node_tree.nodes:
            if node.type != "BSDF_PRINCIPLED":
                continue
            links = node.inputs["Base Color"].links
            if links and links[0].from_node.type == "TEX_IMAGE":
                matches.append(links[0].from_node.image)
    unique = {image.name: image for image in matches if image is not None}
    if len(unique) != 1:
        raise RuntimeError("Texture-mask processing requires exactly one base-color image.")
    return next(iter(unique.values()))


def _parse_hex(value: str) -> tuple[float, float, float]:
    text = value.removeprefix("#")
    if len(text) != 6:
        raise RuntimeError("Target color must be a six-digit RGB hex value.")
    try:
        channels = tuple(int(text[index : index + 2], 16) / 255 for index in (0, 2, 4))
    except ValueError as exc:
        raise RuntimeError("Target color must be a six-digit RGB hex value.") from exc
    return channels


def _srgb_to_linear(value: float) -> float:
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


if __name__ == "__main__":
    main()
