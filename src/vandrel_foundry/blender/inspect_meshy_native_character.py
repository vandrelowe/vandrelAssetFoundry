"""Inspect one provider-native Meshy character and its native locomotion FBXs."""

import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def main() -> None:
    values = sys.argv[sys.argv.index("--") + 1 :]
    if len(values) not in {4, 5}:
        raise RuntimeError(
            "Expected character FBX, walking FBX, optional running FBX, frame directory, and report."
        )
    paths = list(map(Path, values))
    character_path, walking_path = paths[:2]
    running_path = paths[2] if len(paths) == 5 else None
    frames_root, report_path = paths[-2:]
    frames_root.mkdir(parents=True, exist_ok=False)
    character = _inspect_fbx(character_path, render=False, frames_root=None)
    walking = _inspect_fbx(walking_path, render=True, frames_root=frames_root)
    running = (
        _inspect_fbx(running_path, render=False, frames_root=None)
        if running_path is not None
        else None
    )
    payload = {
        "schema": "vandrel_foundry_meshy_native_character_adapter/1.0",
        "blender_version": bpy.app.version_string,
        "neutral_gray": True,
        "character": character,
        "walking": walking,
        "frame_files": walking.pop("frame_files"),
    }
    if running is not None:
        payload["running"] = running
    report_path.write_text(
        json.dumps(payload, indent=2)
        + "\n",
        encoding="utf-8",
    )


def _inspect_fbx(path: Path, render: bool, frames_root: Path | None) -> dict[str, object]:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = 30
    scene.render.fps_base = 1.0
    bpy.ops.import_scene.fbx(filepath=str(path), use_anim=True)
    armatures = [item for item in scene.objects if item.type == "ARMATURE"]
    meshes = [item for item in scene.objects if item.type == "MESH"]
    if len(armatures) != 1:
        raise RuntimeError(f"Expected exactly one armature in {path.name}, found {len(armatures)}.")
    armature = armatures[0]
    skinned = [
        item
        for item in meshes
        if any(mod.type == "ARMATURE" and mod.object == armature for mod in item.modifiers)
    ]
    hierarchy = {bone.name: bone.parent.name if bone.parent else None for bone in armature.data.bones}
    unweighted = sum(
        1
        for mesh in skinned
        for vertex in mesh.data.vertices
        if not vertex.groups or sum(group.weight for group in vertex.groups) <= 0
    )
    actions = []
    for action in sorted(bpy.data.actions, key=lambda item: item.name.casefold()):
        start, end = (float(value) for value in action.frame_range)
        actions.append(
            {
                "name": action.name,
                "frame_range": [start, end],
                "duration_seconds": (end - start) / float(scene.render.fps),
            }
        )
    value = {
        "armature_count": len(armatures),
        "mesh_count": len(meshes),
        "skinned_mesh_count": len(skinned),
        "joint_count": len(hierarchy),
        "joint_hierarchy": hierarchy,
        "vertex_count": sum(len(item.data.vertices) for item in skinned),
        "polygon_count": sum(len(item.data.polygons) for item in skinned),
        "material_slot_count": sum(len(item.material_slots) for item in skinned),
        "image_count": len(bpy.data.images),
        "unweighted_vertex_count": unweighted,
        "bind_signature": _bind_signature(skinned, armature),
        "actions": actions,
    }
    if render:
        if not actions or frames_root is None:
            raise RuntimeError("Walking FBX has no animation to render.")
        value["frame_files"] = _render(scene, armature, skinned, bpy.data.actions[0], frames_root)
    return value


def _render(scene, armature, meshes, action, root):
    armature.animation_data_create()
    armature.animation_data.action = action
    camera_data = bpy.data.cameras.new("MeshyNativeCharacterCamera")
    camera = bpy.data.objects.new("MeshyNativeCharacterCamera", camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "SINGLE"
    scene.display.shading.single_color = (0.62, 0.62, 0.62)
    scene.render.resolution_x = 384
    scene.render.resolution_y = 384
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    start = math.floor(action.frame_range[0])
    end = max(start, math.ceil(action.frame_range[1]))
    step = max(1, math.ceil((end - start + 1) / 72))
    frames = list(range(start, end + 1, step))
    if frames[-1] != end:
        frames.append(end)
    points = []
    for frame in frames:
        scene.frame_set(frame)
        points.extend(_points(meshes))
    low = Vector(tuple(min(point[index] for point in points) for index in range(3)))
    high = Vector(tuple(max(point[index] for point in points) for index in range(3)))
    center = (low + high) / 2
    extent = max(high - low)
    camera.location = center + Vector((1.6, -0.12, 0.28)).normalized() * (
        extent / math.tan(camera_data.angle / 2) * 1.45
    )
    camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
    files = []
    for index, frame in enumerate(frames):
        scene.frame_set(frame)
        output = root / f"{index:04d}.png"
        scene.render.filepath = str(output)
        bpy.ops.render.render(write_still=True)
        files.append(output.name)
    return files


def _points(meshes):
    graph = bpy.context.evaluated_depsgraph_get()
    values = []
    for item in meshes:
        evaluated = item.evaluated_get(graph)
        mesh = evaluated.to_mesh()
        try:
            values.extend(evaluated.matrix_world @ vertex.co for vertex in mesh.vertices)
        finally:
            evaluated.to_mesh_clear()
    if not values:
        raise RuntimeError("No evaluated skinned mesh vertices.")
    return values


def _bind_signature(meshes, armature):
    value = {
        "bones": [
            {
                "name": bone.name,
                "parent": bone.parent.name if bone.parent else None,
                "matrix": [float(item) for row in bone.matrix_local for item in row],
            }
            for bone in armature.data.bones
        ],
        "meshes": [
            {
                "vertices": len(mesh.data.vertices),
                "groups": [group.name for group in mesh.vertex_groups],
                "weights": [
                    [[membership.group, float(membership.weight)] for membership in vertex.groups]
                    for vertex in mesh.data.vertices
                ],
            }
            for mesh in meshes
        ],
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


if __name__ == "__main__":
    main()
