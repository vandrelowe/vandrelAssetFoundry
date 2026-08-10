"""Normalize one Meshy-native merged animation FBX without changing its native rig."""

import hashlib
import json
import math
import re
import struct
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

EXPECTED_HIERARCHY = {
    "Hips": None,
    "LeftUpLeg": "Hips",
    "LeftLeg": "LeftUpLeg",
    "LeftFoot": "LeftLeg",
    "LeftToeBase": "LeftFoot",
    "RightUpLeg": "Hips",
    "RightLeg": "RightUpLeg",
    "RightFoot": "RightLeg",
    "RightToeBase": "RightFoot",
    "Spine02": "Hips",
    "Spine01": "Spine02",
    "Spine": "Spine01",
    "LeftShoulder": "Spine",
    "LeftArm": "LeftShoulder",
    "LeftForeArm": "LeftArm",
    "LeftHand": "LeftForeArm",
    "RightShoulder": "Spine",
    "RightArm": "RightShoulder",
    "RightForeArm": "RightArm",
    "RightHand": "RightForeArm",
    "neck": "Spine",
    "Head": "neck",
    "head_end": "Head",
    "headfront": "Head",
}
UUID_ACTION = re.compile(
    r"^target_character\|[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def main() -> None:
    values = sys.argv[sys.argv.index("--") + 1 :]
    if len(values) != 4:
        raise RuntimeError("Expected source FBX, combined GLB, split directory, and report JSON.")
    source, combined_output, split_directory, report_path = map(Path, values)
    split_directory.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(source), use_anim=True)
    scene = bpy.context.scene
    scene.render.fps = 30
    armatures = [item for item in scene.objects if item.type == "ARMATURE"]
    if len(armatures) != 1:
        raise RuntimeError(f"Expected one Meshy armature, found {len(armatures)}.")
    armature = armatures[0]
    hierarchy = {
        bone.name: bone.parent.name if bone.parent else None for bone in armature.data.bones
    }
    if hierarchy != EXPECTED_HIERARCHY:
        missing = sorted(set(EXPECTED_HIERARCHY) - set(hierarchy))
        extra = sorted(set(hierarchy) - set(EXPECTED_HIERARCHY))
        changed = sorted(
            name
            for name in set(hierarchy) & set(EXPECTED_HIERARCHY)
            if hierarchy[name] != EXPECTED_HIERARCHY[name]
        )
        raise RuntimeError(
            f"Meshy 24-joint hierarchy mismatch; missing={missing}, extra={extra}, changed={changed}."
        )
    meshes = [
        item
        for item in scene.objects
        if item.type == "MESH"
        and any(mod.type == "ARMATURE" and mod.object == armature for mod in item.modifiers)
    ]
    if not meshes or any(
        not any(mod.type == "ARMATURE" and mod.object == armature for mod in item.modifiers)
        for item in meshes
    ):
        raise RuntimeError("Meshy source must retain native skinned geometry.")
    unweighted = sum(
        1
        for item in meshes
        for vertex in item.data.vertices
        if not vertex.groups or sum(group.weight for group in vertex.groups) <= 0.0
    )
    if unweighted:
        raise RuntimeError(f"Meshy source has {unweighted} unweighted exported vertices.")
    if not any(slot.material is not None for item in meshes for slot in item.material_slots):
        raise RuntimeError("Meshy source has no material.")
    source_actions = list(bpy.data.actions)
    if len(source_actions) != 10 or len({item.name for item in source_actions}) != 10:
        raise RuntimeError("Meshy package must contain exactly ten unique actions.")
    if not {"target_character|Running", "target_character|Walking"}.issubset(
        {item.name for item in source_actions}
    ):
        raise RuntimeError("Meshy package is missing the named Running or Walking loop.")

    bind_before = _bind_signature(meshes, armature)
    rotation = Matrix.Rotation(math.radians(90.0), 4, "X")
    normalization_root = bpy.data.objects.new("MeshyNativeAxisNormalization", None)
    scene.collection.objects.link(normalization_root)
    normalization_root.matrix_world = rotation
    if any(item.parent != armature for item in meshes):
        raise RuntimeError("Every Meshy native skin must retain the armature as object parent.")
    armature_local_matrix = armature.matrix_world.copy()
    armature.parent = normalization_root
    armature.matrix_parent_inverse = Matrix.Identity(4)
    armature.matrix_basis = armature_local_matrix
    bpy.context.view_layer.update()
    normalized_actions, root_facts = _reconcile_actions(scene, meshes, armature, source_actions)
    bind_after = _bind_signature(meshes, armature)
    if bind_before != bind_after:
        raise RuntimeError("Meshy skin weights or bind/rest relationship changed.")

    metrics = _clip_metrics(scene, meshes, armature, normalized_actions, root_facts)
    _select_only([armature, *meshes])
    _export(combined_output, "ACTIONS")
    split_outputs = []
    for index, action in enumerate(normalized_actions, start=1):
        armature.animation_data.action = action
        destination = split_directory / f"{index:02d}-{_slug(action.name)}.glb"
        _export(destination, "ACTIVE_ACTIONS")
        _rename_single_glb_animation(destination, action.name)
        split_outputs.append({"name": action.name, "file": destination.name})
    armature.animation_data.action = None
    report_path.write_text(
        json.dumps(
            {
                "schema": "vandrel_foundry_meshy_native_blender_adapter/1.0",
                "tool_version": bpy.app.version_string,
                "transformation_facts": {
                    "source_armatures_retained": 1,
                    "source_joint_count": len(armature.data.bones),
                    "source_mesh_count": len(meshes),
                    "source_material_count": sum(
                        slot.material is not None for item in meshes for slot in item.material_slots
                    ),
                    "source_action_count": len(source_actions),
                    "output_action_count": len(normalized_actions),
                    "unweighted_exported_vertex_count": unweighted,
                    "bind_signature_before": bind_before,
                    "bind_signature_after": bind_after,
                    "bind_preserved": True,
                    "global_normalization": "world_positive_90_degrees_x_y_up_to_z_up",
                    "normalization_root_strategy": "parent_space_exported_on_armature_root",
                    "rest_axis_policy": "preserve_native_bone_rest_matrices",
                    "root_motion_policy": (
                        "subtract_per_clip_hips_frame_start_and_raise_clip_minimum_ground_to_z_zero"
                    ),
                    "semantic_policy": "retain_exact_action_names_and_unresolved_uuids",
                    "unresolved_uuid_action_count": sum(
                        1 for action in normalized_actions if UUID_ACTION.fullmatch(action.name)
                    ),
                },
                "clips": metrics,
                "split_outputs": split_outputs,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _reconcile_actions(scene, meshes, armature, source_actions):
    armature.animation_data_create()
    output_actions = []
    root_facts = {}
    for source_action in sorted(source_actions, key=lambda item: item.name.casefold()):
        armature.animation_data.action = source_action
        start = math.floor(source_action.frame_range[0])
        end = max(start, math.ceil(source_action.frame_range[1]))
        scene.frame_set(start)
        bpy.context.view_layer.update()
        root = armature.pose.bones["Hips"]
        baseline = root.location.copy()
        output_action = bpy.data.actions.new(f"__normalized__{source_action.name}")
        for frame in range(start, end + 1):
            armature.animation_data.action = source_action
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            matrices = {bone.name: bone.matrix_basis.copy() for bone in armature.pose.bones}
            armature.animation_data.action = output_action
            for bone in armature.pose.bones:
                bone.rotation_mode = "QUATERNION"
                bone.matrix_basis = matrices[bone.name]
                if bone.name == "Hips":
                    bone.location -= baseline
                _require_finite(
                    [*bone.location, *bone.rotation_quaternion, *bone.scale],
                    f"{source_action.name}:{bone.name}:{frame}",
                )
                bone.keyframe_insert("location", frame=frame, group=bone.name)
                bone.keyframe_insert("rotation_quaternion", frame=frame, group=bone.name)
                bone.keyframe_insert("scale", frame=frame, group=bone.name)
        armature.animation_data.action = output_action
        ground_before = math.inf
        for frame in range(start, end + 1):
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            ground_before = min(ground_before, float(_bounds(meshes)[0].z))
        world_shift = Vector((0.0, 0.0, -ground_before))
        root_location_correction = (
            root.bone.matrix_local.to_3x3().inverted()
            @ armature.matrix_world.to_3x3().inverted()
            @ world_shift
        )
        for frame in range(start, end + 1):
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            root.location += root_location_correction
            root.keyframe_insert("location", frame=frame, group=root.name)
        root_facts[output_action.name] = {
            "source_name": source_action.name,
            "frame_range": [start, end],
            "baseline": [float(value) for value in baseline],
            "clip_ground_minimum_before_correction_z": ground_before,
            "root_ground_correction": [float(value) for value in root_location_correction],
        }
        output_actions.append(output_action)
    armature.animation_data.action = None
    for action in source_actions:
        bpy.data.actions.remove(action)
    for action in output_actions:
        original_name = root_facts[action.name]["source_name"]
        action.name = original_name
        root_facts[original_name] = root_facts.pop(f"__normalized__{original_name}")
    return output_actions, root_facts


def _clip_metrics(scene, meshes, armature, actions, root_facts):
    values = []
    for action in actions:
        armature.animation_data.action = action
        start, end = root_facts[action.name]["frame_range"]
        frames = list(range(start, end + 1))
        sampled = sorted({start, (start + end) // 2, end})
        ground_values = []
        root_positions = []
        baseline_points = None
        maximum_displacement = 0.0
        endpoint_basis = []
        for frame in frames:
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            minimum, _ = _bounds(meshes)
            ground_values.append(float(minimum.z))
            root_positions.append(armature.matrix_world @ armature.pose.bones["Hips"].head)
            if frame in sampled:
                points = _evaluated_points(meshes)
                if baseline_points is None:
                    baseline_points = points
                else:
                    maximum_displacement = max(
                        maximum_displacement,
                        max(
                            (point - baseline_points[index]).length
                            for index, point in enumerate(points)
                        ),
                    )
            if frame in {start, end}:
                endpoint_basis.append(
                    [
                        float(value)
                        for bone in armature.pose.bones
                        for row in bone.matrix_basis
                        for value in row
                    ]
                )
        if maximum_displacement <= 1e-8 or not math.isfinite(maximum_displacement):
            raise RuntimeError(f"Clip has no finite measurable deformation: {action.name}.")
        extent = max(_bounds(meshes)[1] - _bounds(meshes)[0])
        if maximum_displacement > extent * 10:
            raise RuntimeError(f"Clip deformation is unbounded: {action.name}.")
        displacement = (root_positions[-1] - root_positions[0]).length
        endpoint_matrix_max_delta = max(
            abs(first - last)
            for first, last in zip(endpoint_basis[0], endpoint_basis[1], strict=True)
        )
        loop_match = endpoint_matrix_max_delta <= 0.02
        if action.name.endswith(("|Running", "|Walking")) and not loop_match:
            raise RuntimeError(
                f"Named locomotion clip does not close: {action.name} "
                f"(matrix delta {endpoint_matrix_max_delta})."
            )
        values.append(
            {
                "exact_name": action.name,
                "frame_range": [start, end],
                "duration_seconds": (end - start) / 30.0,
                "root_baseline": root_facts[action.name]["baseline"],
                "root_displacement": float(displacement),
                "sampled_ground_minimum_range": [min(ground_values), max(ground_values)],
                "maximum_sampled_vertex_displacement": float(maximum_displacement),
                "endpoint_loop_match": loop_match,
                "endpoint_matrix_max_delta": float(endpoint_matrix_max_delta),
                "semantic_status": (
                    "unresolved_uuid" if UUID_ACTION.fullmatch(action.name) else "provider_named"
                ),
                "semantic_assessment": _semantic_assessment(action.name),
            }
        )
    armature.animation_data.action = None
    return values


def _semantic_assessment(name: str) -> str:
    if name.endswith("|Running"):
        return "locomotion_running"
    if name.endswith("|Walking"):
        return "locomotion_walking"
    if UUID_ACTION.fullmatch(name):
        return "unresolved"
    if "Pick_Fruit" in name or "Pick_Put" in name:
        return "foraging_not_eating"
    return "not_butchery" if "Red_Carpet" in name else "other"


def _export(destination: Path, mode: str) -> None:
    bpy.ops.export_scene.gltf(
        filepath=str(destination),
        export_format="GLB",
        use_selection=True,
        export_animations=True,
        export_animation_mode=mode,
        export_anim_slide_to_zero=False,
        export_skins=True,
        export_materials="EXPORT",
    )
    if not destination.is_file():
        raise RuntimeError(f"glTF exporter did not create {destination}.")


def _rename_single_glb_animation(path: Path, exact_name: str) -> None:
    value = path.read_bytes()
    if len(value) < 20:
        raise RuntimeError("Split GLB is truncated.")
    magic, version, declared_length = struct.unpack_from("<4sII", value, 0)
    if magic != b"glTF" or version != 2 or declared_length != len(value):
        raise RuntimeError("Split output is not a valid GLB 2.0 container.")
    offset = 12
    chunks = []
    while offset < len(value):
        if offset + 8 > len(value):
            raise RuntimeError("Split GLB chunk header is truncated.")
        length, chunk_type = struct.unpack_from("<II", value, offset)
        offset += 8
        chunk = value[offset : offset + length]
        if len(chunk) != length:
            raise RuntimeError("Split GLB chunk is truncated.")
        chunks.append((chunk_type, chunk))
        offset += length
    if not chunks or chunks[0][0] != 0x4E4F534A:
        raise RuntimeError("Split GLB has no leading JSON chunk.")
    document = json.loads(chunks[0][1].rstrip(b" \t\r\n\x00").decode("utf-8"))
    animations = document.get("animations")
    if not isinstance(animations, list) or len(animations) != 1:
        raise RuntimeError("Split GLB does not contain exactly one animation.")
    animations[0]["name"] = exact_name
    payload = json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    payload += b" " * (-len(payload) % 4)
    rewritten = [(0x4E4F534A, payload), *chunks[1:]]
    total = 12 + sum(8 + len(chunk) for _, chunk in rewritten)
    output = bytearray(struct.pack("<4sII", b"glTF", 2, total))
    for chunk_type, chunk in rewritten:
        output.extend(struct.pack("<II", len(chunk), chunk_type))
        output.extend(chunk)
    path.write_bytes(output)


def _select_only(objects) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    for item in objects:
        item.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]


def _bind_signature(meshes, armature) -> str:
    value = {
        "bones": [
            {
                "name": bone.name,
                "parent": bone.parent.name if bone.parent else None,
                "matrix_local": [float(value) for row in bone.matrix_local for value in row],
            }
            for bone in armature.data.bones
        ],
        "meshes": [
            {
                "name": item.name,
                "vertices": [[float(value) for value in vertex.co] for vertex in item.data.vertices],
                "groups": [group.name for group in item.vertex_groups],
                "weights": [
                    [[membership.group, float(membership.weight)] for membership in vertex.groups]
                    for vertex in item.data.vertices
                ],
                "armature_modifiers": [
                    modifier.object.name if modifier.object else None
                    for modifier in item.modifiers
                    if modifier.type == "ARMATURE"
                ],
            }
            for item in meshes
        ],
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _bounds(meshes):
    points = _evaluated_points(meshes)
    return (
        Vector(tuple(min(point[index] for point in points) for index in range(3))),
        Vector(tuple(max(point[index] for point in points) for index in range(3))),
    )


def _evaluated_points(meshes):
    graph = bpy.context.evaluated_depsgraph_get()
    points = []
    for item in meshes:
        evaluated = item.evaluated_get(graph)
        mesh = evaluated.to_mesh()
        try:
            points.extend(evaluated.matrix_world @ vertex.co for vertex in mesh.vertices)
        finally:
            evaluated.to_mesh_clear()
    if not points:
        raise RuntimeError("Meshy native canary has no evaluated vertices.")
    _require_finite(
        [coordinate for point in points for coordinate in point], "evaluated geometry"
    )
    return points


def _require_finite(values, context: str) -> None:
    if any(not math.isfinite(float(value)) for value in values):
        raise RuntimeError(f"Nonfinite transform detected in {context}.")


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


if __name__ == "__main__":
    main()
