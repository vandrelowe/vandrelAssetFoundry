"""Assemble normalized Meshy-native actions onto one exact native character rig."""

import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def main() -> None:
    values = sys.argv[sys.argv.index("--") + 1 :]
    if len(values) != 6:
        raise RuntimeError(
            "Expected character FBX, texture PNG, canary GLB, top-four reference GLB, "
            "output GLB, and report JSON."
        )
    (
        character_path,
        texture_path,
        canary_path,
        reference_path,
        output_path,
        report_path,
    ) = map(Path, values)
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
    source_actions = sorted(bpy.data.actions, key=lambda item: item.name.casefold())
    if len(source_actions) != 10 or len({item.name for item in source_actions}) != 10:
        raise RuntimeError("Canary motion model must contain exactly ten unique actions.")
    scale_ratio = _rig_scale(target) / _rig_scale(source)
    transferred = []
    clip_facts = []
    for source_action in source_actions:
        action, facts = _transfer_action(
            scene, source, target, target_meshes, source_action, scale_ratio
        )
        transferred.append(action)
        clip_facts.append(facts)

    for item in imported:
        bpy.data.objects.remove(item, do_unlink=True)
    for action in source_actions:
        if action.name in bpy.data.actions:
            bpy.data.actions.remove(action)
    for action, facts in zip(transferred, clip_facts, strict=True):
        action.name = facts["exact_name"]
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
                "schema": "vandrel_foundry_meshy_native_character_assembly_adapter/2.0",
                "blender_version": bpy.app.version_string,
                "transformation_facts": {
                    "target_joint_count": len(target_hierarchy),
                    "source_joint_count": len(source_hierarchy),
                    "exact_native_joint_hierarchy_match": True,
                    "semantic_transfer_policy": "native_joint_identity_rest_space_delta",
                    "index_or_mixamo_graft": False,
                    "rest_rotation_max_delta_radians": rest_rotation_delta,
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
                    "root_motion_policy": (
                        "per_clip_xy_start_baseline_then_actual_target_mesh_ground_to_z_zero"
                    ),
                },
                "clips": clip_facts,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _transfer_action(scene, source, target, meshes, source_action, scale_ratio):
    source.animation_data_create()
    target.animation_data_create()
    source.animation_data.action = source_action
    start = math.floor(source_action.frame_range[0])
    end = max(start + 1, math.ceil(source_action.frame_range[1]))
    output = bpy.data.actions.new(f"__target__{source_action.name}")
    for frame in range(start, end + 1):
        source.animation_data.action = source_action
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        deltas = {
            bone.name: _retarget_basis(
                source.data.bones[bone.name],
                target.data.bones[bone.name],
                bone.matrix_basis,
                scale_ratio,
            )
            for bone in source.pose.bones
        }
        target.animation_data.action = output
        for bone in target.pose.bones:
            bone.rotation_mode = "QUATERNION"
            location, rotation, scale = deltas[bone.name]
            bone.location = location
            bone.rotation_quaternion = rotation
            bone.scale = scale
            _finite([*bone.location, *bone.rotation_quaternion, *bone.scale], bone.name)
            bone.keyframe_insert("location", frame=frame, group=bone.name)
            bone.keyframe_insert("rotation_quaternion", frame=frame, group=bone.name)
            bone.keyframe_insert("scale", frame=frame, group=bone.name)
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
    return output, {
        "exact_name": source_action.name,
        "frame_range": [start, end],
        "duration_seconds": (end - start) / 30.0,
        "root_xy_baseline": [float(baseline.x), float(baseline.y)],
        "ground_before_correction_z": ground_before,
        "ground_after_range_z": [min(ground_after), max(ground_after)],
        "maximum_sampled_vertex_displacement": deformation,
    }


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


def _retarget_basis(source_bone, target_bone, matrix_basis, scale_ratio):
    location, rotation, scale = matrix_basis.decompose()
    source_rest = _local_rest_rotation(source_bone)
    target_rest = _local_rest_rotation(target_bone)
    parent_space_rotation = source_rest @ rotation @ source_rest.inverted()
    mapped_rotation = target_rest.inverted() @ parent_space_rotation @ target_rest
    parent_space_location = source_rest @ location
    mapped_location = (target_rest.inverted() @ parent_space_location) * scale_ratio
    _finite([*mapped_location, *mapped_rotation, *scale], source_bone.name)
    return mapped_location, mapped_rotation, scale


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
