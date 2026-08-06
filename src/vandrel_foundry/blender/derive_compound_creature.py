"""Bounded Blender adapter for mesh-to-donor-rig binding."""

import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector
from mathutils.kdtree import KDTree

sys.path.insert(0, str(Path(__file__).parents[2]))

from vandrel_foundry.domain.creature_retarget import (
    require_bind_preserved,
    resolve_semantic_bones,
    validate_finite_transform,
    validate_required_clip_families,
)


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
    if not {path.resolve() for path in material_paths}.issubset(imported_image_paths):
        _bind_material_dependencies(source_meshes, material_paths)
        imported_image_paths = {
            Path(bpy.path.abspath(image.filepath)).resolve()
            for image in bpy.data.images
            if image.filepath
        }
    missing_materials = [path for path in material_paths if path.resolve() not in imported_image_paths]
    if missing_materials:
        raise RuntimeError(f"Declared material dependencies are not used: {missing_materials}")
    source_armatures = [item for item in bpy.context.scene.objects if item.type == "ARMATURE"]
    if len(source_armatures) != 1:
        raise RuntimeError("Mesh source must contain exactly one native armature.")
    source_armature = source_armatures[0]
    if not all(
        any(modifier.type == "ARMATURE" and modifier.object == source_armature for modifier in item.modifiers)
        for item in source_meshes
    ):
        raise RuntimeError("Every source mesh must retain its native skin modifier.")
    bpy.context.scene.frame_set(1); bpy.context.view_layer.update()
    source_pose_baseline = {
        bone.name: bone.matrix_basis.copy() for bone in source_armature.pose.bones
    }
    bind_signature_before = _bind_signature(source_meshes, source_armature)
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
    clip_families = validate_required_clip_families([item.name for item in donor_actions])
    semantic = resolve_semantic_bones(
        [bone.name for bone in source_armature.data.bones],
        [bone.name for bone in donor.data.bones],
        {bone.name: bone.parent.name if bone.parent else None for bone in source_armature.data.bones},
        {bone.name: bone.parent.name if bone.parent else None for bone in donor.data.bones},
    )
    donor_meshes = [
        item for item in bpy.context.scene.objects
        if item.type == "MESH" and item not in source_objects
    ]
    retarget = _retarget_actions(
        source_armature, donor, donor_actions, semantic.roles, source_pose_baseline
    )
    for item in donor_meshes:
        bpy.data.objects.remove(item, do_unlink=True)
    bpy.data.objects.remove(donor, do_unlink=True)
    deformation_metrics = _deformation_metrics(
        source_meshes, source_armature, list(bpy.data.actions)
    )
    bind_signature_after = _bind_signature(source_meshes, source_armature)
    require_bind_preserved(bind_signature_before, bind_signature_after)
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
    source_armature.select_set(True)
    bpy.context.view_layer.objects.active = source_armature
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
                    "donor_armatures_retained": 0,
                    "source_armatures_retained": 1,
                    "source_armatures_removed": 0,
                    "donor_mesh_objects_removed": len(donor_meshes),
                    "binding_method": "semantic_rest_space_animation_retarget",
                    "donor_actions_retained": len(donor_actions),
                    "material_dependencies_declared": len(material_paths),
                    "material_dependencies_used": len(material_paths),
                    "output_skin_count": 1,
                    "output_animation_count": len(donor_actions),
                    "unweighted_exported_vertex_count": unweighted_vertex_count,
                    "semantic_bone_roles": {
                        role: {"source": values[0], "donor": values[1]}
                        for role, values in semantic.roles.items()
                    },
                    "unmapped_source_bones": list(semantic.unmapped_source),
                    "unmapped_donor_bones": list(semantic.unmapped_donor),
                    "clip_family_coverage": {
                        family: list(names) for family, names in clip_families.items()
                    },
                    "retarget": retarget,
                    "deformation_metrics": deformation_metrics,
                    "bind_signature_before": bind_signature_before,
                    "bind_signature_after": bind_signature_after,
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


def _retarget_actions(source, donor, donor_actions, roles, baseline) -> dict[str, object]:
    source.animation_data_create(); donor.animation_data_create()
    source_root, donor_root = roles["root"]
    source_head, donor_head = roles["head"]
    source_scale = _bone_distance(source, source_root, source_head)
    donor_scale = _bone_distance(donor, donor_root, donor_head)
    if source_scale <= 0 or donor_scale <= 0:
        raise RuntimeError("Retarget scale landmarks are degenerate.")
    translation_scale = source_scale / donor_scale
    ordered = sorted(roles.items(), key=lambda item: _bone_depth(source.data.bones[item[1][0]]))
    baked = []; output_actions = []
    for donor_action in sorted(donor_actions, key=lambda item: item.name.casefold()):
        donor.animation_data.action = donor_action
        output_action = bpy.data.actions.new(donor_action.name)
        output_actions.append((output_action, donor_action.name))
        source.animation_data.action = output_action
        start = math.floor(donor_action.frame_range[0])
        end = max(start, math.ceil(donor_action.frame_range[1]))
        for frame in range(start, end + 1):
            bpy.context.scene.frame_set(frame); bpy.context.view_layer.update()
            for pose_bone in source.pose.bones:
                pose_bone.matrix_basis = baseline[pose_bone.name]
            for role, (source_name, donor_name) in ordered:
                source_pose = source.pose.bones[source_name]
                donor_pose = donor.pose.bones[donor_name]
                source_rest = source.data.bones[source_name].matrix_local.to_quaternion()
                donor_rest = donor.data.bones[donor_name].matrix_local.to_quaternion()
                donor_basis = donor_pose.matrix_basis.to_quaternion()
                converted = (
                    source_rest.inverted() @ donor_rest @ donor_basis
                    @ donor_rest.inverted() @ source_rest
                )
                try:
                    validate_finite_transform((*converted, *donor_pose.scale, *donor_pose.location))
                except Exception as exc:
                    raise RuntimeError(
                        f"Retarget produced a nonfinite transform in {donor_action.name}:{donor_name}:{frame}"
                    ) from exc
                baseline_matrix = baseline[source_name]
                source_pose.rotation_mode = "QUATERNION"
                source_pose.rotation_quaternion = baseline_matrix.to_quaternion() @ converted
                source_pose.scale = Vector(tuple(
                    baseline_matrix.to_scale()[index] * donor_pose.scale[index]
                    for index in range(3)
                ))
                source_pose.location = baseline_matrix.to_translation()
                if role == "root":
                    world_motion = donor_rest @ donor_pose.location
                    source_pose.location += (
                        source_rest.inverted() @ world_motion * translation_scale
                    )
                source_pose.keyframe_insert("rotation_quaternion", frame=frame, group=source_name)
                source_pose.keyframe_insert("location", frame=frame, group=source_name)
                source_pose.keyframe_insert("scale", frame=frame, group=source_name)
        baked.append({"name": donor_action.name, "frame_range": [start, end]})
    donor.animation_data.action = None
    for donor_action in donor_actions:
        bpy.data.actions.remove(donor_action)
    for output_action, exact_name in output_actions:
        output_action.name = exact_name
    source.animation_data.action = None
    for pose_bone in source.pose.bones:
        pose_bone.matrix_basis = baseline[pose_bone.name]
    bpy.context.scene.frame_set(0); bpy.context.view_layer.update()
    return {
        "space": "rest_local_rotation_delta",
        "source_pose_baseline": "imported_native_frame_1_matrix_basis",
        "scale_landmarks": {"source": [source_root, source_head], "donor": [donor_root, donor_head]},
        "translation_scale": translation_scale,
        "root_motion_policy": "scaled_root_translation_only",
        "nonroot_translation_policy": "zero",
        "clips": baked,
    }


def _bone_distance(armature, first: str, second: str) -> float:
    return (armature.data.bones[second].head_local - armature.data.bones[first].head_local).length


def _bone_depth(bone) -> int:
    depth = 0
    while bone.parent is not None:
        depth += 1; bone = bone.parent
    return depth


def _bind_signature(meshes, armature) -> str:
    value = {
        "armature": armature.name,
        "armature_matrix": [float(value) for row in armature.matrix_world for value in row],
        "bones": [
            {
                "name": bone.name,
                "parent": bone.parent.name if bone.parent else None,
                "matrix": [float(value) for row in bone.matrix_local for value in row],
            }
            for bone in armature.data.bones
        ],
        "meshes": [
            {
                "name": item.name,
                "matrix": [float(value) for row in item.matrix_world for value in row],
                "vertices": [[float(value) for value in vertex.co] for vertex in item.data.vertices],
                "groups": [group.name for group in item.vertex_groups],
                "weights": [
                    [[membership.group, float(membership.weight)] for membership in vertex.groups]
                    for vertex in item.data.vertices
                ],
                "armature_modifiers": [
                    modifier.object.name if modifier.object else None
                    for modifier in item.modifiers if modifier.type == "ARMATURE"
                ],
            }
            for item in meshes
        ],
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _deformation_metrics(meshes, armature, actions) -> list[dict[str, object]]:
    values = []
    armature.animation_data_create()
    for action in sorted(actions, key=lambda item: item.name.casefold()):
        armature.animation_data.action = action
        start = math.floor(action.frame_range[0]); end = max(start, math.ceil(action.frame_range[1]))
        frames = sorted({start, (start + end) // 2, end})
        samples = []
        for frame in frames:
            bpy.context.scene.frame_set(frame); bpy.context.view_layer.update()
            graph = bpy.context.evaluated_depsgraph_get(); points = []
            for item in meshes:
                evaluated = item.evaluated_get(graph); mesh = evaluated.to_mesh()
                try:
                    points.extend(evaluated.matrix_world @ vertex.co for vertex in mesh.vertices)
                finally:
                    evaluated.to_mesh_clear()
            validate_finite_transform([coordinate for point in points for coordinate in point])
            samples.append(points)
        if any(len(sample) != len(samples[0]) for sample in samples):
            raise RuntimeError(f"Deformation vertex count changed in clip {action.name}.")
        minimum = Vector(tuple(min(point[index] for point in samples[0]) for index in range(3)))
        maximum = Vector(tuple(max(point[index] for point in samples[0]) for index in range(3)))
        bind_extent = max(maximum - minimum)
        maximum_displacement = max(
            (point - samples[0][index]).length
            for sample in samples[1:]
            for index, point in enumerate(sample)
        )
        if maximum_displacement <= max(bind_extent * 0.00001, 1e-9):
            raise RuntimeError(f"Retargeted clip has no measurable deformation: {action.name}")
        if maximum_displacement > bind_extent * 10:
            raise RuntimeError(f"Retargeted clip deformation is unbounded: {action.name}")
        values.append({
            "name": action.name,
            "sample_frames": frames,
            "vertex_count": len(samples[0]),
            "baseline_extent": bind_extent,
            "maximum_sampled_displacement": maximum_displacement,
        })
    armature.animation_data.action = None
    return values


def _align_to_donor_rest(source_meshes, donor_reference) -> dict[str, object]:
    for item in source_meshes:
        item.data.transform(item.matrix_world)
        item.matrix_world = Matrix.Identity(4)
    source_minimum, source_maximum = _object_bounds(source_meshes)
    donor_minimum, donor_maximum = _object_bounds([donor_reference])
    source_extent = source_maximum - source_minimum
    donor_extent = donor_maximum - donor_minimum
    if min(source_extent) <= 0 or min(donor_extent) <= 0:
        raise RuntimeError("Creature rest alignment requires nonzero three-axis bounds.")
    scales = Vector(tuple(donor_extent[index] / source_extent[index] for index in range(3)))
    for item in source_meshes:
        for vertex in item.data.vertices:
            vertex.co = Vector(tuple(
                donor_minimum[index] + (vertex.co[index] - source_minimum[index]) * scales[index]
                for index in range(3)
            ))
        item.data.update()
    aligned_minimum, aligned_maximum = _object_bounds(source_meshes)
    return {
        "method": "axis_bounds_to_largest_donor_mesh",
        "donor_reference_object": donor_reference.name,
        "source_bounds_before": [list(source_minimum), list(source_maximum)],
        "donor_bounds": [list(donor_minimum), list(donor_maximum)],
        "axis_scales": list(scales),
        "source_bounds_after": [list(aligned_minimum), list(aligned_maximum)],
    }


def _freeze_source_visible_pose(source_meshes) -> dict[str, object]:
    """Bake the imported FBX's evaluated pose before removing its source rig."""
    scene = bpy.context.scene
    scene.frame_set(scene.frame_current)
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get()
    for item in source_meshes:
        evaluated = item.evaluated_get(graph)
        baked = bpy.data.meshes.new_from_object(
            evaluated, preserve_all_data_layers=True, depsgraph=graph
        )
        previous = item.data
        item.data = baked
        item.data.transform(item.matrix_world)
        item.matrix_world = Matrix.Identity(4)
        item.parent = None
        if previous.users == 0:
            bpy.data.meshes.remove(previous)
    return {
        "method": "evaluated_source_pose_to_static_mesh",
        "source_frame": scene.frame_current,
        "mesh_objects_baked": len(source_meshes),
    }


def _object_bounds(objects):
    points = [
        item.matrix_world @ vertex.co
        for item in objects
        for vertex in item.data.vertices
    ]
    if not points:
        raise RuntimeError("Creature rest alignment has no geometry bounds.")
    return (
        Vector(tuple(min(point[index] for point in points) for index in range(3))),
        Vector(tuple(max(point[index] for point in points) for index in range(3))),
    )


def _transfer_donor_skin(source_meshes, donor_reference, donor) -> None:
    donor_groups = [group.name for group in donor_reference.vertex_groups]
    if not donor_groups:
        raise RuntimeError("Donor reference geometry has no skin weights.")
    tree = KDTree(len(donor_reference.data.vertices))
    for vertex in donor_reference.data.vertices:
        tree.insert(donor_reference.matrix_world @ vertex.co, vertex.index)
    tree.balance()
    for item in source_meshes:
        for name in donor_groups:
            item.vertex_groups.new(name=name)
        for vertex in item.data.vertices:
            _, donor_index, _ = tree.find(item.matrix_world @ vertex.co)
            donor_vertex = donor_reference.data.vertices[donor_index]
            for membership in donor_vertex.groups:
                item.vertex_groups[membership.group].add(
                    [vertex.index], membership.weight, "REPLACE"
                )


def _replace_donor_geometry(source_meshes, donor_reference):
    if len(source_meshes) != 1:
        raise RuntimeError("Compound creature adapter currently requires one primary mesh object.")
    source = source_meshes[0]
    assignments = {
        group.name: [
            (vertex.index, membership.weight)
            for vertex in source.data.vertices
            for membership in vertex.groups
            if membership.group == group.index
        ]
        for group in source.vertex_groups
    }
    previous = donor_reference.data
    donor_reference.data = source.data
    donor_reference.vertex_groups.clear()
    for name, values in assignments.items():
        group = donor_reference.vertex_groups.new(name=name)
        for vertex_index, weight in values:
            group.add([vertex_index], weight, "REPLACE")
    bpy.data.objects.remove(source, do_unlink=True)
    if previous.users == 0:
        bpy.data.meshes.remove(previous)
    return donor_reference


def _bind_material_dependencies(meshes, paths: list[Path]) -> None:
    materials = [material for mesh in meshes for material in mesh.data.materials if material]
    if not materials:
        material = bpy.data.materials.new("FoundryCreatureMaterial")
        meshes[0].data.materials.append(material); materials = [material]
    for material in materials:
        material.use_nodes = True
        nodes = material.node_tree.nodes; links = material.node_tree.links
        shader = nodes.get("Principled BSDF")
        if shader is None:
            raise RuntimeError("Creature material has no Principled BSDF node.")
        for path in paths:
            image = bpy.data.images.load(str(path), check_existing=True)
            texture = nodes.new("ShaderNodeTexImage"); texture.image = image
            name = path.stem.casefold()
            if "normal" in name:
                image.colorspace_settings.name = "Non-Color"
                normal = nodes.new("ShaderNodeNormalMap")
                links.new(texture.outputs["Color"], normal.inputs["Color"])
                links.new(normal.outputs["Normal"], shader.inputs["Normal"])
            elif "metallic" in name:
                image.colorspace_settings.name = "Non-Color"
                links.new(texture.outputs["Color"], shader.inputs["Metallic"])
            elif "roughness" in name:
                image.colorspace_settings.name = "Non-Color"
                links.new(texture.outputs["Color"], shader.inputs["Roughness"])
            else:
                links.new(texture.outputs["Color"], shader.inputs["Base Color"])


if __name__ == "__main__":
    main()
