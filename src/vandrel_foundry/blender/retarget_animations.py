"""Executed inside Blender; arguments follow a ``--`` separator."""

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

PROCESSOR_VERSION = "1"
ROOT_BONE = "Hips"


def main() -> None:
    arguments = sys.argv[sys.argv.index("--") + 1 :]
    if len(arguments) != 4:
        raise RuntimeError("Expected target GLB, donor GLB, output GLB, and report JSON.")
    target_path, donor_path, output_path, report_path = map(Path, arguments)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = 30
    scene.render.fps_base = 1.0

    bpy.ops.import_scene.gltf(filepath=str(target_path))
    target_armature = _single_armature("target")
    target_meshes = _skinned_meshes(target_armature)
    if not target_meshes:
        raise RuntimeError("Target GLB has no mesh skinned to its armature.")
    target_actions = set(bpy.data.actions)
    target_objects = set(scene.objects)
    target_armature.name = "FoundryTargetArmature"
    if target_armature.animation_data:
        target_armature.animation_data.action = None

    bpy.ops.import_scene.gltf(filepath=str(donor_path))
    armatures = [item for item in scene.objects if item.type == "ARMATURE"]
    donor_candidates = [item for item in armatures if item != target_armature]
    if len(donor_candidates) != 1:
        raise RuntimeError(f"Expected one donor armature, found {len(donor_candidates)}.")
    donor_armature = donor_candidates[0]
    donor_actions = [item for item in bpy.data.actions if item not in target_actions]
    if not donor_actions:
        raise RuntimeError("Donor GLB contains no actions.")

    target_names = set(target_armature.data.bones.keys())
    donor_names = set(donor_armature.data.bones.keys())
    if target_names != donor_names:
        missing = sorted(donor_names - target_names)
        extra = sorted(target_names - donor_names)
        raise RuntimeError(f"Rig bone names differ; missing={missing}, extra={extra}.")
    for name in sorted(target_names):
        target_parent = target_armature.data.bones[name].parent
        donor_parent = donor_armature.data.bones[name].parent
        if (target_parent.name if target_parent else None) != (
            donor_parent.name if donor_parent else None
        ):
            raise RuntimeError(f"Rig hierarchy differs at bone: {name}.")
    if ROOT_BONE not in target_names:
        raise RuntimeError(f"Required root bone is missing: {ROOT_BONE}.")

    ordered_names = _hierarchy_order(target_armature)
    target_rest = {
        name: target_armature.data.bones[name].matrix_local.copy() for name in ordered_names
    }
    donor_rest = {
        name: donor_armature.data.bones[name].matrix_local.copy() for name in ordered_names
    }
    scale_ratio = _skeleton_scale(target_rest) / _skeleton_scale(donor_rest)
    output_actions = []
    action_reports = []

    for donor_action in sorted(donor_actions, key=lambda item: item.name):
        original_name = donor_action.name
        donor_action.name = f"__foundry_donor__{original_name}"
        action = bpy.data.actions.new(name=original_name)
        donor_armature.animation_data_create()
        target_armature.animation_data_create()
        donor_armature.animation_data.action = donor_action
        target_armature.animation_data.action = action

        start = math.floor(donor_action.frame_range[0] + 1e-4)
        end = math.ceil(donor_action.frame_range[1] - 1e-4)
        end = max(end, start)
        for frame in range(start, end + 1):
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            for pose_bone in target_armature.pose.bones:
                pose_bone.matrix_basis.identity()
                pose_bone.rotation_mode = "QUATERNION"
            for name in ordered_names:
                donor_bone = donor_armature.pose.bones[name]
                pose_bone = target_armature.pose.bones[name]
                if name == ROOT_BONE:
                    donor_world_delta = (
                        donor_bone.matrix.to_quaternion()
                        @ donor_rest[name].to_quaternion().inverted()
                    )
                    target_rotation = donor_world_delta @ target_rest[name].to_quaternion()
                    target_translation = (
                        target_rest[name].translation
                        + (donor_bone.matrix.translation - donor_rest[name].translation)
                        * scale_ratio
                    )
                    pose_bone.matrix = Matrix.LocRotScale(
                        target_translation,
                        target_rotation,
                        Vector((1.0, 1.0, 1.0)),
                    )
                else:
                    pose_bone.location = donor_bone.location * scale_ratio
                    pose_bone.rotation_quaternion = donor_bone.rotation_quaternion
                    pose_bone.scale = donor_bone.scale
                pose_bone.keyframe_insert("location", frame=frame, group=name)
                pose_bone.keyframe_insert("rotation_quaternion", frame=frame, group=name)
                pose_bone.keyframe_insert("scale", frame=frame, group=name)
        output_actions.append(action)
        action_reports.append(
            {
                "name": original_name,
                "source_frame_range": [donor_action.frame_range[0], donor_action.frame_range[1]],
                "baked_frame_range": [start, end],
                "baked_frames": end - start + 1,
            }
        )

    donor_armature.animation_data.action = None
    target_armature.animation_data.action = output_actions[0]
    for item in list(scene.objects):
        if item not in target_objects:
            bpy.data.objects.remove(item, do_unlink=True)
    for action in [*target_actions, *donor_actions]:
        bpy.data.actions.remove(action)

    bpy.ops.export_scene.gltf(
        filepath=str(output_path),
        export_format="GLB",
        export_animations=True,
        export_animation_mode="ACTIONS",
        export_frame_step=1,
        export_force_sampling=True,
        export_apply=False,
    )
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "processor": {
                    "name": "blender_rest_pose_retarget",
                    "version": PROCESSOR_VERSION,
                },
                "blender_version": bpy.app.version_string,
                "root_bone": ROOT_BONE,
                "root_motion_policy": "preserve_scaled_hips_translation",
                "rotation_policy": "local_pose_basis_on_target_rest",
                "translation_policy": "uniformly_scaled_local_pose_basis",
                "sample_rate_fps": scene.render.fps,
                "skeleton_scale_ratio": scale_ratio,
                "bone_count": len(ordered_names),
                "output_animation_count": len(output_actions),
                "animations": action_reports,
                "limitations": [
                    "Baked output still requires visual deformation and foot-contact review.",
                    "Root motion is technical evidence and has no Vandrel runtime semantics.",
                    "The output is a Foundry candidate, not Vandrel animation acceptance.",
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _single_armature(label: str):
    values = [item for item in bpy.context.scene.objects if item.type == "ARMATURE"]
    if len(values) != 1:
        raise RuntimeError(f"Expected one {label} armature, found {len(values)}.")
    return values[0]


def _skinned_meshes(armature):
    return [
        item
        for item in bpy.context.scene.objects
        if item.type == "MESH" and _uses_armature(item, armature)
    ]


def _uses_armature(item, armature) -> bool:
    return item.type == "MESH" and any(
        modifier.type == "ARMATURE" and modifier.object == armature for modifier in item.modifiers
    )


def _hierarchy_order(armature) -> list[str]:
    pending = set(armature.data.bones.keys())
    ordered = []
    while pending:
        ready = sorted(
            name
            for name in pending
            if armature.data.bones[name].parent is None
            or armature.data.bones[name].parent.name in ordered
        )
        if not ready:
            raise RuntimeError("Armature hierarchy is cyclic or incomplete.")
        ordered.extend(ready)
        pending.difference_update(ready)
    return ordered


def _skeleton_scale(rest: dict[str, Matrix]) -> float:
    points = [matrix.translation for matrix in rest.values()]
    minimum = Vector(tuple(min(point[index] for point in points) for index in range(3)))
    maximum = Vector(tuple(max(point[index] for point in points) for index in range(3)))
    scale = (maximum - minimum).length
    if scale <= 1e-8:
        raise RuntimeError("Armature rest pose has zero extent.")
    return scale


if __name__ == "__main__":
    main()
