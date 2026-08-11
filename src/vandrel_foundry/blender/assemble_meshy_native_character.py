"""Assemble normalized Meshy-native actions onto one exact native character rig."""

import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector


def main() -> None:
    values = sys.argv[sys.argv.index("--") + 1 :]
    if len(values) not in {6, 7}:
        raise RuntimeError(
            "Expected character FBX, texture PNG, canary GLB, top-four reference GLB, "
            "output GLB, report JSON, and optional multi-motion entry manifest."
        )
    (
        character_path,
        texture_path,
        canary_path,
        reference_path,
        output_path,
        report_path,
    ) = map(Path, values[:6])
    extension_manifest_path = Path(values[6]) if len(values) == 7 else None
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = 30
    scene.render.fps_base = 1.0

    bpy.ops.import_scene.fbx(filepath=str(character_path), use_anim=True)
    target_armatures = [item for item in scene.objects if item.type == "ARMATURE"]
    if len(target_armatures) != 1:
        raise RuntimeError("Real Meshy character must contain exactly one armature.")
    target = target_armatures[0]
    target_meshes = _skinned_meshes(scene, target)
    if not target_meshes:
        raise RuntimeError("Real Meshy character has no native skinned mesh.")
    _bind_exact_texture(target_meshes, texture_path)
    target_hierarchy = _hierarchy(target)
    if len(target_hierarchy) != 24:
        raise RuntimeError("Real Meshy character does not contain the fixed 24-joint profile.")
    if _unweighted(target_meshes, target):
        raise RuntimeError("Real Meshy character contains unweighted vertices.")
    native_skin_signature = _skin_weight_signature(target_meshes, target)
    top4_policy = _apply_top4_policy(target_meshes, target)
    top4_skin_signature = _skin_weight_signature(target_meshes, target)
    bind_before = _bind_matrix_signature(target_meshes, target)
    material_before = _material_signature(target_meshes)
    target_actions = list(bpy.data.actions)
    for action in target_actions:
        bpy.data.actions.remove(action)
    _export(target, target_meshes, reference_path, animations=False)

    existing_objects = set(scene.objects)
    bpy.ops.import_scene.gltf(filepath=str(canary_path))
    imported = [item for item in scene.objects if item not in existing_objects]
    source_armatures = [item for item in imported if item.type == "ARMATURE"]
    if len(source_armatures) != 1:
        raise RuntimeError("Canary motion model must contain exactly one armature.")
    source = source_armatures[0]
    source_hierarchy = _hierarchy(source)
    if source_hierarchy != target_hierarchy:
        raise RuntimeError("Canary and real-character native joint hierarchies do not match.")
    rest_rotation_delta = _maximum_rest_rotation_delta(source, target)
    armature_correction = (
        target.matrix_world.to_quaternion().normalized().inverted()
        @ source.matrix_world.to_quaternion().normalized()
    ).normalized()
    source_actions = sorted(bpy.data.actions, key=lambda item: item.name.casefold())
    if len(source_actions) != 10 or len({item.name for item in source_actions}) != 10:
        raise RuntimeError("Canary motion model must contain exactly ten unique actions.")
    scale_ratio = _rig_scale(target) / _rig_scale(source)
    transferred = []
    clip_facts = []
    for source_action in source_actions:
        action, facts = _transfer_action(
            scene,
            source,
            target,
            target_meshes,
            source_action,
            scale_ratio,
            armature_correction,
        )
        action.use_fake_user = True
        transferred.append(action)
        clip_facts.append(facts)

    for item in imported:
        bpy.data.objects.remove(item, do_unlink=True)
    for action in source_actions:
        if action.name in bpy.data.actions:
            bpy.data.actions.remove(action)
    for action, facts in zip(transferred, clip_facts, strict=True):
        action.name = facts["exact_name"]
    extension_facts = []
    collision_facts = []
    if extension_manifest_path is not None:
        extension_facts, collision_facts = _add_extension_actions(
            scene,
            target,
            target_meshes,
            target_hierarchy,
            transferred,
            clip_facts,
            extension_manifest_path,
        )
    bind_after = _bind_matrix_signature(target_meshes, target)
    material_after = _material_signature(target_meshes)
    if bind_before != bind_after:
        raise RuntimeError("Real-character native skin/bind relationship changed during assembly.")
    if material_before != material_after:
        raise RuntimeError("Real-character material/texture relationship changed during assembly.")
    if _unweighted(target_meshes, target):
        raise RuntimeError("Assembled character contains unweighted vertices.")
    if _skin_weight_signature(target_meshes, target) != top4_skin_signature:
        raise RuntimeError("Deterministic top-four skin changed during motion assembly.")

    _export(target, target_meshes, output_path, animations=True)
    if not output_path.is_file():
        raise RuntimeError("Meshy-native character exporter did not create the GLB.")
    report_path.write_text(
        json.dumps(
            {
                "schema": (
                    "vandrel_foundry_meshy_native_character_assembly_adapter/5.0"
                    if extension_manifest_path is not None
                    else "vandrel_foundry_meshy_native_character_assembly_adapter/3.0"
                ),
                "blender_version": bpy.app.version_string,
                "transformation_facts": {
                    "target_joint_count": len(target_hierarchy),
                    "source_joint_count": len(source_hierarchy),
                    "exact_native_joint_hierarchy_match": True,
                    "semantic_transfer_policy": (
                        "native_joint_identity_global_pose_reconstruction"
                    ),
                    "index_or_mixamo_graft": False,
                    "rest_rotation_max_delta_radians": rest_rotation_delta,
                    "armature_space_correction_quaternion_wxyz": [
                        float(item) for item in armature_correction
                    ],
                    "armature_space_correction_angle_degrees": math.degrees(
                        armature_correction.angle
                    ),
                    "target_rest_translation_policy": (
                        "preserve_target_rest_translations_and_bone_lengths"
                    ),
                    "target_pose_scale_policy": "identity_preserves_target_bone_lengths",
                    "old_target_global_rest_postfactor_applied": False,
                    "direct_matrix_basis_copy_applied": False,
                    "maximum_sampled_global_orientation_delta_degrees": max(
                        facts["maximum_sampled_global_orientation_delta_degrees"]
                        for facts in clip_facts
                    ),
                    "maximum_sampled_parent_local_orientation_delta_degrees": max(
                        facts["maximum_sampled_parent_local_orientation_delta_degrees"]
                        for facts in clip_facts
                    ),
                    "translation_scale_ratio": scale_ratio,
                    "target_bind_matrix_signature_before": bind_before,
                    "target_bind_matrix_signature_after": bind_after,
                    "bind_matrices_preserved": True,
                    "source_native_skin_weight_signature": native_skin_signature,
                    "target_top4_skin_weight_signature": top4_skin_signature,
                    "skin_weight_policy": "deterministic_top4_normalized",
                    "skin_weights_exactly_preserved": False,
                    **top4_policy,
                    "target_material_signature_before": material_before,
                    "target_material_signature_after": material_after,
                    "material_texture_preserved": True,
                    "preexport_unweighted_vertex_count": 0,
                    "output_action_count": len(transferred),
                    "base_action_count": 10,
                    "extension_source_entry_count": len(extension_facts),
                    "extension_compatible_entry_count": sum(
                        item["runtime_eligibility"] == "identity_normalized"
                        for item in extension_facts
                    ),
                    "extension_provenance_only_entry_count": sum(
                        item["runtime_eligibility"]
                        == "provenance_only_legacy_outlier"
                        for item in extension_facts
                    ),
                    "runtime_collision_count": len(collision_facts),
                    "runtime_deduplicated_collision_count": sum(
                        item["resolution"]
                        in {"deduplicated_identical", "deduplicated_identical_curve"}
                        for item in collision_facts
                    ),
                    "runtime_source_qualified_collision_count": sum(
                        item["resolution"] == "source_qualified_alternative"
                        for item in collision_facts
                    ),
                    "root_motion_policy": (
                        "per_clip_xy_start_baseline_then_actual_target_mesh_ground_to_z_zero"
                    ),
                },
                "clips": clip_facts,
                "extension_entries": extension_facts,
                "collisions": collision_facts,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _add_extension_actions(
    scene,
    target,
    target_meshes,
    target_hierarchy,
    transferred,
    clip_facts,
    manifest_path,
):
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = value.get("entries") if isinstance(value, dict) else None
    if not isinstance(entries, list) or not entries:
        raise RuntimeError("Meshy multi-motion adapter requires at least one FBX entry.")
    runtime_actions = {action.name: action for action in transferred}
    entry_facts = []
    collision_facts = []
    package_rest_signatures = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise TypeError("Meshy multi-motion entry descriptor is invalid.")
        artifact_id = entry.get("artifact_id")
        exact_name = entry.get("exact_export_name")
        eligibility = entry.get("runtime_eligibility")
        package_number = entry.get("source_package_number")
        source_qualifier = entry.get("source_qualifier")
        source_path = Path(entry.get("path", ""))
        if (
            not isinstance(artifact_id, str)
            or not isinstance(exact_name, str)
            or eligibility
            not in {"identity_normalized", "provenance_only_legacy_outlier"}
            or not isinstance(package_number, int)
            or package_number < 1
            or not isinstance(source_qualifier, str)
            or len(source_qualifier) != 8
            or any(character not in "0123456789abcdef" for character in source_qualifier)
            or not source_path.is_file()
        ):
            raise RuntimeError("Meshy multi-motion entry descriptor is incomplete.")
        existing_objects = set(scene.objects)
        existing_actions = set(bpy.data.actions)
        bpy.ops.import_scene.fbx(filepath=str(source_path), use_anim=True)
        scene.render.fps = 30
        scene.render.fps_base = 1.0
        imported = [item for item in scene.objects if item not in existing_objects]
        source_armatures = [item for item in imported if item.type == "ARMATURE"]
        source_actions = [item for item in bpy.data.actions if item not in existing_actions]
        if len(source_armatures) != 1 or len(source_actions) != 1:
            raise RuntimeError(
                f"Meshy multi-motion {artifact_id} requires one armature and one action."
            )
        source = source_armatures[0]
        source_action = source_actions[0]
        hierarchy = _hierarchy(source)
        if hierarchy != target_hierarchy or len(hierarchy) != 24:
            raise RuntimeError(f"Meshy multi-motion hierarchy mismatch: {artifact_id}.")
        source_meshes = _skinned_meshes(scene, source)
        if not source_meshes or _unweighted(source_meshes, source):
            raise RuntimeError(f"Meshy multi-motion skin is invalid: {artifact_id}.")
        rest_signature = _rest_signature(source)
        container_angle = math.degrees(
            source.matrix_world.to_quaternion().normalized().angle
        )
        if eligibility == "provenance_only_legacy_outlier":
            if exact_name != "019fee70-fd9d-7b6e-914a-d6dad2a49eeb" or not (
                89.0 <= container_angle <= 91.0
            ):
                raise RuntimeError("Known Meshy legacy UUID container proof failed.")
            entry_facts.append(
                {
                    "artifact_id": artifact_id,
                    "exact_export_name": exact_name,
                    "embedded_action_name": source_action.name,
                    "runtime_eligibility": eligibility,
                    "source_package_number": package_number,
                    "source_qualifier": source_qualifier,
                    "joint_count": len(hierarchy),
                    "rest_signature": rest_signature,
                    "container_rotation_degrees": container_angle,
                    "runtime_action_name": None,
                    "exclusion_reason": "known_legacy_plus_90_x_container_outlier",
                }
            )
            _remove_imported(imported, source_actions)
            continue
        if container_angle > 0.01:
            raise RuntimeError(
                f"Meshy multi-motion identity container mismatch: {artifact_id}={container_angle}."
            )
        established_rest = package_rest_signatures.setdefault(package_number, rest_signature)
        if rest_signature != established_rest:
            raise RuntimeError(
                f"Meshy multi-motion package rest signature mismatch: {artifact_id}."
            )
        runtime_name = f"target_character|{exact_name}"
        scale_ratio = _rig_scale(target) / _rig_scale(source)
        armature_correction = (
            target.matrix_world.to_quaternion().normalized().inverted()
            @ source.matrix_world.to_quaternion().normalized()
        ).normalized()
        action, facts = _transfer_action(
            scene,
            source,
            target,
            target_meshes,
            source_action,
            scale_ratio,
            armature_correction,
        )
        action.use_fake_user = True
        collision = runtime_actions.get(runtime_name)
        source_curve_signature = _action_curve_signature(source_action)
        entry_fact = {
            "artifact_id": artifact_id,
            "exact_export_name": exact_name,
            "embedded_action_name": entry.get("embedded_action_name", source_action.name),
            "runtime_eligibility": eligibility,
            "source_package_number": package_number,
            "source_qualifier": source_qualifier,
            "joint_count": len(hierarchy),
            "rest_signature": rest_signature,
            "container_rotation_degrees": container_angle,
            "source_frame_range": [
                float(source_action.frame_range[0]),
                float(source_action.frame_range[1]),
            ],
            "source_duration_seconds": (
                float(source_action.frame_range[1]) - float(source_action.frame_range[0])
            )
            / 30.0,
            "source_curve_sha256": source_curve_signature,
            "transferred_curve_sha256": _action_curve_signature(action),
        }
        if collision is None:
            identical = _find_identical_action(runtime_actions, action)
            if identical is None:
                action.name = runtime_name
                facts["exact_name"] = runtime_name
                facts["source_artifact_id"] = artifact_id
                facts["source_exact_export_name"] = exact_name
                facts["source_package_number"] = package_number
                facts["source_qualifier"] = source_qualifier
                runtime_actions[runtime_name] = action
                transferred.append(action)
                clip_facts.append(facts)
                entry_fact["runtime_action_name"] = runtime_name
                entry_fact["collision_resolution"] = "none"
            else:
                existing_name, comparison = identical
                bpy.data.actions.remove(action)
                entry_fact["runtime_action_name"] = existing_name
                entry_fact["collision_resolution"] = "deduplicated_identical_curve"
                collision_facts.append(
                    {
                        "exact_export_name": exact_name,
                        "existing_runtime_action_name": existing_name,
                        "source_artifact_id": artifact_id,
                        "source_qualifier": source_qualifier,
                        "resolution": "deduplicated_identical_curve",
                        "selected_runtime_action_name": existing_name,
                        "retained_alternative_action_name": None,
                        "curve_comparison": comparison,
                    }
                )
        else:
            comparison = _compare_actions(collision, action)
            if comparison["identical"]:
                bpy.data.actions.remove(action)
                entry_fact["runtime_action_name"] = runtime_name
                entry_fact["collision_resolution"] = "deduplicated_identical"
                collision_facts.append(
                    {
                        "exact_export_name": exact_name,
                        "existing_runtime_action_name": runtime_name,
                        "source_artifact_id": artifact_id,
                        "source_qualifier": source_qualifier,
                        "resolution": "deduplicated_identical",
                        "selected_runtime_action_name": runtime_name,
                        "retained_alternative_action_name": None,
                        "curve_comparison": comparison,
                    }
                )
            else:
                identical = _find_identical_action(
                    {
                        name: existing
                        for name, existing in runtime_actions.items()
                        if name != runtime_name
                    },
                    action,
                )
                if identical is not None:
                    existing_name, identical_comparison = identical
                    bpy.data.actions.remove(action)
                    entry_fact["runtime_action_name"] = existing_name
                    entry_fact["collision_resolution"] = "deduplicated_identical_curve"
                    collision_facts.append(
                        {
                            "exact_export_name": exact_name,
                            "existing_runtime_action_name": runtime_name,
                            "source_artifact_id": artifact_id,
                            "source_qualifier": source_qualifier,
                            "resolution": "deduplicated_identical_curve",
                            "selected_runtime_action_name": existing_name,
                            "retained_alternative_action_name": None,
                            "curve_comparison": identical_comparison,
                        }
                    )
                else:
                    qualified = f"target_character|multi_{source_qualifier}|{exact_name}"
                    if qualified in runtime_actions:
                        raise RuntimeError("Stable Meshy source-qualified action ID collides.")
                    action.name = qualified
                    facts["exact_name"] = qualified
                    facts["source_artifact_id"] = artifact_id
                    facts["source_exact_export_name"] = exact_name
                    facts["source_package_number"] = package_number
                    facts["source_qualifier"] = source_qualifier
                    runtime_actions[qualified] = action
                    transferred.append(action)
                    clip_facts.append(facts)
                    entry_fact["runtime_action_name"] = qualified
                    entry_fact["collision_resolution"] = "source_qualified_alternative"
                    collision_facts.append(
                        {
                            "exact_export_name": exact_name,
                            "existing_runtime_action_name": runtime_name,
                            "source_artifact_id": artifact_id,
                            "source_qualifier": source_qualifier,
                            "resolution": "source_qualified_alternative",
                            "selected_runtime_action_name": runtime_name,
                            "retained_alternative_action_name": qualified,
                            "curve_comparison": comparison,
                        }
                    )
        entry_facts.append(entry_fact)
        _remove_imported(imported, source_actions)
    if not package_rest_signatures:
        raise RuntimeError("Meshy multi-motion archive has no identity-compatible action.")
    return entry_facts, collision_facts


def _action_fcurves(action):
    if hasattr(action, "fcurves"):
        return list(action.fcurves)
    values = []
    for layer in getattr(action, "layers", []):
        for strip in getattr(layer, "strips", []):
            for channelbag in getattr(strip, "channelbags", []):
                values.extend(channelbag.fcurves)
    return values


def _action_curve_signature(action):
    value = {
        "frame_range": [float(item) for item in action.frame_range],
        "curves": [],
    }
    for curve in sorted(
        _action_fcurves(action), key=lambda item: (item.data_path, item.array_index)
    ):
        value["curves"].append(
            {
                "data_path": curve.data_path,
                "array_index": curve.array_index,
                "points": [
                    {
                        "co": [float(point.co.x), float(point.co.y)],
                        "handle_left": [
                            float(point.handle_left.x),
                            float(point.handle_left.y),
                        ],
                        "handle_right": [
                            float(point.handle_right.x),
                            float(point.handle_right.y),
                        ],
                        "interpolation": point.interpolation,
                        "easing": point.easing,
                        "handle_left_type": point.handle_left_type,
                        "handle_right_type": point.handle_right_type,
                    }
                    for point in curve.keyframe_points
                ],
            }
        )
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _find_identical_action(runtime_actions, candidate):
    for name, existing in sorted(runtime_actions.items()):
        comparison = _compare_actions(existing, candidate)
        if comparison["identical"]:
            return name, comparison
    return None


def _compare_actions(first, second):
    first_range = tuple(float(value) for value in first.frame_range)
    second_range = tuple(float(value) for value in second.frame_range)
    range_delta = max(
        abs(left - right) for left, right in zip(first_range, second_range, strict=True)
    )
    if range_delta > 1e-6:
        return {
            "identical": False,
            "reason": "duration_mismatch",
            "maximum_key_value_delta": range_delta,
        }
    first_curves = sorted(
        _action_fcurves(first), key=lambda item: (item.data_path, item.array_index)
    )
    second_curves = sorted(
        _action_fcurves(second), key=lambda item: (item.data_path, item.array_index)
    )
    if len(first_curves) != len(second_curves):
        return {
            "identical": False,
            "reason": "curve_count_mismatch",
            "maximum_key_value_delta": None,
        }
    maximum = 0.0
    for left, right in zip(first_curves, second_curves, strict=True):
        if (left.data_path, left.array_index) != (right.data_path, right.array_index):
            return {
                "identical": False,
                "reason": "curve_identity_mismatch",
                "maximum_key_value_delta": None,
            }
        left_points = list(left.keyframe_points)
        right_points = list(right.keyframe_points)
        if len(left_points) != len(right_points):
            return {
                "identical": False,
                "reason": "key_count_mismatch",
                "maximum_key_value_delta": None,
            }
        for left_point, right_point in zip(left_points, right_points, strict=True):
            frame_delta = abs(float(left_point.co.x) - float(right_point.co.x))
            value_delta = abs(float(left_point.co.y) - float(right_point.co.y))
            maximum = max(maximum, frame_delta, value_delta)
            if (
                left_point.interpolation != right_point.interpolation
                or left_point.easing != right_point.easing
                or left_point.handle_left_type != right_point.handle_left_type
                or left_point.handle_right_type != right_point.handle_right_type
            ):
                return {
                    "identical": False,
                    "reason": "curve_interpolation_mismatch",
                    "maximum_key_value_delta": maximum,
                }
            for left_handle, right_handle in (
                (left_point.handle_left, right_point.handle_left),
                (left_point.handle_right, right_point.handle_right),
            ):
                maximum = max(
                    maximum,
                    abs(float(left_handle.x) - float(right_handle.x)),
                    abs(float(left_handle.y) - float(right_handle.y)),
                )
    return {
        "identical": maximum <= 1e-6,
        "reason": "exact_within_1e-6" if maximum <= 1e-6 else "material_value_delta",
        "maximum_key_value_delta": maximum,
    }


def _rest_signature(armature):
    value = [
        {
            "name": bone.name,
            "parent": bone.parent.name if bone.parent else None,
            "matrix_local": [float(item) for row in bone.matrix_local for item in row],
        }
        for bone in armature.data.bones
    ]
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _remove_imported(objects, actions):
    for item in objects:
        if item.name in bpy.data.objects:
            bpy.data.objects.remove(item, do_unlink=True)
    for action in actions:
        if action.name in bpy.data.actions:
            bpy.data.actions.remove(action)
    bpy.data.orphans_purge(do_recursive=True)


def _transfer_action(
    scene,
    source,
    target,
    meshes,
    source_action,
    scale_ratio,
    armature_correction,
):
    source.animation_data_create()
    target.animation_data_create()
    source.animation_data.action = source_action
    start = math.floor(source_action.frame_range[0])
    end = max(start + 1, math.ceil(source_action.frame_range[1]))
    output = bpy.data.actions.new(f"__target__{source_action.name}")
    ordered_target_bones = sorted(target.pose.bones, key=_bone_depth)
    source_root_rest = source.data.bones["Hips"].matrix_local
    target_root_rest_rotation = (
        target.data.bones["Hips"].matrix_local.to_quaternion().normalized()
    )
    for frame in range(start, end + 1):
        source.animation_data.action = source_action
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        target.animation_data.action = output
        for bone in ordered_target_bones:
            source_pose = source.pose.bones[bone.name]
            desired_global_rotation = (
                armature_correction @ source_pose.matrix.to_quaternion().normalized()
            ).normalized()
            parent_rotation = (
                bone.parent.matrix.to_quaternion().normalized()
                if bone.parent is not None
                else Quaternion((1.0, 0.0, 0.0, 0.0))
            )
            target_local_rest = _local_rest_rotation(target.data.bones[bone.name])
            basis_rotation = (
                (parent_rotation @ target_local_rest).inverted()
                @ desired_global_rotation
            ).normalized()
            bone.rotation_mode = "QUATERNION"
            bone.rotation_quaternion = basis_rotation
            if bone.name == "Hips":
                source_delta = source_pose.matrix.translation - source_root_rest.translation
                mapped_delta = (armature_correction @ source_delta) * scale_ratio
                bone.location = target_root_rest_rotation.inverted() @ mapped_delta
            else:
                bone.location = Vector((0.0, 0.0, 0.0))
            bone.scale = Vector((1.0, 1.0, 1.0))
            _finite([*bone.location, *bone.rotation_quaternion, *bone.scale], bone.name)
            bone.keyframe_insert("location", frame=frame, group=bone.name)
            bone.keyframe_insert("rotation_quaternion", frame=frame, group=bone.name)
            bone.keyframe_insert("scale", frame=frame, group=bone.name)
            bpy.context.view_layer.update()
    target.animation_data.action = output
    root = target.pose.bones["Hips"]
    scene.frame_set(start)
    baseline = root.location.copy()
    for frame in range(start, end + 1):
        scene.frame_set(frame)
        root.location.x -= baseline.x
        root.location.y -= baseline.y
        root.keyframe_insert("location", frame=frame, group=root.name)
    ground_before = math.inf
    for frame in range(start, end + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        ground_before = min(ground_before, float(_bounds(meshes)[0].z))
    world_shift = Vector((0.0, 0.0, -ground_before))
    correction = (
        root.bone.matrix_local.to_3x3().inverted()
        @ target.matrix_world.to_3x3().inverted()
        @ world_shift
    )
    ground_after = []
    deformation = 0.0
    baseline_points = None
    for frame in range(start, end + 1):
        scene.frame_set(frame)
        root.location += correction
        root.keyframe_insert("location", frame=frame, group=root.name)
        bpy.context.view_layer.update()
        points = _points(meshes)
        ground_after.append(float(min(point.z for point in points)))
        if frame in {start, (start + end) // 2, end}:
            if baseline_points is None:
                baseline_points = points
            else:
                deformation = max(
                    deformation,
                    max(
                        (point - baseline_points[index]).length
                        for index, point in enumerate(points)
                    ),
                )
    angular_deltas = _sample_angular_deltas(
        scene,
        source,
        target,
        source_action,
        output,
        armature_correction,
        start,
        end,
    )
    return output, {
        "exact_name": source_action.name,
        "frame_range": [start, end],
        "duration_seconds": (end - start) / 30.0,
        "root_xy_baseline": [float(baseline.x), float(baseline.y)],
        "ground_before_correction_z": ground_before,
        "ground_after_range_z": [min(ground_after), max(ground_after)],
        "maximum_sampled_vertex_displacement": deformation,
        "sampled_orientation_deltas": angular_deltas,
        "maximum_sampled_global_orientation_delta_degrees": max(
            sample["maximum_global_delta_degrees"] for sample in angular_deltas.values()
        ),
        "maximum_sampled_parent_local_orientation_delta_degrees": max(
            sample["maximum_parent_local_delta_degrees"]
            for sample in angular_deltas.values()
        ),
    }


def _sample_angular_deltas(
    scene,
    source,
    target,
    source_action,
    target_action,
    armature_correction,
    start,
    end,
):
    result = {}
    for label, frame in (
        ("frame_start", start),
        ("frame_mid", (start + end) // 2),
        ("frame_end", end),
    ):
        source.animation_data.action = source_action
        target.animation_data.action = target_action
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        joints = []
        for source_pose in source.pose.bones:
            target_pose = target.pose.bones[source_pose.name]
            desired_global = (
                armature_correction @ source_pose.matrix.to_quaternion().normalized()
            ).normalized()
            source_local = (
                source_pose.parent.matrix.to_quaternion().normalized().inverted()
                @ source_pose.matrix.to_quaternion().normalized()
                if source_pose.parent is not None
                else armature_correction @ source_pose.matrix.to_quaternion().normalized()
            )
            target_local = (
                target_pose.parent.matrix.to_quaternion().normalized().inverted()
                @ target_pose.matrix.to_quaternion().normalized()
                if target_pose.parent is not None
                else target_pose.matrix.to_quaternion().normalized()
            )
            joints.append(
                {
                    "joint": source_pose.name,
                    "global_delta_degrees": _quaternion_angle_degrees(
                        desired_global, target_pose.matrix.to_quaternion()
                    ),
                    "parent_local_delta_degrees": _quaternion_angle_degrees(
                        source_local, target_local
                    ),
                }
            )
        result[label] = {
            "frame": frame,
            "maximum_global_delta_degrees": max(
                item["global_delta_degrees"] for item in joints
            ),
            "maximum_parent_local_delta_degrees": max(
                item["parent_local_delta_degrees"] for item in joints
            ),
            "largest_global_joints": sorted(
                joints, key=lambda item: item["global_delta_degrees"], reverse=True
            )[:5],
        }
    return result


def _quaternion_angle_degrees(first, second):
    angle = float(first.normalized().rotation_difference(second.normalized()).angle)
    return math.degrees(min(angle, abs((2 * math.pi) - angle)))


def _bone_depth(pose_bone):
    value = 0
    parent = pose_bone.parent
    while parent is not None:
        value += 1
        parent = parent.parent
    return value


def _bind_exact_texture(meshes, texture_path):
    image = bpy.data.images.load(str(texture_path), check_existing=False)
    materials = [slot.material for mesh in meshes for slot in mesh.material_slots if slot.material]
    if not materials:
        raise RuntimeError("Real Meshy character has no material.")
    bound = 0
    for material in materials:
        material.use_nodes = True
        nodes = material.node_tree.nodes
        textures = [node for node in nodes if node.type == "TEX_IMAGE"]
        if not textures:
            texture = nodes.new("ShaderNodeTexImage")
            shader = next((node for node in nodes if node.type == "BSDF_PRINCIPLED"), None)
            if shader is None:
                raise RuntimeError("Real Meshy material has no Principled shader.")
            material.node_tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
            textures = [texture]
        for texture in textures:
            texture.image = image
            bound += 1
    if not bound:
        raise RuntimeError("Exact Meshy texture was not bound to the character material.")


def _skinned_meshes(scene, armature):
    return [
        item
        for item in scene.objects
        if item.type == "MESH"
        and any(mod.type == "ARMATURE" and mod.object == armature for mod in item.modifiers)
    ]


def _hierarchy(armature):
    return {bone.name: bone.parent.name if bone.parent else None for bone in armature.data.bones}


def _maximum_rest_rotation_delta(source, target):
    values = []
    for name in _hierarchy(source):
        source_bone = source.data.bones[name]
        target_bone = target.data.bones[name]
        if source_bone.parent is None:
            continue
        source_local = source_bone.parent.matrix_local.inverted() @ source_bone.matrix_local
        target_local = target_bone.parent.matrix_local.inverted() @ target_bone.matrix_local
        first = source_local.to_quaternion().normalized()
        second = target_local.to_quaternion().normalized()
        angle = float(first.rotation_difference(second).angle)
        values.append(min(angle, abs((2 * math.pi) - angle)))
    if not values:
        raise RuntimeError("Meshy native rig has no parent-relative rest rotations.")
    return max(values)


def _local_rest_rotation(bone):
    matrix = (
        bone.parent.matrix_local.inverted() @ bone.matrix_local
        if bone.parent is not None
        else bone.matrix_local
    )
    return matrix.to_quaternion().normalized()


def _rig_scale(armature):
    points = [armature.matrix_world @ bone.head_local for bone in armature.data.bones]
    extent = max(point.z for point in points) - min(point.z for point in points)
    if not math.isfinite(extent) or extent <= 0:
        raise RuntimeError("Meshy native rig has invalid scale.")
    return extent


def _unweighted(meshes, armature):
    bone_names = {bone.name for bone in armature.data.bones}
    return sum(
        1
        for mesh in meshes
        for vertex in mesh.data.vertices
        if sum(
            group.weight
            for group in vertex.groups
            if mesh.vertex_groups[group.group].name in bone_names
        )
        <= 0
    )


def _apply_top4_policy(meshes, armature):
    bone_names = {bone.name for bone in armature.data.bones}
    over_four = 0
    maximum_before = 0
    dropped_weight = 0.0
    vertex_count = 0
    for mesh in sorted(meshes, key=lambda item: item.name.casefold()):
        groups = {index: group for index, group in enumerate(mesh.vertex_groups)}
        for vertex in mesh.data.vertices:
            vertex_count += 1
            weighted = [
                (groups[item.group].name, float(item.weight), groups[item.group])
                for item in vertex.groups
                if groups[item.group].name in bone_names and float(item.weight) > 0.0
            ]
            weighted.sort(key=lambda item: (-item[1], item[0].casefold(), item[0]))
            maximum_before = max(maximum_before, len(weighted))
            if len(weighted) > 4:
                over_four += 1
            retained = weighted[:4]
            dropped_weight += sum(item[1] for item in weighted[4:])
            total = sum(item[1] for item in retained)
            if not math.isfinite(total) or total <= 0:
                raise RuntimeError("Top-four skin policy encountered an unweighted vertex.")
            for item in list(vertex.groups):
                groups[item.group].remove([vertex.index])
            for _name, weight, group in retained:
                group.add([vertex.index], weight / total, "REPLACE")
    if _unweighted(meshes, armature):
        raise RuntimeError("Top-four skin policy produced unweighted vertices.")
    maximum_after = max(
        sum(
            1
            for item in vertex.groups
            if mesh.vertex_groups[item.group].name in bone_names and item.weight > 1e-8
        )
        for mesh in meshes
        for vertex in mesh.data.vertices
    )
    if maximum_after > 4:
        raise RuntimeError("Top-four skin policy left more than four influences.")
    return {
        "source_vertex_count": vertex_count,
        "source_maximum_influences": maximum_before,
        "source_vertices_over_four_influences": over_four,
        "dropped_source_weight_total": dropped_weight,
        "top4_maximum_influences": maximum_after,
        "top4_normalized": True,
    }


def _skin_weight_signature(meshes, armature):
    bone_names = {bone.name for bone in armature.data.bones}
    value = []
    for mesh in sorted(meshes, key=lambda item: item.name.casefold()):
        value.append(
            {
                "mesh": mesh.name,
                "vertices": [
                    [
                        [mesh.vertex_groups[item.group].name, float(item.weight)]
                        for item in sorted(
                            (
                                item
                                for item in vertex.groups
                                if mesh.vertex_groups[item.group].name in bone_names
                                and item.weight > 0
                            ),
                            key=lambda entry: mesh.vertex_groups[entry.group].name.casefold(),
                        )
                    ]
                    for vertex in mesh.data.vertices
                ],
            }
        )
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _bind_matrix_signature(meshes, armature):
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
                "name": mesh.name,
                "armature_modifiers": sorted(
                    modifier.name
                    for modifier in mesh.modifiers
                    if modifier.type == "ARMATURE" and modifier.object == armature
                ),
            }
            for mesh in meshes
        ],
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _material_signature(meshes):
    value = []
    for mesh in meshes:
        for slot in mesh.material_slots:
            material = slot.material
            value.append(
                {
                    "material": material.name if material else None,
                    "images": sorted(
                        node.image.name
                        for node in material.node_tree.nodes
                        if node.type == "TEX_IMAGE" and node.image is not None
                    )
                    if material and material.use_nodes
                    else [],
                }
            )
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


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
        raise RuntimeError("Real Meshy character has no evaluated vertices.")
    _finite([coordinate for point in values for coordinate in point], "evaluated geometry")
    return values


def _bounds(meshes):
    points = _points(meshes)
    return (
        Vector(tuple(min(point[index] for point in points) for index in range(3))),
        Vector(tuple(max(point[index] for point in points) for index in range(3))),
    )


def _finite(values, context):
    if any(not math.isfinite(float(value)) for value in values):
        raise RuntimeError(f"Nonfinite transform in {context}.")


def _select_only(objects):
    bpy.ops.object.select_all(action="DESELECT")
    for item in objects:
        item.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]


def _export(armature, meshes, path, *, animations):
    _select_only([armature, *meshes])
    bpy.ops.export_scene.gltf(
        filepath=str(path),
        export_format="GLB",
        use_selection=True,
        export_animations=animations,
        export_animation_mode="ACTIONS",
        export_anim_slide_to_zero=False,
        export_skins=True,
        export_materials="EXPORT",
        export_all_influences=False,
        export_influence_nb=4,
    )
    if not path.is_file():
        raise RuntimeError("Meshy-native character exporter did not create the GLB.")


if __name__ == "__main__":
    main()
