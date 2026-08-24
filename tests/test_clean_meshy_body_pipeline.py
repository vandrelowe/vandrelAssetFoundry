import hashlib
import json
import shutil
import struct
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from tests.conftest import bind_approved_test_scale, bind_documented_test_custody
from tests.test_audit_library import _write_v2_animation_library
from vandrel_foundry.cli import app
from vandrel_foundry.domain.clean_meshy_body import (
    CLEAN_BODY_CAMERA_CONFIG_SHA256,
    CleanBodyVisualReviewRequest,
)
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, utc_now
from vandrel_foundry.domain.release_descriptor import ReleaseDescriptorV2
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.domain.workflow_policy import (
    approval_artifact_bindings,
    approval_artifact_roles,
    approval_checks_pass,
)
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.import_clean_meshy_body_visual_review import (
    import_clean_meshy_body_visual_review,
)
from vandrel_foundry.services.plan_release import plan_release
from vandrel_foundry.services.process_clean_meshy_body import (
    _blender_diagnostic_schema,
    _derive_gltf_facts,
    process_clean_meshy_body,
)
from vandrel_foundry.services.run_animation_visual_capture import CaptureProcessResult
from vandrel_foundry.services.run_clean_meshy_body_godot import run_monitored_clean_body
from vandrel_foundry.services.validate_clean_meshy_body import (
    CleanBodyValidationExecution,
    _remove_scratch_tree,
    _validate_monitor,
    validate_clean_meshy_body,
)
from vandrel_foundry.storage.manifests import ManifestRepository


def test_scratch_cleanup_retries_a_transient_windows_cache_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scratch = tmp_path / "sandbox"
    (scratch / ".godot/editor").mkdir(parents=True)
    (scratch / ".godot/editor/cache").write_text("transient", encoding="utf-8")
    actual_rmtree = shutil.rmtree
    attempts = 0

    def flaky_rmtree(path: Path) -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OSError(145, "directory is not empty")
        actual_rmtree(path)

    monkeypatch.setattr(
        "vandrel_foundry.services.validate_clean_meshy_body.shutil.rmtree",
        flaky_rmtree,
    )
    monkeypatch.setattr(
        "vandrel_foundry.services.validate_clean_meshy_body.time.sleep", lambda _: None
    )

    _remove_scratch_tree(scratch)

    assert attempts == 3
    assert not scratch.exists()


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _source_candidate(config, humanoid_lanes, prompt, tmp_path):
    create_asset(config, humanoid_lanes, "clean_body_test_001", "humanoid", "Clean", prompt)
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load("clean_body_test_001")
    root = repository.asset_directory("clean_body_test_001")
    package = root / "source/clean_meshy_body_package_001"; package.mkdir(parents=True)
    values = {"body.fbx": b"rest body", "albedo.png": b"texture", "intake-report.json": json.dumps({"forbidden_output_sha256s":["d"*64]}).encode()}
    specs = (("body","clean_meshy_body_fbx","fbx"),("albedo","clean_meshy_body_albedo","png"),("intake","clean_meshy_body_intake_report","json"))
    for (stem, role, fmt), (name, payload) in zip(specs, values.items(), strict=True):
        (package/name).write_bytes(payload); manifest.artifacts.append(Artifact(artifact_id=f"{stem}_001", role=role, stage="source", format=fmt, path=f"source/clean_meshy_body_package_001/{name}", sha256=_sha(payload), size_bytes=len(payload), derived_from=["archive_001"]))
    manifest.workflow.state = WorkflowState.DOWNLOADED; manifest.revision += 1
    repository.save(manifest, "test.clean_body_source", expected_revision=manifest.revision-1)


def _processed(config, humanoid_lanes, prompt, tmp_path):
    _source_candidate(config, humanoid_lanes, prompt, tmp_path)
    blender = tmp_path / "blender.exe"; blender.write_bytes(b"exe")
    settings = config.model_copy(update={"tools": config.tools.model_copy(update={"blender_executable": blender})})
    def runner(arguments, *_args):
        index = arguments.index("--")
        _, albedo, output, report = map(Path, arguments[index+1:index+5])
        positions=struct.pack("<9f",-0.5,0.0,0.0,0.5,0.0,0.0,0.0,1.8,0.2)
        joints=struct.pack("<12H",*([0,1,2,3]*3))
        weights=struct.pack("<12f",*([0.25]*12))
        binds=struct.pack("<16f",*([1.0,0.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0,0.0,1.0]))
        binary=positions+joints+weights+binds
        document={"asset":{"version":"2.0"},"buffers":[{"uri":"body.bin","byteLength":len(binary)}],"bufferViews":[{"buffer":0,"byteOffset":0,"byteLength":len(positions)},{"buffer":0,"byteOffset":len(positions),"byteLength":len(joints)},{"buffer":0,"byteOffset":len(positions)+len(joints),"byteLength":len(weights)},{"buffer":0,"byteOffset":len(positions)+len(joints)+len(weights),"byteLength":len(binds)}],"accessors":[{"bufferView":0,"componentType":5126,"count":3,"type":"VEC3"},{"bufferView":1,"componentType":5123,"count":3,"type":"VEC4"},{"bufferView":2,"componentType":5126,"count":3,"type":"VEC4"},{"bufferView":3,"componentType":5126,"count":1,"type":"MAT4"}],"images":[{"uri":"albedo.png"}],"textures":[{"source":0}],"materials":[{"pbrMetallicRoughness":{"baseColorTexture":{"index":0},"metallicFactor":0.0,"roughnessFactor":0.8}}],"meshes":[{"primitives":[{"attributes":{"POSITION":0,"JOINTS_0":1,"WEIGHTS_0":2},"material":0}]}],"skins":[{"joints":[1,2,3,4],"inverseBindMatrices":3}],"nodes":[{"mesh":0,"skin":0},{},{},{},{}],"scenes":[{"nodes":[0,1,2,3,4]}],"scene":0}
        output.write_text(json.dumps(document))
        output.with_name("body.bin").write_bytes(binary)
        output.with_name("albedo.png").write_bytes(albedo.read_bytes())
        report.write_text(json.dumps({"schema_version":"vandrel_foundry_clean_meshy_body_blender/1.0","blender_version":"test"}))
        return CaptureProcessResult(0,"","",False,False,0.1)
    artifacts = process_clean_meshy_body(settings, "clean_body_test_001", runner)
    assert [item.role for item in artifacts] == ["processed_model","processed_clean_body_buffer","processed_clean_body_albedo","clean_body_processing_report"]
    return settings


def _validation_request(config, tmp_path: Path) -> tuple[Path, bytes, bytes, bytes, str]:
    bone=b"bone-map"; sidecar=b"policy-only"
    for name, value in (("bone_map.tres",bone),("accepted.fbx.import",sidecar)): (tmp_path/name).write_bytes(value)
    _write_v2_animation_library(config.foundry.asset_library_root)
    release=config.foundry.asset_library_root/"assets/meshy_shared_reactions_b2_passing_001/r001"
    descriptor_bytes=(release/"asset-release.json").read_bytes()
    library=(release/"animations/animation_library.res").read_bytes()
    value={"schema_version":"vandrel_foundry_clean_meshy_body_validation/1.0","asset_id":"clean_body_test_001","accepted_bone_map":{"path":str(tmp_path/"bone_map.tres"),"sha256":_sha(bone),"size_bytes":len(bone)},"accepted_import_sidecar_policy":{"path":str(tmp_path/"accepted.fbx.import"),"sha256":_sha(sidecar),"size_bytes":len(sidecar)},"shared_animation_library_asset_id":"meshy_shared_reactions_b2_passing_001","shared_animation_library_release_revision":1,"shared_animation_library_sha256":_sha(library),"shared_semantics":["AngryStomp","HitReaction"],"import_policy":"godot_clean_body_humanoid_bone_map_rest_fixer_v1","camera_policy":"vandrel_fixed_clean_body_review_camera_v1","camera_config_sha256":CLEAN_BODY_CAMERA_CONFIG_SHA256}
    path=tmp_path/"validation.json"; path.write_text(json.dumps(value)); return path,bone,sidecar,library,_sha(descriptor_bytes)


def _passing_monitor() -> dict:
    phases=[]
    for name in ("initial_import","configure_import","retargeted_import","technical_validate","visual_capture"):
        phases.append({"phase":name,"exit_code":0,"timed_out":False,"cleanup_failed":False,"has_crash_evidence":False,"crash_evidence_path":f"{name}-crash.json","stdout_path":f"{name}-stdout.log","stderr_path":f"{name}-stderr.log","godot_log_path":f"{name}-godot.log"})
    return {"schema_version":"vandrel_foundry_clean_body_godot_monitor/1.0","policy":"vandrel_monitored_godot_clean_body_corridor_2026-08-21","run_started_utc":"2026-08-22T00:00:00Z","run_ended_utc":"2026-08-22T00:01:00Z","console_executable_name":"Godot_v4.7-stable_mono_win64_console.exe","console_file_version":"4.7","godot_console_sha256":"1"*64,"supervisor_sha256":"2"*64,"runtime_guard_sha256":"3"*64,"crash_evidence_authority_sha256":"4"*64,"process_zero_preflight":True,"child_environment":{"DOTNET_ROLL_FORWARD":"LatestMajor"},"phase_results":phases,"outer_timeout_seconds_per_phase":120,"maximum_output_bytes":1_000_000,"internal_iteration_bomb":600,"post_exit_poll_seconds":5,"timed_out":False,"output_limited":False,"cleanup_failed":False,"failure":"","application_error_windows":[],"application_events":[],"wer_and_dump_paths":[],"final_godot_processes":[],"has_crash_evidence":False,"passed":True}


def test_body_only_process_validation_manual_review_and_approval_contract(config, humanoid_lanes, prompt, tmp_path):
    settings=_processed(config,humanoid_lanes,prompt,tmp_path); request,bone,sidecar,library,descriptor_sha=_validation_request(settings,tmp_path)
    repository=ManifestRepository(settings.foundry.workspace_root); model=[item for item in repository.load("clean_body_test_001").artifacts if item.role=="processed_model"][-1]
    def validation_runner(_config,sandbox):
        output=sandbox/"output"; cells=[]
        for index,label in enumerate(("front","side","back","AngryStomp","HitReaction"),start=1):
            payload=f"image-{label}".encode(); name=f"cell-{index}.png"; (output/name).write_bytes(payload); cells.append({"kind":"rest" if index<4 else "motion","label":label,"phases":[] if index<4 else [0,.125,.25,.375,.5,.625,.75,.875],"path":name,"sha256":_sha(payload),"size_bytes":len(payload),"result":None})
        technical={"schema_version":"vandrel_foundry_clean_body_technical/1.1","processed_body_sha256":model.sha256,"bone_map_sha256":_sha(bone),"sidecar_policy_source_sha256":_sha(sidecar),"shared_animation_library_sha256":_sha(library),"shared_animation_library_descriptor_sha256":descriptor_sha,"skeleton_name":"GeneralSkeleton","mapped_bone_count":22,"skeleton_count":1,"animation_count":0,"skin_present":True,"bind_count_positive":True,"weights_present":True,"rest_pose_valid":True,"import_policy_valid":True,"material_surface_count":1,"external_lit_albedo":True,"casts_shadows":True,"scale_finite_positive":True,"grounded":True,"shared_animation_pool_compatible":True,"shared_semantics":["AngryStomp","HitReaction"]}
        monitor=_passing_monitor()
        capture={"schema_version":"vandrel_foundry_clean_body_capture/1.0","processed_body_sha256":model.sha256,"shared_animation_library_sha256":_sha(library),"shared_animation_library_descriptor_sha256":descriptor_sha,"camera_config_sha256":CLEAN_BODY_CAMERA_CONFIG_SHA256,"review_status":"manual_review_required","manual_result":None,"cells":cells}
        for name,value in (("technical.json",technical),("monitor.json",monitor),("capture.json",capture)): (output/name).write_text(json.dumps(value))
        return CleanBodyValidationExecution(output/"technical.json",output/"monitor.json",output/"capture.json")
    validate_clean_meshy_body(settings,"clean_body_test_001",request,validation_runner)
    manifest=repository.load("clean_body_test_001"); root=repository.asset_directory("clean_body_test_001"); technical=[item for item in manifest.artifacts if item.role=="clean_body_technical_report"][-1]; monitor=[item for item in manifest.artifacts if item.role=="clean_body_godot_monitor_report"][-1]
    capture=[item for item in manifest.artifacts if item.role=="clean_body_capture_evidence"]
    rest=[]; motion=[]
    for index,item in enumerate(capture):
        cell={"evidence":{"path":str(root/item.path),"sha256":item.sha256,"size_bytes":item.size_bytes},"result":"PASS","notes":"reviewed"}
        if index<3: rest.append(cell|{"view":("front","side","back")[index]})
        else: motion.append(cell|{"semantic":("AngryStomp","HitReaction")[index-3],"observed_phases":[0,.125,.25,.375,.5,.625,.75,.875]})
    review={"schema_version":"vandrel_foundry_clean_meshy_body_visual_review/1.0","asset_id":"clean_body_test_001","processed_body_sha256":model.sha256,"technical_report_sha256":technical.sha256,"monitor_report_sha256":monitor.sha256,"shared_animation_library_sha256":_sha(library),"camera_policy":"vandrel_fixed_clean_body_review_camera_v1","camera_config_sha256":CLEAN_BODY_CAMERA_CONFIG_SHA256,"reviewer":"Independent reviewer","reviewed_at":"2026-08-22T00:00:00Z","rest_cells":rest,"motion_cells":motion}
    review_path=tmp_path/"review.json"; review_path.write_text(json.dumps(review)); import_clean_meshy_body_visual_review(settings,"clean_body_test_001",review_path)
    manifest=repository.load("clean_body_test_001")
    assert approval_checks_pass(manifest)
    assert approval_artifact_roles(manifest)[0:4] == ("processed_model","processed_clean_body_buffer","processed_clean_body_albedo","clean_body_processing_report")
    bindings=approval_artifact_bindings(manifest); assert len([key for key in bindings if key.startswith("artifact:")]) == 5
    bind_documented_test_custody(manifest,root); bind_approved_test_scale(manifest)
    manifest.approval.approved=True; manifest.approval.approved_at=utc_now(); manifest.approval.reviewer="Independent reviewer"; manifest.approval.approved_artifact_hashes=bindings; manifest.workflow.state=WorkflowState.APPROVED; manifest.revision+=1
    repository.save(manifest,"test.clean_body_approved",expected_revision=manifest.revision-1)
    plan=plan_release(settings,humanoid_lanes,"clean_body_test_001")
    assert plan.descriptor["primary_payload"]=="clean_body"
    release_paths = {item["role"]: item["path"] for item in plan.descriptor["files"]}
    assert release_paths["model"] == "model.gltf"
    assert release_paths["clean_body_buffer"] == "body.bin"
    assert release_paths["clean_body_albedo"] == "albedo.png"
    assert plan.descriptor["clean_body"]["candidate_only"] is True
    assert plan.descriptor["clean_body"]["vandrel_runtime_accepted"] is False
    assert not ({"godot_wrapper_scene","animation_walk","animation_run","animation_library"} & {item["role"] for item in plan.descriptor["files"]})


def test_generated_policy_is_not_source_sidecar_and_capture_is_manual_null():
    configure=Path("src/vandrel_foundry/godot/configure_clean_meshy_body_import.gd").read_text()
    capture=Path("src/vandrel_foundry/godot/capture_clean_meshy_body.gd").read_text()
    wrapper=Path("src/vandrel_foundry/godot/Invoke-FoundryCleanMeshyBodyMonitored.ps1").read_text()
    assert "function Wait-GodotProcessZero" in wrapper
    assert "Wait-GodotProcessZero -Deadline $phaseStarted.AddSeconds($TimeoutSeconds)" in wrapper
    assert "assigns this supervisor and every descendant to one" in wrapper
    assert "outer Job terminates only its own tree" in wrapper
    assert "Stop-Process" not in wrapper
    assert "$phaseWindows=@($initialPhaseCrash.application_error_windows)+@($settle.application_error_windows)" in wrapper
    assert "-ObservedApplicationErrorWindows $phaseWindows" in wrapper
    assert "$phaseCrashEvidence=[bool]$phaseCrash.has_crash_evidence" in wrapper
    assert 'config.set_value("params", "animation/import", false)' in configure
    assert "accepted.fbx.import" not in configure
    assert '"manual_result":null' in capture
    assert "--headless','--path" in wrapper
    assert "name='visual_capture';args=@('--path'" in wrapper
    assert "VandrelGodotRuntimeGuard.ps1" not in wrapper
    assert "Get-VandrelGodotChildEnvironment" in wrapper
    assert "Write-VandrelGodotCrashEvidence" in wrapper
    technical=Path("src/vandrel_foundry/godot/validate_clean_meshy_body.gd").read_text()
    assert '&"Chest"' in technical and '&"UpperChest"' in technical and '&"LeftUpperArm"' in technical
    assert '&"Spine1"' not in technical and '&"LeftArm"' not in technical and '&"LeftUpLeg"' not in technical
    assert "lit = lit and standard != null" in technical
    assert "not standard.emission_enabled" in technical
    assert '"rest_pose_valid": rest_pose_valid' in technical
    assert "float(influences_per_vertex) / 65535.0" in technical
    assert "abs(total - 1.0) > normalization_tolerance" in technical
    assert '"animation/import", true' in technical
    assert 'bone_map.resource_path == "res://input/bone_map.tres"' in technical
    assert 'policy.get("retarget/rest_fixer/retarget_method") == 1' in technical
    assert "pose.is_equal_approx(rest)" in technical
    assert "retarget_policy_count == 1 and exact_policy_found" in technical


def test_service_parses_real_blender_diagnostic_schema_constant():
    script=Path("src/vandrel_foundry/blender/process_clean_meshy_body.py").read_text()
    assert _blender_diagnostic_schema()=="vandrel_foundry_clean_meshy_body_blender/1.0"
    assert '"schema_version": BLENDER_DIAGNOSTIC_SCHEMA' in script


def _derive_fixture(tmp_path: Path, *, joint_index: int=0, translation=None, scale=None):
    positions=struct.pack("<9f",-0.5,0.0,0.0,0.5,0.0,0.0,0.0,1.8,0.2)
    joints=struct.pack("<12H",*([joint_index,1,2,3]*3))
    weights=struct.pack("<12f",*([0.25]*12))
    binds=struct.pack("<16f",*([1.0,0.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0,0.0,1.0]))
    binary=positions+joints+weights+binds
    body_node={"mesh":0,"skin":0}
    if translation is not None: body_node["translation"]=translation
    if scale is not None: body_node["scale"]=scale
    document={"asset":{"version":"2.0"},"buffers":[{"uri":"body.bin","byteLength":len(binary)}],"bufferViews":[{"buffer":0,"byteOffset":0,"byteLength":len(positions)},{"buffer":0,"byteOffset":len(positions),"byteLength":len(joints)},{"buffer":0,"byteOffset":len(positions)+len(joints),"byteLength":len(weights)},{"buffer":0,"byteOffset":len(positions)+len(joints)+len(weights),"byteLength":len(binds)}],"accessors":[{"bufferView":0,"componentType":5126,"count":3,"type":"VEC3"},{"bufferView":1,"componentType":5123,"count":3,"type":"VEC4"},{"bufferView":2,"componentType":5126,"count":3,"type":"VEC4"},{"bufferView":3,"componentType":5126,"count":1,"type":"MAT4"}],"images":[{"uri":"albedo.png"}],"textures":[{"source":0}],"materials":[{"pbrMetallicRoughness":{"baseColorTexture":{"index":0},"metallicFactor":0.0,"roughnessFactor":0.8}}],"meshes":[{"primitives":[{"attributes":{"POSITION":0,"JOINTS_0":1,"WEIGHTS_0":2},"material":0}]}],"skins":[{"joints":[1,2,3,4],"inverseBindMatrices":3}],"nodes":[body_node,{},{},{},{}],"scenes":[{"nodes":[0,1,2,3,4]}],"scene":0}
    gltf=tmp_path/"body.gltf"; buffer=tmp_path/"body.bin"; albedo=tmp_path/"albedo.png"
    gltf.write_text(json.dumps(document)); buffer.write_bytes(binary); albedo.write_bytes(b"texture")
    return _derive_gltf_facts(gltf,buffer,albedo)


def test_output_facts_validate_joint_indices_and_world_transform(tmp_path):
    facts=_derive_fixture(tmp_path,scale=[2.0,2.0,2.0])
    assert facts["dimensions"]==pytest.approx([2.0,3.6,0.4])
    with pytest.raises(FoundryError,match="joint index"):
        _derive_fixture(tmp_path,joint_index=8)
    with pytest.raises(FoundryError,match="not grounded"):
        _derive_fixture(tmp_path,translation=[0.0,0.5,0.0])


@pytest.mark.parametrize("mutation",("authority","cleanup","post_exit","phase_timeout","inventory","outer_bound"))
def test_monitor_closed_schema_rejects_incomplete_or_failed_evidence(mutation):
    monitor=_passing_monitor()
    if mutation=="authority": monitor["runtime_guard_sha256"]=""
    elif mutation=="cleanup": monitor["cleanup_failed"]=True
    elif mutation=="post_exit": monitor["post_exit_poll_seconds"]=4
    elif mutation=="phase_timeout": monitor["phase_results"][0]["timed_out"]=True
    elif mutation=="inventory": monitor["final_godot_processes"]=[{"pid":42}]
    else: monitor["outer_timeout_seconds_per_phase"]=0
    with pytest.raises(FoundryError):
        _validate_monitor(monitor,["initial_import","configure_import","retargeted_import","technical_validate","visual_capture"])


def test_visual_review_rejects_reused_evidence_bytes(tmp_path):
    evidence={"path":"same.png","sha256":"a"*64,"size_bytes":1}
    value={"schema_version":"vandrel_foundry_clean_meshy_body_visual_review/1.0","asset_id":"clean_body_test_001","processed_body_sha256":"b"*64,"technical_report_sha256":"c"*64,"monitor_report_sha256":"d"*64,"shared_animation_library_sha256":"e"*64,"camera_policy":"vandrel_fixed_clean_body_review_camera_v1","camera_config_sha256":CLEAN_BODY_CAMERA_CONFIG_SHA256,"reviewer":"reviewer","reviewed_at":"now","rest_cells":[{"view":view,"result":"PASS","evidence":evidence} for view in ("front","side","back")],"motion_cells":[{"semantic":"Idle","result":"PASS","observed_phases":[0,.125,.25,.375,.5,.625,.75,.875],"evidence":evidence}]}
    with pytest.raises(ValidationError,match="unique evidence"): CleanBodyVisualReviewRequest.model_validate(value)


def test_clean_body_release_descriptor_is_isolated_and_exact():
    value=json.loads(Path("tests/fixtures/release_descriptors/release-v2.json").read_text())
    value["lane"]="humanoid"; value["primary_payload"]="clean_body"; value["godot"]["wrapper_template"]="humanoid_candidate"
    reports={}
    for index,(role,name) in enumerate((("clean_body_processing_report","processing_report"),("clean_body_technical_report","technical_report"),("clean_body_godot_monitor_report","monitor_report"),("clean_body_visual_review_report","visual_review_report")),start=10):
        item={"role":role,"path":f"evidence/clean-body/{name}.json","sha256":str(index%10)*64,"size_bytes":index,"source_artifact_id":f"{role}-001"}; value["files"].append(item); reports[name]={"release_path":item["path"],"sha256":item["sha256"],"size_bytes":item["size_bytes"],"source_artifact_id":item["source_artifact_id"]}
    dependencies=[]
    for role,path,digest in (("clean_body_buffer","body.bin","a"*64),("clean_body_albedo","albedo.png","b"*64)):
        value["files"].append({"role":role,"path":path,"sha256":digest,"size_bytes":4,"source_artifact_id":role+"-001"}); dependencies.append(digest)
    for index in range(4):
        value["files"].append({"role":"clean_body_visual_evidence","path":f"evidence/clean-body/cells/{index}.png","sha256":f"{index+3:x}"*64,"size_bytes":10+index,"source_artifact_id":f"visual-{index}"})
    value["clean_body"]={"evidence_route":"clean_body_shared_animation","candidate_only":True,"vandrel_runtime_accepted":False,"shared_animation_pool_compatible":True,"embedded_animations_disabled":True,"import_policy":"godot_clean_body_humanoid_bone_map_rest_fixer_v1","material_policy":"external_lit_principled_albedo_v1","output_sha256":value["files"][0]["sha256"],"dependency_sha256s":dependencies,"shared_animation_library":{"asset_id":"shared_library_001","release_revision":1,"output_sha256":"c"*64},**reports}
    descriptor=ReleaseDescriptorV2.model_validate(value); assert descriptor.clean_body is not None
    assert {item.path for item in descriptor.files if item.role in {"model", "clean_body_buffer", "clean_body_albedo"}} == {"model.glb", "body.bin", "albedo.png"}
    invalid=json.loads(json.dumps(value)); invalid["files"].append({"role":"animation_library","path":"forbidden.res","sha256":"f"*64,"size_bytes":1,"source_artifact_id":"forbidden"})
    with pytest.raises(ValueError,match="one exact body model"): ReleaseDescriptorV2.model_validate(invalid)


def test_clean_body_cli_commands_are_public_and_thin():
    result=CliRunner().invoke(app,["--help"])
    assert result.exit_code==0
    for command in ("intake-clean-meshy-body","process-clean-meshy-body","validate-clean-meshy-body","import-clean-meshy-body-visual-review"):
        assert command in result.stdout


def test_clean_body_outer_adapter_invokes_only_dedicated_supervisor(config,tmp_path):
    godot=tmp_path/"Godot_v4.7-stable_mono_win64_console.exe"; godot.write_bytes(b"godot")
    powershell=tmp_path/"pwsh.exe"; powershell.write_bytes(b"pwsh")
    sandbox=tmp_path/"sandbox"; (sandbox/"output").mkdir(parents=True)
    vandrel=tmp_path/"vandrel"; authority=vandrel/"tools/ai"; authority.mkdir(parents=True)
    (authority/"VandrelGodotRuntimeGuard.ps1").write_text("# guard")
    (authority/"VandrelGodotCrashEvidence.ps1").write_text("# crash")
    settings=config.model_copy(update={"vandrel":config.vandrel.model_copy(update={"reference_repo_root":vandrel}),"tools":config.tools.model_copy(update={"godot_executable":godot,"godot_timeout_seconds":10,"maximum_output_bytes":4096})})
    observed={}
    def runner(arguments,cwd,environment,timeout,limit):
        observed.update(arguments=list(arguments),cwd=cwd,environment=dict(environment),timeout=timeout,limit=limit)
        return CaptureProcessResult(0,"","",False,False,0.1)
    result=run_monitored_clean_body(settings,sandbox,runner,environment={"PATH":str(tmp_path)},supervisor_executable=powershell)
    assert result.monitor_report==sandbox/"output/clean-body-godot-monitor.json"
    assert Path(observed["arguments"][observed["arguments"].index("-File")+1]).name=="Invoke-FoundryCleanMeshyBodyMonitored.ps1"
    assert observed["arguments"][observed["arguments"].index("-RuntimeGuardPath")+1].endswith("VandrelGodotRuntimeGuard.ps1")
    assert observed["arguments"][observed["arguments"].index("-CrashEvidenceScriptPath")+1].endswith("VandrelGodotCrashEvidence.ps1")
    assert observed["cwd"]==sandbox and observed["timeout"]==110 and observed["limit"]==69632
