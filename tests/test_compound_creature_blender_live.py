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
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(); mesh=bpy.context.object; mesh.name='CreatureMesh'
image=bpy.data.images.new('fur', width=2, height=2); image.filepath_raw=str(root/'fur.png')
image.file_format='PNG'; image.save()
mat=bpy.data.materials.new('CreatureMaterial'); mat.use_nodes=True
texture=mat.node_tree.nodes.new('ShaderNodeTexImage'); texture.image=image
mat.node_tree.links.new(texture.outputs['Color'], mat.node_tree.nodes.get('Principled BSDF').inputs['Base Color'])
mesh.data.materials.append(mat)
bpy.ops.export_scene.fbx(filepath=str(root/'mesh.fbx'), use_selection=False)
bpy.ops.wm.read_factory_settings(use_empty=True)
arm_data=bpy.data.armatures.new('DonorRig'); arm=bpy.data.objects.new('DonorRig',arm_data)
bpy.context.collection.objects.link(arm); bpy.context.view_layer.objects.active=arm; arm.select_set(True)
bpy.ops.object.mode_set(mode='EDIT'); root_bone=arm_data.edit_bones.new('root')
root_bone.head=Vector((0,0,0)); root_bone.tail=Vector((0,0,1)); child=arm_data.edit_bones.new('spine')
child.head=root_bone.tail; child.tail=Vector((0,0,2)); child.parent=root_bone
bpy.ops.object.mode_set(mode='POSE'); pose_bone=arm.pose.bones['root']
bpy.context.scene.frame_set(1); pose_bone.location.x=0; pose_bone.keyframe_insert('location')
bpy.context.scene.frame_set(20); pose_bone.location.x=0.2; pose_bone.keyframe_insert('location')
bpy.ops.object.mode_set(mode='OBJECT')
bpy.ops.export_scene.gltf(filepath=str(root/'donor.glb'), export_format='GLB', export_animations=True)
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
    assert inspection.skin_count == 1 and inspection.joint_count == 2
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
