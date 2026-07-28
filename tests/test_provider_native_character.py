import hashlib
import json
from pathlib import Path

import pytest

from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.inspect_assets import initialize_workspace
from vandrel_foundry.services.plan_release import plan_release
from vandrel_foundry.services.prepare_native_character import (
    PROCESSOR_NAME,
    _repair_native_artifact_id_collisions,
    _require_native_character_report,
    _select_sources,
    prepare_provider_native_character,
)
from vandrel_foundry.services.review_asset import approval_checks_pass, approve_asset
from vandrel_foundry.services.validate_godot import ProcessResult
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath


def test_prepares_approvable_same_task_fbx_character_without_blender(
    config,
    humanoid_lanes,
    prompt: Path,
) -> None:
    initialize_workspace(config.foundry.workspace_root)
    manifest = create_asset(
        config,
        humanoid_lanes,
        "native_character_001",
        "humanoid",
        "Native Character",
        prompt,
    )
    manifest.workflow.state = WorkflowState.DOWNLOADED
    asset_root = config.foundry.workspace_root / "assets/native_character_001"
    for artifact_id, role, name in (
        ("source_fbx_001", "source_model", "character.fbx"),
        ("source_animation_walk_fbx_001", "source_animation_walk", "walking.fbx"),
        ("source_animation_run_fbx_001", "source_animation_run", "running.fbx"),
    ):
        relative = RelativeManifestPath(f"source/meshy_rigging_001/{name}")
        path = asset_root / str(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = artifact_id.encode()
        path.write_bytes(content)
        manifest.artifacts.append(
            Artifact(
                artifact_id=artifact_id,
                role=role,
                stage="source",
                format="fbx",
                path=relative,
                sha256=hashlib.sha256(content).hexdigest(),
                size_bytes=len(content),
                source_task_key="meshy_rigging_001",
            )
        )
    manifest.revision += 1
    ManifestRepository(config.foundry.workspace_root).save(
        manifest,
        "fixture.native_sources",
        expected_revision=manifest.revision - 1,
    )
    executable = config.foundry.workspace_root / "godot.exe"
    executable.write_bytes(b"fake")
    config.tools.godot_executable = executable

    calls: list[list[str]] = []

    def runner(arguments, cwd, environment, timeout_seconds, maximum_output_bytes):
        calls.append(list(arguments))
        if "--import" in arguments:
            (cwd / ".godot/imported").mkdir(parents=True)
        else:
            (cwd / "animations/walk.res").write_bytes(b"walk-resource")
            (cwd / "animations/run.res").write_bytes(b"run-resource")
            (cwd / "native-character-report.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "passed": True,
                        "bone_count": 24,
                        "mesh_count": 1,
                        "visible_mesh_count": 1,
                        "visible_skinned_mesh_count": 1,
                        "visible_unskinned_mesh_count": 0,
                        "triangle_count": 12000,
                        "visible_skinned_triangle_count": 12000,
                        "material_count": 1,
                        "textured_material_count": 1,
                        "missing_animations": [],
                        "finite_bone_scales": True,
                    }
                ),
                encoding="utf-8",
            )
        return ProcessResult(0, "", "", False, False, 0.1)

    result = prepare_provider_native_character(
        config,
        "native_character_001",
        runner=runner,
        environment={"PATH": "safe", "MESHY_API_KEY": "must-not-pass"},
    )

    assert len(calls) == 2
    assert result.model.format == "fbx"
    assert result.walk.role == "processed_animation_walk"
    assert result.run.role == "processed_animation_run"
    assert not (asset_root / Path(str(result.model.path)).parent / "walking.fbx").exists()
    package_root = asset_root / Path(str(result.model.path)).parent
    assert 'run/main_scene="res://wrapper.tscn"' in (
        package_root / "project.godot"
    ).read_text(encoding="utf-8")
    saved = ManifestRepository(config.foundry.workspace_root).load("native_character_001")
    assert saved.workflow.state is WorkflowState.REVIEW
    assert approval_checks_pass(saved)
    check = next(
        item
        for item in saved.validation.checks
        if item["name"] == "provider_native_character_playback"
    )
    assert check["same_provider_task"] is True
    assert check["skin_binding_passed"] is True
    assert check["processed_model_sha256"] == result.model.sha256
    skin_check = next(
        item for item in saved.validation.checks if item["name"] == "character_skin_binding"
    )
    assert skin_check == {
        "name": "character_skin_binding",
        "passed": True,
        "observed_visible_skinned_meshes": 1,
        "observed_visible_unskinned_meshes": 0,
        "observed_visible_skinned_triangles": 12000,
    }

    approve_asset(config, "native_character_001", "Automated test")
    release = plan_release(config, humanoid_lanes, "native_character_001")
    assert [item["path"] for item in release.descriptor["files"]] == [
        "model.fbx",
        "godot/wrapper.tscn",
        "godot/animation_loader.gd",
        "animations/walk.res",
        "animations/run.res",
    ]
    assert release.descriptor["humanoid_compatibility"] == {
        "candidate_only": True,
        "vandrel_runtime_accepted": False,
        "provider_native_same_task": True,
        "shared_animation_pool_compatible": False,
        "report": str(result.report.path),
    }


def test_native_character_report_rejects_static_mesh_beside_unbound_rig() -> None:
    report = {
        "schema_version": 1,
        "passed": True,
        "bone_count": 24,
        "mesh_count": 1,
        "visible_mesh_count": 1,
        "visible_skinned_mesh_count": 0,
        "visible_unskinned_mesh_count": 1,
        "triangle_count": 12000,
        "visible_skinned_triangle_count": 0,
        "material_count": 1,
        "textured_material_count": 1,
        "missing_animations": [],
        "finite_bone_scales": True,
    }

    with pytest.raises(
        FoundryError,
        match="visible geometry skinned to the imported rig",
    ):
        _require_native_character_report(report)


def test_legacy_rig_download_order_is_supported_but_recorded(
    config,
    humanoid_lanes,
    prompt: Path,
) -> None:
    initialize_workspace(config.foundry.workspace_root)
    manifest = create_asset(
        config,
        humanoid_lanes,
        "legacy_native_character",
        "humanoid",
        "Legacy Native Character",
        prompt,
    )
    manifest.workflow.state = WorkflowState.DOWNLOADED
    asset_root = config.foundry.workspace_root / "assets/legacy_native_character"
    for index, (artifact_id, role) in enumerate(
        (
            ("source_fbx_001", "source_model"),
            ("source_animation_fbx_003", "source_animation_model"),
            ("source_animation_fbx_004", "source_animation_model"),
        ),
        start=1,
    ):
        relative = RelativeManifestPath(f"source/rig/file-{index}.fbx")
        path = asset_root / str(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(artifact_id.encode())
        manifest.artifacts.append(
            Artifact(
                artifact_id=artifact_id,
                role=role,
                stage="source",
                format="fbx",
                path=relative,
                sha256=hashlib.sha256(artifact_id.encode()).hexdigest(),
                size_bytes=len(artifact_id),
                source_task_key="rig",
            )
        )
    _, walk, run, basis = _select_sources(manifest.artifacts)
    assert walk.artifact_id == "source_animation_fbx_003"
    assert run.artifact_id == "source_animation_fbx_004"
    assert basis == "legacy_downloader_walk_then_run_order"


def test_repairs_only_provider_native_artifact_id_collisions(
    config,
    humanoid_lanes,
    prompt: Path,
) -> None:
    initialize_workspace(config.foundry.workspace_root)
    manifest = create_asset(
        config,
        humanoid_lanes,
        "native_id_repair",
        "humanoid",
        "Native ID Repair",
        prompt,
    )
    digest = hashlib.sha256(b"x").hexdigest()
    manifest.artifacts.extend(
        [
            Artifact(
                artifact_id="godot_wrapper_scene_001",
                role="godot_wrapper_scene",
                stage="staged",
                format="tscn",
                path=RelativeManifestPath("old/wrapper.tscn"),
                sha256=digest,
                size_bytes=1,
            ),
            Artifact(
                artifact_id="godot_wrapper_scene_001",
                role="godot_wrapper_scene",
                stage="processed",
                format="tscn",
                path=RelativeManifestPath("native/wrapper.tscn"),
                sha256=digest,
                size_bytes=1,
                processor=Processor(name=PROCESSOR_NAME, version="1"),
            ),
            Artifact(
                artifact_id="godot_validation_project_001",
                role="godot_validation_project",
                stage="processed",
                format="godot",
                path=RelativeManifestPath("native/project.godot"),
                sha256=digest,
                size_bytes=1,
                derived_from=["godot_wrapper_scene_001"],
                processor=Processor(name=PROCESSOR_NAME, version="1"),
            ),
        ]
    )

    assert _repair_native_artifact_id_collisions(manifest)
    assert manifest.artifacts[0].artifact_id == "godot_wrapper_scene_001"
    assert manifest.artifacts[1].artifact_id == "godot_wrapper_scene_001_native_001"
    assert manifest.artifacts[2].derived_from == ["godot_wrapper_scene_001_native_001"]
