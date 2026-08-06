import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

from vandrel_foundry.domain.lanes import LaneConfiguration
from vandrel_foundry.domain.manifest import Artifact
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.derive_compound_creature import derive_compound_creature
from vandrel_foundry.services.inspect_glb import inspect_glb
from vandrel_foundry.services.validate_godot import run_bounded_process
from vandrel_foundry.storage.manifests import ManifestRepository


@pytest.mark.live_tool
def test_real_blender_adapter_output_is_independently_valid(
    tmp_path: Path, config, prompt: Path
) -> None:
    blender = Path("C:/Program Files (x86)/Steam/steamapps/common/Blender/blender.exe")
    if not blender.is_file():
        pytest.skip("Configured Blender executable is unavailable.")
    setup = tmp_path / "setup.py"
    mesh = tmp_path / "mesh.fbx"; donor = tmp_path / "donor.glb"
    texture = tmp_path / "fur.png"; output = tmp_path / "output.glb"
    adapter_report = tmp_path / "adapter.json"
    setup.write_text(
        """import bpy, sys
from pathlib import Path
from mathutils import Vector
root=Path(sys.argv[sys.argv.index('--')+1])
def make_rig(name, names, parents):
    data=bpy.data.armatures.new(name); arm=bpy.data.objects.new(name,data)
    bpy.context.collection.objects.link(arm); bpy.context.view_layer.objects.active=arm; arm.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT'); made={}
    for index,bone_name in enumerate(names):
        bone=data.edit_bones.new(bone_name); bone.head=Vector((0,0,index*.2)); bone.tail=bone.head+Vector((0,0,.15)); made[bone_name]=bone
    for child,parent in parents.items(): made[child].parent=made[parent]
    bpy.ops.object.mode_set(mode='OBJECT'); return arm
def add_skinned_cube(arm, root_name, material=None):
    bpy.ops.mesh.primitive_cube_add(location=(0,0,1)); mesh=bpy.context.object
    mesh.name='CreatureMesh'; group=mesh.vertex_groups.new(name=root_name)
    group.add(list(range(len(mesh.data.vertices))),1.0,'REPLACE')
    modifier=mesh.modifiers.new('NativeArmature','ARMATURE'); modifier.object=arm
    mesh.parent=arm; mesh.matrix_parent_inverse=arm.matrix_world.inverted()
    if material: mesh.data.materials.append(material)
    return mesh
source_names=['Hips','chest','head','tailstart','tail1','tail2','backleg','backleg0','backleg1','backleg2','R_backleg','R_backleg0','R_backleg1','R_backleg2','frontleg','frontleg0','frontleg1','R_frontleg','R_frontleg0','R_frontleg1']
source_parents={'chest':'Hips','head':'chest','tailstart':'Hips','tail1':'tailstart','tail2':'tail1','backleg0':'backleg','backleg1':'backleg0','backleg2':'backleg1','R_backleg0':'R_backleg','R_backleg1':'R_backleg0','R_backleg2':'R_backleg1','frontleg0':'frontleg','frontleg1':'frontleg0','R_frontleg0':'R_frontleg','R_frontleg1':'R_frontleg0'}
donor_names=['Body','Torso3','Head','Tail1','Tail2','Tail3','BackShoulder.L','BackLeg.L','BackUpperLeg.L','BackLowerLeg.L','BackShoulder.R','BackLeg.R','BackUpperLeg.R','BackLowerLeg.R','FrontShoulder.L','FrontUpperLeg.L','FrontLowerLeg.L','FrontShoulder.R','FrontUpperLeg.R','FrontLowerLeg.R']
donor_parents={'Torso3':'Body','Head':'Torso3','Tail1':'Body','Tail2':'Tail1','Tail3':'Tail2','BackLeg.L':'BackShoulder.L','BackUpperLeg.L':'BackLeg.L','BackLowerLeg.L':'BackUpperLeg.L','BackLeg.R':'BackShoulder.R','BackUpperLeg.R':'BackLeg.R','BackLowerLeg.R':'BackUpperLeg.R','FrontUpperLeg.L':'FrontShoulder.L','FrontLowerLeg.L':'FrontUpperLeg.L','FrontUpperLeg.R':'FrontShoulder.R','FrontLowerLeg.R':'FrontUpperLeg.R'}
bpy.ops.wm.read_factory_settings(use_empty=True); source_arm=make_rig('Armature',source_names,source_parents)
image=bpy.data.images.new('fur',width=2,height=2); image.filepath_raw=str(root/'fur.png'); image.file_format='PNG'; image.save()
mat=bpy.data.materials.new('CreatureMaterial'); mat.use_nodes=True; texture=mat.node_tree.nodes.new('ShaderNodeTexImage'); texture.image=image
mat.node_tree.links.new(texture.outputs['Color'],mat.node_tree.nodes.get('Principled BSDF').inputs['Base Color'])
add_skinned_cube(source_arm,'Hips',mat); source_arm.animation_data_create(); action=bpy.data.actions.new('Walking'); source_arm.animation_data.action=action
pose=source_arm.pose.bones['Hips']; pose.rotation_mode='XYZ'
for frame,angle in ((1,0.0),(10,.1),(20,0.0)): bpy.context.scene.frame_set(frame); pose.rotation_euler.x=angle; pose.keyframe_insert('rotation_euler')
bpy.ops.export_scene.fbx(filepath=str(root/'mesh.fbx'),use_selection=False)
bpy.ops.wm.read_factory_settings(use_empty=True); arm=make_rig('DonorRig',donor_names,donor_parents); add_skinned_cube(arm,'Body')
arm.animation_data_create(); pose=arm.pose.bones['Body']; pose.rotation_mode='XYZ'
for action_name in ['Idle','Eating','Walk','Gallop','Jump_toIdle','Idle_HitReact1','Attack_Kick','Death']:
    action=bpy.data.actions.new(action_name); arm.animation_data.action=action
    for frame,angle in ((0,0.0),(10,.15),(20,0.0)): bpy.context.scene.frame_set(frame); pose.rotation_euler.x=angle; pose.keyframe_insert('rotation_euler')
bpy.ops.export_scene.gltf(filepath=str(root/'donor.glb'),export_format='GLB',export_animations=True)
""",
        encoding="utf-8",
    )
    environment = {key: value for key, value in os.environ.items() if key.upper() in {
        "APPDATA", "HOME", "LOCALAPPDATA", "PATH", "SYSTEMDRIVE", "SYSTEMROOT",
        "TEMP", "TMP", "USERPROFILE", "WINDIR",
    }}
    setup_result = run_bounded_process(
        [str(blender), "--background", "--factory-startup", "--disable-autoexec",
         "--python-exit-code", "1", "--python", str(setup), "--", str(tmp_path)],
        tmp_path, environment, 120, 1_000_000,
    )
    assert setup_result.return_code == 0 and mesh.is_file() and donor.is_file(), (
        setup_result.stdout + setup_result.stderr
    )
    adapter = Path(__file__).parents[1] / "src" / "vandrel_foundry" / "blender" / "derive_compound_creature.py"
    result = run_bounded_process(
        [str(blender), "--background", "--factory-startup", "--disable-autoexec",
         "--python-exit-code", "1", "--python", str(adapter), "--", str(mesh),
         str(donor), str(output), str(adapter_report), str(texture)],
        tmp_path, environment, 120, 1_000_000,
    )
    assert result.return_code == 0, result.stderr
    inspection = inspect_glb(output)
    facts = json.loads(adapter_report.read_text(encoding="utf-8"))["transformation_facts"]
    assert inspection.mesh_count == 1 and inspection.material_count >= 1
    assert inspection.skin_count == 1 and inspection.joint_count >= 20
    assert inspection.animation_count >= 1
    assert facts["output_skin_count"] == inspection.skin_count
    assert facts["output_animation_count"] == inspection.animation_count
    assert facts["unweighted_exported_vertex_count"] == 0

    config.tools.blender_executable = blender
    lanes = LaneConfiguration.model_validate({"lanes": {"creature": {
        "wrapper_template": "creature_candidate", "collision_policy": "manual_review",
        "requires_materials": True, "requires_skeleton": True, "release_enabled": False,
    }}})
    manifest = create_asset(
        config, lanes, "live_compound_001", "creature", "Live Compound", prompt
    )
    asset_root = config.foundry.workspace_root / "assets" / "live_compound_001"
    roots = [
        ("mesh_001", mesh, "fbx"),
        ("fur_001", texture, "png"),
        ("rig_001", donor, "glb"),
    ]
    for artifact_id, source, format_name in roots:
        destination = asset_root / "source" / source.name
        shutil.copy2(source, destination)
        value = destination.read_bytes()
        manifest.artifacts.append(Artifact(
            artifact_id=artifact_id, role="source_contribution", stage="source",
            format=format_name, path=f"source/{source.name}",
            sha256=hashlib.sha256(value).hexdigest(), size_bytes=len(value),
        ))
    manifest.workflow.state = WorkflowState.DOWNLOADED
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest.revision += 1
    repository.save(manifest, expected_revision=manifest.revision - 1)
    service_result = derive_compound_creature(
        config,
        "live_compound_001",
        [
            ("mesh_material_source", "mesh_001"),
            ("material_dependency", "fur_001"),
            ("rig_animation_donor", "rig_001"),
        ],
    )
    live = repository.load("live_compound_001")
    assert live.artifacts[-2].artifact_id == service_result.model.artifact_id
    assert inspect_glb(asset_root / service_result.model.path).animation_count >= 1
