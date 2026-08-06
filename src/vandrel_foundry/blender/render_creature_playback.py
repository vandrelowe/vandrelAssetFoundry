"""Render bounded continuous clip videos and framewise deformation evidence."""

import json
import math
import re
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def main() -> None:
    values = sys.argv[sys.argv.index("--") + 1 :]
    if len(values) != 3:
        raise RuntimeError("Expected input GLB, output directory, and report JSON.")
    source, output, report = map(Path, values)
    output.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    scene = bpy.context.scene
    armatures = [item for item in scene.objects if item.type == "ARMATURE"]
    if len(armatures) != 1:
        raise RuntimeError("Creature playback requires exactly one armature.")
    armature = armatures[0]
    meshes = [
        item for item in scene.objects if item.type == "MESH"
        and any(mod.type == "ARMATURE" and mod.object == armature for mod in item.modifiers)
    ]
    if not meshes:
        raise RuntimeError("Creature playback requires skinned geometry.")
    actions = sorted(bpy.data.actions, key=lambda item: item.name.casefold())
    if not actions:
        raise RuntimeError("Creature playback requires animations.")
    camera_data = bpy.data.cameras.new("PlaybackCamera")
    camera = bpy.data.objects.new("PlaybackCamera", camera_data)
    scene.collection.objects.link(camera); scene.camera = camera
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "SINGLE"
    scene.display.shading.single_color = (0.62, 0.62, 0.62)
    scene.display.shading.background_type = "WORLD"
    if scene.world is None:
        scene.world = bpy.data.worlds.new("PlaybackWorld")
    scene.world.color = (0.0, 0.0, 0.0)
    scene.render.resolution_x = 320; scene.render.resolution_y = 320
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    armature.animation_data_create()
    clips = []
    for action in actions:
        armature.animation_data.action = action
        start = math.floor(action.frame_range[0]); end = max(start, math.ceil(action.frame_range[1]))
        step = max(1, math.ceil((end - start + 1) / 45))
        frames = list(range(start, end + 1, step))
        if frames[-1] != end:
            frames.append(end)
        bounds = []
        minimum_z = []
        for frame in frames:
            scene.frame_set(frame); bpy.context.view_layer.update()
            minimum, maximum = _bounds(meshes)
            bounds.extend((minimum, maximum)); minimum_z.append(minimum.z)
        minimum = Vector(tuple(min(point[index] for point in bounds) for index in range(3)))
        maximum = Vector(tuple(max(point[index] for point in bounds) for index in range(3)))
        center = (minimum + maximum) / 2; extent = max(maximum - minimum)
        # Quadrupeds need a predominantly lateral view so torso, tail, and all
        # four limb chains remain readable throughout locomotion.
        camera.location = center + Vector((1.5, -0.18, 0.32)).normalized() * (
            extent / math.tan(camera_data.angle / 2) * 1.45
        )
        camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
        camera_data.clip_start = max(extent / 1000, 0.000001); camera_data.clip_end = extent * 100
        clip_directory = output / _slug(action.name); clip_directory.mkdir()
        frame_files = []
        for index, frame in enumerate(frames):
            scene.frame_set(frame); scene.render.filepath = str(clip_directory / f"{index:04d}.png")
            bpy.ops.render.render(write_still=True); frame_files.append(f"{_slug(action.name)}/{index:04d}.png")
        filename = f"{_slug(action.name)}.webp"
        clips.append({
            "name": action.name, "family": _family(action.name), "frame_range": [start, end],
            "frame_step": step, "sampled_frame_count": len(frames), "frame_files": frame_files,
            "video": filename, "frame_duration_ms": max(1, round(1000 * step / 30)),
            "bounds_min": list(minimum), "bounds_max": list(maximum),
            "ground_minimum_range": [min(minimum_z), max(minimum_z)],
        })
    report.write_text(json.dumps({
        "schema": "vandrel_foundry_creature_playback/1.0",
        "blender_version": bpy.app.version_string,
        "continuous_temporal_output": True,
        "clip_count": len(clips), "clips": clips,
        "review_scope": ["deformation", "scale", "ground_contact", "full_clip_family_coverage"],
    }, indent=2) + "\n", encoding="utf-8")


def _bounds(meshes):
    graph = bpy.context.evaluated_depsgraph_get(); points = []
    for item in meshes:
        evaluated = item.evaluated_get(graph); mesh = evaluated.to_mesh()
        try:
            points.extend(evaluated.matrix_world @ vertex.co for vertex in mesh.vertices)
        finally:
            evaluated.to_mesh_clear()
    if not points:
        raise RuntimeError("Playback frame has no deformed vertices.")
    return (
        Vector(tuple(min(point[index] for point in points) for index in range(3))),
        Vector(tuple(max(point[index] for point in points) for index in range(3))),
    )


def _family(name: str) -> str:
    value = name.casefold()
    for family, tokens in (
        ("death", ("death",)), ("eating", ("eat",)), ("gallop", ("gallop",)),
        ("jump", ("jump",)), ("walk", ("walk",)), ("attack", ("attack", "kick")),
        ("hit", ("hit", "react")), ("idle", ("idle",)),
    ):
        if any(token in value for token in tokens):
            return family
    return "other"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


if __name__ == "__main__":
    main()
