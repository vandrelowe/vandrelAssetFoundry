import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import vandrel_foundry.services.capture_animation_visual_matrix as capture_service_module
import vandrel_foundry.services.run_animation_visual_capture as capture_runner_module
from tests.conftest import write_config
from vandrel_foundry import cli
from vandrel_foundry.cli import app
from vandrel_foundry.domain.animation_library import FIXED_PHASES
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.services.capture_animation_visual_matrix import (
    CAMERA_CONFIG_SHA256,
    ENTRY_SENTINEL_BYTES,
    ENTRY_SENTINEL_SHA256,
    AnimationVisualCaptureExecution,
    capture_animation_visual_matrix,
)
from vandrel_foundry.services.run_animation_visual_capture import (
    OUTER_WATCHDOG_PATH,
    CaptureProcessResult,
    run_monitored_animation_visual_capture,
)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _inputs(config, tmp_path: Path) -> Path:
    library = b"exact processed animation library"
    library_path = tmp_path / "animation_library.res"
    library_path.write_bytes(library)
    motions = []
    for semantic in ("AngryStomp", "StandDodge"):
        motions.append(
            {
                "semantic": semantic,
                "source_sha256": _sha(f"source:{semantic}".encode()),
                "source_size_bytes": 20,
                "hips_position_track_count": 1,
                "mapped_rotation_track_count": 22,
                "scale_track_count": 0,
                "non_hips_position_track_count": 0,
                "other_track_count": 0,
                "finite_keys": True,
                "optimized_rest_leaf_completion_policy": (
                    "restore_optimized_identity_hand_rotation_tracks_v1"
                ),
                "optimized_rest_leaf_animation_length": 1.0,
                "optimized_rest_leaf_tracks_added": [],
                "optimized_rest_leaf_completion_passed": True,
                "output_library_sha256": _sha(library),
                "passed": True,
            }
        )
    technical = {
        "schema_version": "vandrel_foundry_animation_library_technical/1.0",
        "import_policy": "godot_skeleton_profile_humanoid_meshy_bone_map_rest_fixer_v1",
        "animation_library_sha256": _sha(library),
        "animation_library_size_bytes": len(library),
        "motions": motions,
        "passed": True,
    }
    technical_path = tmp_path / "technical.json"
    technical_path.write_text(json.dumps(technical), encoding="utf-8")
    bone_map = b'[gd_resource type="BoneMap" format=3]\n'
    shared_bone_map_path = tmp_path / "shared_bone_map.tres"
    canary_bone_map_path = tmp_path / "canary_bone_map.tres"
    shared_bone_map_path.write_bytes(bone_map)
    canary_bone_map_path.write_bytes(bone_map)
    bodies = []
    for body_id in ("female_average", "male_average", "feral_apeman"):
        payload = f"exact-body:{body_id}".encode()
        path = tmp_path / f"{body_id}.fbx"
        path.write_bytes(payload)
        if body_id == "feral_apeman":
            resource_root = (
                "res://mods/CavemanMod/assets/candidates/"
                "meshy_godot_shared_animation_canary"
            )
            bone_map_path = canary_bone_map_path
        else:
            resource_root = (
                "res://mods/CavemanMod/assets/game/scenes/actors/rigs/caveman/"
                "MeshyShared"
            )
            bone_map_path = shared_bone_map_path
        resource_path = f"{resource_root}/bodies/{body_id}/{body_id}.fbx"
        bone_map_resource_path = f"{resource_root}/meshy_humanoid_bone_map.tres"
        sidecar = (
            "[remap]\n\n"
            'importer="scene"\n'
            'type="PackedScene"\n'
            f'path="res://.godot/imported/{body_id}.scn"\n\n'
            "[deps]\n\n"
            f'source_file="{resource_path}"\n'
            f'dest_files=["res://.godot/imported/{body_id}.scn"]\n\n'
            "[params]\n\n"
            "animation/import=false\n"
            "_subresources={\n"
            '"nodes": {\n'
            '"PATH:Armature/Skeleton3D": {\n'
            '"rest_pose/external_animation_library": null,\n'
            f'"retarget/bone_map": Resource("{bone_map_resource_path}"),\n'
            '"retarget/bone_renamer/rename_bones": true,\n'
            '"retarget/bone_renamer/unique_node/make_unique": true,\n'
            '"retarget/bone_renamer/unique_node/skeleton_name": "GeneralSkeleton",\n'
            '"retarget/remove_tracks/except_bone_transform": false,\n'
            '"retarget/remove_tracks/unimportant_positions": true,\n'
            '"retarget/remove_tracks/unmapped_bones": 0,\n'
            '"retarget/rest_fixer/apply_node_transforms": true,\n'
            '"retarget/rest_fixer/fix_silhouette/base_height_adjustment": 0.0,\n'
            '"retarget/rest_fixer/fix_silhouette/enable": false,\n'
            '"retarget/rest_fixer/fix_silhouette/filter": [],\n'
            '"retarget/rest_fixer/fix_silhouette/threshold": 15.0,\n'
            '"retarget/rest_fixer/keep_global_rest_on_leftovers": true,\n'
            '"retarget/rest_fixer/normalize_position_tracks": true,\n'
            '"retarget/rest_fixer/reset_all_bone_poses_after_import": true,\n'
            '"retarget/rest_fixer/retarget_method": 1\n'
            "}\n"
            "}\n"
            "}\n"
        ).encode()
        sidecar_path = tmp_path / f"{body_id}.fbx.import"
        sidecar_path.write_bytes(sidecar)
        bodies.append(
            {
                "body_id": body_id,
                "path": path.name,
                "sha256": _sha(payload),
                "size_bytes": len(payload),
                "resource_path": resource_path,
                "import_sidecar": {
                    "path": sidecar_path.name,
                    "sha256": _sha(sidecar),
                    "size_bytes": len(sidecar),
                    "resource_path": f"{resource_path}.import",
                },
                "bone_map": {
                    "path": bone_map_path.name,
                    "sha256": _sha(bone_map),
                    "size_bytes": len(bone_map),
                    "resource_path": bone_map_resource_path,
                },
            }
        )
    request = {
        "schema_version": "vandrel_foundry_animation_visual_capture_request/1.0",
        "asset_id": "b2_selective_reactions_001",
        "animation_library": {
            "path": library_path.name,
            "sha256": _sha(library),
            "size_bytes": len(library),
        },
        "technical_report": {
            "path": technical_path.name,
            "sha256": _sha(technical_path.read_bytes()),
            "size_bytes": technical_path.stat().st_size,
        },
        "bodies": bodies,
        "camera_policy": "vandrel_fixed_animation_review_camera_v1",
        "camera_config_sha256": CAMERA_CONFIG_SHA256,
    }
    path = tmp_path / "capture-request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    executable = tmp_path / "Godot_console.exe"
    executable.write_bytes(b"fake Godot console")
    config.tools.godot_executable = executable
    return path


def _fake_runner(
    *,
    horizontal_span_x: float = 0.0,
    horizontal_span_z: float = 0.0,
    horizontal_delta: float = 0.0,
    duplicate: bool = False,
    crash_evidence: bool = False,
):
    def run(config, sandbox: Path, runtime_sha: str, script_sha: str):
        runtime = json.loads((sandbox / "animation-visual-runtime.json").read_text())
        (sandbox / "output" / "capture-entry.json").write_bytes(ENTRY_SENTINEL_BYTES)
        evidence_root = sandbox / "output" / "cells"
        evidence_root.mkdir()
        cells = []
        duplicate_bytes = b"\x89PNG\r\n\x1a\nrepeated-contact-sheet"
        for semantic in runtime["selected_semantics"]:
            for body in runtime["bodies"]:
                filename = f"{semantic}--{body['body_id']}.png"
                payload = (
                    duplicate_bytes
                    if duplicate
                    else b"\x89PNG\r\n\x1a\n"
                    + f"eight-phases:{semantic}:{body['body_id']}".encode()
                )
                path = evidence_root / filename
                path.write_bytes(payload)
                cells.append(
                    {
                        "semantic": semantic,
                        "body_id": body["body_id"],
                        "observed_phases": list(FIXED_PHASES),
                        "evidence": {
                            "path": f"cells/{filename}",
                            "sha256": _sha(payload),
                            "size_bytes": len(payload),
                        },
                        "horizontal_root_motion_span_x": horizontal_span_x,
                        "horizontal_root_motion_span_z": horizontal_span_z,
                        "horizontal_root_motion_initial_offset_x": 0.25,
                        "horizontal_root_motion_initial_offset_z": -0.1,
                        "horizontal_root_motion_max_delta_from_first": horizontal_delta,
                        "camera_follow_enabled": False,
                        "per_phase_reframing": False,
                    }
                )
        report = {
            "schema_version": "vandrel_foundry_animation_visual_capture_result/1.0",
            "entry_sentinel_sha256": ENTRY_SENTINEL_SHA256,
            "animation_library_sha256": runtime["animation_library_sha256"],
            "technical_report_sha256": runtime["technical_report_sha256"],
            "selected_semantics": runtime["selected_semantics"],
            "bodies": [
                {
                    "body_id": body["body_id"],
                    "payload_sha256": body["payload_sha256"],
                    "payload_size_bytes": body["size_bytes"],
                    "staged_payload_sha256": body["staged_payload_sha256"],
                    "staged_payload_size_bytes": body["staged_payload_size_bytes"],
                    "resource_path": body["path"],
                    "staging_policy": body["staging_policy"],
                    "import_sidecar_resource_path": body[
                        "import_sidecar_resource_path"
                    ],
                    "import_sidecar_sha256": body["import_sidecar_sha256"],
                    "import_sidecar_size_bytes": body["import_sidecar_size_bytes"],
                    "staged_import_sidecar_sha256": body[
                        "staged_import_sidecar_sha256"
                    ],
                    "staged_import_sidecar_size_bytes": body[
                        "staged_import_sidecar_size_bytes"
                    ],
                    "bone_map_resource_path": body["bone_map_resource_path"],
                    "bone_map_sha256": body["bone_map_sha256"],
                    "bone_map_size_bytes": body["bone_map_size_bytes"],
                    "staged_bone_map_sha256": body["staged_bone_map_sha256"],
                    "staged_bone_map_size_bytes": body[
                        "staged_bone_map_size_bytes"
                    ],
                }
                for body in runtime["bodies"]
            ],
            "camera_policy": runtime["camera_policy"],
            "camera_config_sha256": runtime["camera_config_sha256"],
            "observed_phases": list(FIXED_PHASES),
            "camera_follow_enabled": False,
            "per_phase_reframing": False,
            "anatomy_acceptance": "not_assessed",
            "cells": cells,
            "capture_passed": True,
        }
        capture_report = sandbox / "output" / "capture-report.json"
        capture_report.write_text(json.dumps(report), encoding="utf-8")
        supervisor = (
            Path(__file__).parents[1]
            / "src"
            / "vandrel_foundry"
            / "godot"
            / "Invoke-FoundryAnimationVisualCaptureMonitored.ps1"
        )
        monitor = {
            "schema_version": "vandrel_foundry_animation_visual_capture_monitor/1.0",
            "policy": "vandrel_monitored_godot_animation_visual_capture_corridor_2026-08-21",
            "run_started_utc": "2026-08-21T12:00:00Z",
            "run_ended_utc": "2026-08-21T12:00:05Z",
            "console_executable_name": "Godot_console.exe",
            "console_file_version": "4.7.2",
            "godot_console_sha256": _sha(config.tools.godot_executable.read_bytes()),
            "supervisor_sha256": _sha(supervisor.read_bytes()),
            "runtime_request_sha256": runtime_sha,
            "capture_script_sha256": script_sha,
            "camera_config_sha256": CAMERA_CONFIG_SHA256,
            "preflights": {
                "sandbox": True,
                "runtime_request": True,
                "capture_script": True,
                "camera_config": True,
                "godot_console": True,
                "initial_process_zero": True,
            },
            "process_zero_preflight": True,
            "child_environment": {"DOTNET_ROLL_FORWARD": "LatestMajor"},
            "phases": ["import", "capture"],
            "phase_results": [
                {
                    "phase": phase,
                    "process_zero_preflight": True,
                    "post_exit_poll_seconds": 5,
                    "started_utc": "2026-08-21T12:00:00Z",
                    "ended_utc": "2026-08-21T12:00:01Z",
                    "exit_code": 0,
                    "stdout_path": f"{phase}.stdout",
                    "stderr_path": f"{phase}.stderr",
                    "godot_log_path": f"{phase}.godot",
                }
                for phase in ("import", "capture")
            ],
            "outer_timeout_seconds_per_phase": int(config.tools.godot_timeout_seconds),
            "internal_iteration_bomb": 600,
            "post_exit_poll_seconds": 5,
            "timed_out": False,
            "output_limited": False,
            "cleanup_failed": False,
            "cleanup_issue": "",
            "application_error_windows": [],
            "application_events": ["crash-after-exit-zero"] if crash_evidence else [],
            "wer_and_dump_paths": [],
            "final_godot_processes": [],
            "has_crash_evidence": crash_evidence,
            "passed": not crash_evidence,
            "failure_stage": "post_exit_crash_evidence" if crash_evidence else None,
            "failure_message": "crash evidence" if crash_evidence else None,
        }
        monitor_path = sandbox / "output" / "animation-visual-godot-monitor.json"
        monitor_path.write_text(json.dumps(monitor), encoding="utf-8")
        return AnimationVisualCaptureExecution(capture_report, monitor_path, evidence_root)

    return run


def test_capture_packages_exact_grid_and_unsigned_review_template(config, tmp_path) -> None:
    request = _inputs(config, tmp_path)
    output = tmp_path / "visual-capture"

    package = capture_animation_visual_matrix(
        config, request, output, runner=_fake_runner()
    )

    manifest = json.loads(package.manifest.read_text(encoding="utf-8"))
    assert manifest["review_status"] == "manual_review_required"
    assert manifest["anatomy_acceptance"] == "not_assessed"
    assert len(manifest["cells"]) == 6
    assert len({cell["evidence"]["sha256"] for cell in manifest["cells"]}) == 6
    assert all((output / cell["evidence"]["path"]).is_file() for cell in manifest["cells"])
    assert all(cell["horizontal_root_motion_initial_offset_x"] == 0.25 for cell in manifest["cells"])
    template = json.loads(package.review_template.read_text(encoding="utf-8"))
    assert template["schema_version"] == "vandrel_foundry_animation_visual_matrix/1.0"
    assert template["reviewer"] is None and template["reviewed_at"] is None
    assert {cell["result"] for cell in template["cells"]} == {None}


@pytest.mark.parametrize(
    ("runner", "message"),
    [
        (_fake_runner(horizontal_delta=0.001), "root-motion policy"),
        (
            _fake_runner(
                horizontal_span_x=0.00008,
                horizontal_span_z=0.00008,
                horizontal_delta=0.000113137,
            ),
            "root-motion policy",
        ),
        (_fake_runner(duplicate=True), "not unique"),
        (_fake_runner(horizontal_delta=float("nan")), "root-motion policy"),
        (_fake_runner(crash_evidence=True), "monitored Godot evidence"),
    ],
)
def test_capture_rejects_laundered_or_repeated_evidence_without_partial_output(
    config, tmp_path, runner, message
) -> None:
    request = _inputs(config, tmp_path)
    output = tmp_path / "visual-capture"

    with pytest.raises(FoundryError, match=message):
        capture_animation_visual_matrix(config, request, output, runner=runner)

    assert not output.exists()
    failure = tmp_path / "visual-capture.failed"
    assert failure.is_dir()
    assert (failure / "sandbox" / "output" / "capture-report.json").is_file()


def test_capture_rejects_stale_library_before_runner(config, tmp_path) -> None:
    request = _inputs(config, tmp_path)
    (tmp_path / "animation_library.res").write_bytes(b"different library")

    with pytest.raises(FoundryError, match="animation library bytes"):
        capture_animation_visual_matrix(
            config,
            request,
            tmp_path / "visual-capture",
            runner=lambda *_args: pytest.fail("runner must not execute"),
        )


def test_capture_rejects_malformed_rest_leaf_completion_before_runner(
    config, tmp_path
) -> None:
    request_path = _inputs(config, tmp_path)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    technical_path = tmp_path / "technical.json"
    technical = json.loads(technical_path.read_text(encoding="utf-8"))
    technical["motions"][0]["optimized_rest_leaf_tracks_added"] = [
        {
            "bone": "Head",
            "path": "%GeneralSkeleton:Head",
            "track_index": 21,
            "track_type": 2,
            "interpolation_type": 1,
            "key_count": 2,
            "keys": [
                {
                    "time": time,
                    "value_x": 0.0,
                    "value_y": 0.0,
                    "value_z": 0.0,
                    "value_w": 1.0,
                    "finite": True,
                    "identity_rotation": True,
                }
                for time in (0.0, 1.0)
            ],
            "passed": True,
        }
    ]
    technical_path.write_text(json.dumps(technical), encoding="utf-8")
    request["technical_report"]["sha256"] = _sha(technical_path.read_bytes())
    request["technical_report"]["size_bytes"] = technical_path.stat().st_size
    request_path.write_text(json.dumps(request), encoding="utf-8")

    with pytest.raises(FoundryError, match="technical motion membership"):
        capture_animation_visual_matrix(
            config,
            request_path,
            tmp_path / "visual-capture",
            runner=lambda *_args: pytest.fail("runner must not execute"),
        )


def test_capture_stages_exact_unchanged_body_sidecars_and_bone_maps(
    config, tmp_path
) -> None:
    request_path = _inputs(config, tmp_path)
    request = json.loads(request_path.read_text(encoding="utf-8"))

    def inspect_staging(config, sandbox: Path, runtime_sha: str, script_sha: str):
        runtime = json.loads((sandbox / "animation-visual-runtime.json").read_text())
        assert _sha((sandbox / "animation-visual-runtime.json").read_bytes()) == runtime_sha
        project = (sandbox / "project.godot").read_text(encoding="utf-8")
        assert "run/main_scene" not in project
        for requested, staged in zip(request["bodies"], runtime["bodies"], strict=True):
            assert staged["path"] == requested["resource_path"]
            assert staged["staging_policy"] == (
                "accepted_exact_unchanged_godot_body_import_v1"
            )
            for requested_item, resource_key, staged_sha_key, staged_size_key in (
                (
                    requested,
                    "resource_path",
                    "staged_payload_sha256",
                    "staged_payload_size_bytes",
                ),
                (
                    requested["import_sidecar"],
                    "resource_path",
                    "staged_import_sidecar_sha256",
                    "staged_import_sidecar_size_bytes",
                ),
                (
                    requested["bone_map"],
                    "resource_path",
                    "staged_bone_map_sha256",
                    "staged_bone_map_size_bytes",
                ),
            ):
                staged_path = sandbox / requested_item[resource_key].removeprefix("res://")
                source_path = tmp_path / requested_item["path"]
                assert staged_path.read_bytes() == source_path.read_bytes()
                assert _sha(staged_path.read_bytes()) == requested_item["sha256"]
                assert staged_path.stat().st_size == requested_item["size_bytes"]
                assert staged[staged_sha_key] == requested_item["sha256"]
                assert staged[staged_size_key] == requested_item["size_bytes"]
        return _fake_runner()(config, sandbox, runtime_sha, script_sha)

    package = capture_animation_visual_matrix(
        config,
        request_path,
        tmp_path / "visual-capture",
        runner=inspect_staging,
    )

    report = json.loads(package.capture_report.read_text(encoding="utf-8"))
    assert all(
        body["staging_policy"] == "accepted_exact_unchanged_godot_body_import_v1"
        for body in report["bodies"]
    )


@pytest.mark.parametrize(
    ("relative", "message"),
    [
        ("female_average.fbx.import", "import sidecar bytes"),
        ("shared_bone_map.tres", "BoneMap bytes"),
    ],
)
def test_capture_rejects_changed_sidecar_or_bone_map_before_runner(
    config, tmp_path, relative, message
) -> None:
    request = _inputs(config, tmp_path)
    (tmp_path / relative).write_bytes(b"changed accepted import policy")

    with pytest.raises(FoundryError, match=message):
        capture_animation_visual_matrix(
            config,
            request,
            tmp_path / "visual-capture",
            runner=lambda *_args: pytest.fail("runner must not execute"),
        )


@pytest.mark.parametrize("binding", ["body", "bone_map"])
def test_capture_rejects_rehashed_sidecar_with_different_embedded_paths(
    config, tmp_path, binding
) -> None:
    request_path = _inputs(config, tmp_path)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    sidecar_path = tmp_path / request["bodies"][0]["import_sidecar"]["path"]
    accepted_path = (
        request["bodies"][0]["resource_path"]
        if binding == "body"
        else request["bodies"][0]["bone_map"]["resource_path"]
    )
    changed = sidecar_path.read_text(encoding="utf-8").replace(
        accepted_path,
        f"res://different/{binding}",
    )
    sidecar_path.write_text(changed, encoding="utf-8")
    changed_bytes = sidecar_path.read_bytes()
    request["bodies"][0]["import_sidecar"]["sha256"] = _sha(changed_bytes)
    request["bodies"][0]["import_sidecar"]["size_bytes"] = len(changed_bytes)
    request_path.write_text(json.dumps(request), encoding="utf-8")

    with pytest.raises(FoundryError, match="not the accepted body policy"):
        capture_animation_visual_matrix(
            config,
            request_path,
            tmp_path / "visual-capture",
            runner=lambda *_args: pytest.fail("runner must not execute"),
        )


@pytest.mark.parametrize(
    ("accepted", "rejected"),
    [
        (
            '"PATH:Armature/Skeleton3D": {',
            '"PATH:Armature/WrongSkeleton": {',
        ),
        (
            '"retarget/rest_fixer/retarget_method": 1',
            '"retarget/rest_fixer/retarget_method": 0',
        ),
        ("animation/import=false", "animation/import=true"),
    ],
)
def test_capture_rejects_rehashed_sidecar_with_changed_structured_policy(
    config, tmp_path, accepted, rejected
) -> None:
    request_path = _inputs(config, tmp_path)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    sidecar_binding = request["bodies"][0]["import_sidecar"]
    sidecar_path = tmp_path / sidecar_binding["path"]
    value = sidecar_path.read_text(encoding="utf-8")
    assert value.count(accepted) == 1
    sidecar_path.write_text(value.replace(accepted, rejected), encoding="utf-8")
    changed_bytes = sidecar_path.read_bytes()
    sidecar_binding["sha256"] = _sha(changed_bytes)
    sidecar_binding["size_bytes"] = len(changed_bytes)
    request_path.write_text(json.dumps(request), encoding="utf-8")

    with pytest.raises(FoundryError, match="not the accepted body policy"):
        capture_animation_visual_matrix(
            config,
            request_path,
            tmp_path / "visual-capture",
            runner=lambda *_args: pytest.fail("runner must not execute"),
        )


@pytest.mark.parametrize("mutation", ["omitted", "extra"])
def test_capture_rejects_nonexact_skeleton_policy_dictionary(
    config, tmp_path, mutation
) -> None:
    request_path = _inputs(config, tmp_path)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    sidecar_binding = request["bodies"][0]["import_sidecar"]
    sidecar_path = tmp_path / sidecar_binding["path"]
    value = sidecar_path.read_text(encoding="utf-8")
    if mutation == "omitted":
        accepted = '"retarget/rest_fixer/fix_silhouette/filter": [],\n'
        assert value.count(accepted) == 1
        changed = value.replace(accepted, "")
    else:
        accepted = '"retarget/rest_fixer/retarget_method": 1\n'
        assert value.count(accepted) == 1
        changed = value.replace(
            accepted,
            '"retarget/rest_fixer/retarget_method": 1,\n'
            '"foundry/unreviewed_extra": true\n',
        )
    sidecar_path.write_text(changed, encoding="utf-8")
    changed_bytes = sidecar_path.read_bytes()
    sidecar_binding["sha256"] = _sha(changed_bytes)
    sidecar_binding["size_bytes"] = len(changed_bytes)
    request_path.write_text(json.dumps(request), encoding="utf-8")

    with pytest.raises(FoundryError, match="not the accepted body policy"):
        capture_animation_visual_matrix(
            config,
            request_path,
            tmp_path / "visual-capture",
            runner=lambda *_args: pytest.fail("runner must not execute"),
        )


def test_capture_cli_exposes_request_and_output_directory(config_data, tmp_path, monkeypatch):
    config_path = tmp_path / "foundry.toml"
    write_config(config_path, config_data)
    request = tmp_path / "request.json"
    request.write_text("{}", encoding="utf-8")
    output = tmp_path / "capture"
    observed = {}

    def fake_capture(settings, request_path, output_directory):
        observed["request"] = request_path
        observed["output"] = output_directory
        return SimpleNamespace(
            manifest=output_directory / "capture-manifest.json",
            review_template=output_directory / "review-template.json",
        )

    monkeypatch.setattr(cli, "capture_animation_visual_matrix", fake_capture)
    result = CliRunner().invoke(
        app,
        [
            "capture-animation-visual-matrix",
            "--request",
            str(request),
            "--output-directory",
            str(output),
            "--config",
            str(config_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert observed == {"request": request, "output": output}
    assert "Unsigned review template" in result.output


def test_monitored_adapter_binds_exact_workload_without_launch(config, tmp_path) -> None:
    sandbox = tmp_path / "sandbox"
    (sandbox / "output" / "cells").mkdir(parents=True)
    executable = tmp_path / "Godot_console.exe"
    executable.write_bytes(b"godot")
    powershell = tmp_path / "pwsh.exe"
    powershell.write_bytes(b"pwsh")
    config.tools.godot_executable = executable
    observed = {}

    def fake_process(arguments, cwd, environment, timeout_seconds, maximum_output_bytes):
        observed.update(
            arguments=list(arguments),
            cwd=cwd,
            environment=dict(environment),
            timeout_seconds=timeout_seconds,
            maximum_output_bytes=maximum_output_bytes,
        )
        return CaptureProcessResult(0, "", "", False, False, 0.1)

    result = run_monitored_animation_visual_capture(
        config,
        sandbox,
        "a" * 64,
        "b" * 64,
        runner=fake_process,
        environment={"PATH": str(tmp_path), "SECRET": "must-not-pass"},
        supervisor_executable=powershell,
    )

    assert result.capture_report == sandbox / "output" / "capture-report.json"
    assert observed["timeout_seconds"] == config.tools.godot_timeout_seconds * 2 + 60
    assert observed["environment"] == {"PATH": str(tmp_path)}
    assert "SECRET" not in observed["environment"]
    for value in ("a" * 64, "b" * 64, CAMERA_CONFIG_SHA256):
        assert value in observed["arguments"]


def test_godot_capture_script_binds_python_camera_hash() -> None:
    script = (
        Path(__file__).parents[1]
        / "src"
        / "vandrel_foundry"
        / "godot"
        / "capture_animation_visual_matrix.gd"
    ).read_text(encoding="utf-8")
    assert f'EXPECTED_CAMERA_CONFIG_SHA256 := "{CAMERA_CONFIG_SHA256}"' in script
    assert "func _init()" not in script
    assert "func _initialize() -> void:" in script
    assert f'EXPECTED_ENTRY_SENTINEL_SHA256 := "{ENTRY_SENTINEL_SHA256}"' in script
    assert 'const ENTRY_SENTINEL_PATH := "res://output/capture-entry.json"' in script
    sentinel_write = script.index("entry_file.store_string(ENTRY_SENTINEL_TEXT)")
    deferred_run = script.index('call_deferred("_run")')
    assert sentinel_write < deferred_run
    sanitize = script.index("_sanitize_imported_body(body_root)")
    add_to_world = script.index("world.add_child(body_root)")
    assert sanitize < add_to_world
    for prohibited in (
        "Camera3D",
        "WorldEnvironment",
        "Light3D",
        "AnimationTree",
        "AnimationPlayer",
    ):
        assert f"child is {prohibited}" in script
    assert "Vector2(value.x - initial_x, value.z - initial_z).length()" in script
    for membership_guard in (
        "actual_semantics.sort()",
        "expected_semantics.sort()",
        "actual_semantics.size() != expected_semantics.size()",
        "_has_duplicate_names(actual_semantics)",
        "_has_duplicate_names(expected_semantics)",
        "actual_semantics != expected_semantics",
    ):
        assert membership_guard in script
    for exact_body_binding in (
        '"staged_payload_sha256": str(body.staged_payload_sha256)',
        '"import_sidecar_sha256": sidecar_sha',
        '"staged_import_sidecar_sha256": str(body.staged_import_sidecar_sha256)',
        '"bone_map_sha256": bone_map_sha',
        '"staged_bone_map_sha256": str(body.staged_bone_map_sha256)',
    ):
        assert exact_body_binding in script


def test_capture_rejects_exit_zero_without_scenetree_entry_sentinel(
    config, tmp_path
) -> None:
    request = _inputs(config, tmp_path)

    def zero_without_entry(*args):
        execution = _fake_runner()(*args)
        (args[1] / "output" / "capture-entry.json").unlink()
        return execution

    with pytest.raises(FoundryError, match="without entering the SceneTree script"):
        capture_animation_visual_matrix(
            config,
            request,
            tmp_path / "visual-capture",
            runner=zero_without_entry,
        )


def test_visual_capture_supervisor_constructs_exact_engine_argv() -> None:
    supervisor = (
        Path(__file__).parents[1]
        / "src"
        / "vandrel_foundry"
        / "godot"
        / "Invoke-FoundryAnimationVisualCaptureMonitored.ps1"
    ).read_text(encoding="utf-8")
    assert "$resolvedSandbox = (Resolve-Path -LiteralPath $SandboxPath).Path" in supervisor
    assert "-WorkingDirectory $resolvedSandbox" in supervisor
    assert (
        "$arguments = @('--path', $resolvedSandbox) + "
        "@($phase.arguments) + @('--log-file', $godotLog)"
    ) in supervisor
    import_spec = supervisor.split("name = 'import'", 1)[1].split(" },", 1)[0]
    assert "--headless" in import_spec
    assert (
        "arguments = @('--script', "
        "'res://capture_animation_visual_matrix.gd')"
    ) in supervisor
    capture_spec = supervisor.split("name = 'capture'", 1)[1].split(")\n", 1)[0]
    assert "--headless" not in capture_spec
    assert "--quit-after" not in capture_spec
    assert "'--'" not in supervisor


def test_supervisor_preflight_failure_writes_structured_monitor(tmp_path) -> None:
    powershell = shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell 7 is unavailable")
    source_root = Path(__file__).parents[1] / "src" / "vandrel_foundry" / "godot"
    supervisor = source_root / "Invoke-FoundryAnimationVisualCaptureMonitored.ps1"
    sandbox = tmp_path / "sandbox"
    output = sandbox / "output"
    output.mkdir(parents=True)
    runtime = sandbox / "animation-visual-runtime.json"
    runtime.write_text("{}", encoding="utf-8")
    capture_script = sandbox / "capture_animation_visual_matrix.gd"
    capture_script.write_bytes((source_root / capture_script.name).read_bytes())

    result = subprocess.run(
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(supervisor),
            "-GodotExe",
            str(tmp_path / "MissingGodot_console.exe"),
            "-SandboxPath",
            str(sandbox),
            "-TimeoutSeconds",
            "1",
            "-MaximumOutputBytes",
            "4096",
            "-RuntimeRequestSha256",
            _sha(runtime.read_bytes()),
            "-CaptureScriptSha256",
            _sha(capture_script.read_bytes()),
            "-CameraConfigSha256",
            CAMERA_CONFIG_SHA256,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode != 0
    monitor_path = output / "animation-visual-godot-monitor.json"
    monitor = json.loads(monitor_path.read_text(encoding="utf-8"))
    assert monitor["passed"] is False
    assert monitor["failure_stage"] == "preflight_or_supervision"
    assert "does not exist" in monitor["failure_message"]
    assert monitor["preflights"] == {
        "sandbox": True,
        "godot_console": False,
        "runtime_request": True,
        "capture_script": True,
        "camera_config": True,
        "initial_process_zero": False,
    }
    assert monitor["phase_results"] == []


def test_capture_blocks_unchanged_retry_until_failed_attempt_is_dispositioned(
    config, tmp_path
) -> None:
    request = _inputs(config, tmp_path)
    output = tmp_path / "visual-capture"
    with pytest.raises(FoundryError, match="root-motion policy"):
        capture_animation_visual_matrix(
            config, request, output, runner=_fake_runner(horizontal_delta=0.001)
        )

    with pytest.raises(FoundryError, match="Prior visual capture failure evidence"):
        capture_animation_visual_matrix(
            config,
            request,
            output,
            runner=lambda *_args: pytest.fail("unchanged input must not be retried"),
        )


@pytest.mark.parametrize(
    ("timed_out", "output_limited", "reason", "message"),
    [
        (True, False, "outer_timeout", "timed out"),
        (False, True, "outer_output_limit", "output limit"),
    ],
)
def test_outer_watchdog_failure_is_bounded_and_retained_without_supervisor_monitor(
    config,
    tmp_path,
    timed_out,
    output_limited,
    reason,
    message,
) -> None:
    request = _inputs(config, tmp_path)
    config.tools.maximum_output_bytes = 32
    powershell = tmp_path / "pwsh.exe"
    powershell.write_bytes(b"not launched")

    def capture_runner(settings, sandbox, runtime_sha, script_sha):
        def failed_process(*_args):
            (sandbox / ".foundry-capture-outer-stdout.tmp").write_bytes(b"S" * 100)
            (sandbox / ".foundry-capture-outer-stderr.tmp").write_bytes(b"E" * 100)
            return CaptureProcessResult(
                return_code=1,
                stdout="S" * 100,
                stderr="E" * 100,
                timed_out=timed_out,
                output_limited=output_limited,
                duration_seconds=3.0,
            )

        return run_monitored_animation_visual_capture(
            settings,
            sandbox,
            runtime_sha,
            script_sha,
            runner=failed_process,
            supervisor_executable=powershell,
        )

    output = tmp_path / "visual-capture"
    with pytest.raises(FoundryError, match=message) as failure_info:
        capture_animation_visual_matrix(
            config,
            request,
            output,
            runner=capture_runner,
        )

    failure_root = tmp_path / "visual-capture.failed" / "sandbox" / "output"
    watchdog = json.loads((failure_root / OUTER_WATCHDOG_PATH).read_text("utf-8"))
    assert watchdog["reason"] == reason
    assert watchdog["supervisor_monitor_present"] is False
    assert watchdog["maximum_output_bytes"] == 32
    assert watchdog["process_result"]["timed_out"] is timed_out
    assert watchdog["process_result"]["output_limited"] is output_limited
    assert watchdog["raw_temp_cleanup"] == {
        "attempted": True,
        "failed": False,
        "issue_excerpt": None,
        "issue_truncated": False,
    }
    assert not (failure_root / "animation-visual-godot-monitor.json").exists()
    assert "Outer watchdog evidence" in str(failure_info.value)
    retained_size = 0
    for stream in ("stdout_evidence", "stderr_evidence"):
        binding = watchdog[stream]
        payload = (failure_root / binding["path"]).read_bytes()
        retained_size += len(payload)
        assert binding["sha256"] == _sha(payload)
        assert binding["source_size_bytes"] == 100
        assert binding["truncated"] is True
    assert retained_size == 32
    failure_sandbox = failure_root.parent
    assert not (failure_sandbox / ".foundry-capture-outer-stdout.tmp").exists()
    assert not (failure_sandbox / ".foundry-capture-outer-stderr.tmp").exists()


def test_outer_watchdog_records_cleanup_issue_without_replacing_timeout_reason(
    config, tmp_path, monkeypatch
) -> None:
    request = _inputs(config, tmp_path)
    config.tools.maximum_output_bytes = 32
    powershell = tmp_path / "pwsh.exe"
    powershell.write_bytes(b"not launched")
    original_remove = capture_runner_module._remove_outer_temp_file
    failed_once: set[Path] = set()

    def fail_first_remove(path: Path) -> None:
        if path not in failed_once:
            failed_once.add(path)
            raise OSError("simulated first raw-temp removal failure")
        original_remove(path)

    monkeypatch.setattr(
        capture_runner_module,
        "_remove_outer_temp_file",
        fail_first_remove,
    )

    def capture_runner(settings, sandbox, runtime_sha, script_sha):
        def failed_process(*_args):
            (sandbox / ".foundry-capture-outer-stdout.tmp").write_bytes(b"S" * 100)
            (sandbox / ".foundry-capture-outer-stderr.tmp").write_bytes(b"E" * 100)
            return CaptureProcessResult(1, "", "", True, False, 3.0)

        return run_monitored_animation_visual_capture(
            settings,
            sandbox,
            runtime_sha,
            script_sha,
            runner=failed_process,
            supervisor_executable=powershell,
        )

    with pytest.raises(FoundryError, match="timed out") as failure_info:
        capture_animation_visual_matrix(
            config,
            request,
            tmp_path / "visual-capture",
            runner=capture_runner,
        )

    failure_sandbox = tmp_path / "visual-capture.failed" / "sandbox"
    watchdog = json.loads(
        (failure_sandbox / "output" / OUTER_WATCHDOG_PATH).read_text("utf-8")
    )
    assert watchdog["reason"] == "outer_timeout"
    assert watchdog["raw_temp_cleanup"]["attempted"] is True
    assert watchdog["raw_temp_cleanup"]["failed"] is True
    assert "simulated first raw-temp removal failure" in watchdog["raw_temp_cleanup"][
        "issue_excerpt"
    ]
    assert "Raw temp cleanup issue" in str(failure_info.value)
    assert "timed out" in str(failure_info.value)
    assert not (failure_sandbox / ".foundry-capture-outer-stdout.tmp").exists()
    assert not (failure_sandbox / ".foundry-capture-outer-stderr.tmp").exists()


def test_persistent_raw_temp_removal_failure_uses_filtered_bounded_retention(
    config, tmp_path, monkeypatch
) -> None:
    request = _inputs(config, tmp_path)
    config.tools.maximum_output_bytes = 32
    powershell = tmp_path / "pwsh.exe"
    powershell.write_bytes(b"not launched")
    remove_attempts = 0
    original_copy = capture_service_module._copy_new
    cache_removed = False
    capture_sandbox: Path | None = None

    def always_fail_remove(_path: Path) -> None:
        nonlocal remove_attempts
        remove_attempts += 1
        raise OSError("simulated persistent raw-temp removal failure")

    monkeypatch.setattr(
        capture_runner_module,
        "_remove_outer_temp_file",
        always_fail_remove,
    )

    def copy_while_cache_disappears(source: Path, destination: Path) -> None:
        nonlocal cache_removed
        if not cache_removed and capture_sandbox is not None:
            cache = capture_sandbox / ".godot"
            if cache.is_dir():
                shutil.rmtree(cache)
            cache_removed = True
        original_copy(source, destination)

    monkeypatch.setattr(
        capture_service_module,
        "_copy_new",
        copy_while_cache_disappears,
    )

    def capture_runner(settings, sandbox, runtime_sha, script_sha):
        nonlocal capture_sandbox
        capture_sandbox = sandbox

        def failed_process(*_args):
            (sandbox / ".foundry-capture-outer-stdout.tmp").write_bytes(b"S" * 100)
            (sandbox / ".foundry-capture-outer-stderr.tmp").write_bytes(b"E" * 100)
            cache = sandbox / ".godot" / "editor"
            cache.mkdir(parents=True)
            (cache / "volatile-cache.tmp").write_bytes(b"transient")
            return CaptureProcessResult(1, "", "", True, False, 3.0)

        return run_monitored_animation_visual_capture(
            settings,
            sandbox,
            runtime_sha,
            script_sha,
            runner=failed_process,
            supervisor_executable=powershell,
        )

    with pytest.raises(FoundryError, match="timed out") as failure_info:
        capture_animation_visual_matrix(
            config,
            request,
            tmp_path / "visual-capture",
            runner=capture_runner,
        )

    assert remove_attempts == 4
    failure_directory = tmp_path / "visual-capture.failed"
    failure_output = failure_directory / "sandbox" / "output"
    watchdog = json.loads((failure_output / OUTER_WATCHDOG_PATH).read_text("utf-8"))
    assert watchdog["reason"] == "outer_timeout"
    assert watchdog["raw_temp_cleanup"]["failed"] is True
    assert "persistent raw-temp removal failure" in watchdog["raw_temp_cleanup"][
        "issue_excerpt"
    ]
    retained_size = 0
    for stream in ("stdout_evidence", "stderr_evidence"):
        binding = watchdog[stream]
        payload = (failure_output / binding["path"]).read_bytes()
        retained_size += len(payload)
        assert binding["sha256"] == _sha(payload)
        assert binding["source_size_bytes"] == 100
        assert binding["truncated"] is True
    assert retained_size == 32
    assert not [
        path
        for path in failure_directory.rglob("*")
        if path.name.startswith(".foundry-capture-outer-")
    ]
    assert cache_removed is True
    assert not [path for path in failure_directory.rglob("*") if path.name == ".godot"]
    for relative in (
        "sandbox/animation-visual-runtime.json",
        "sandbox/project.godot",
        "sandbox/capture_animation_visual_matrix.gd",
        "sandbox/library/animation_library.res",
        "sandbox/library/technical-report.json",
        (
            "sandbox/mods/CavemanMod/assets/game/scenes/actors/rigs/caveman/"
            "MeshyShared/bodies/female_average/female_average.fbx"
        ),
        (
            "sandbox/mods/CavemanMod/assets/game/scenes/actors/rigs/caveman/"
            "MeshyShared/bodies/male_average/male_average.fbx"
        ),
        (
            "sandbox/mods/CavemanMod/assets/candidates/"
            "meshy_godot_shared_animation_canary/bodies/feral_apeman/"
            "feral_apeman.fbx"
        ),
    ):
        assert (failure_directory / relative).is_file()
    failure_message = str(failure_info.value)
    assert "timed out" in failure_message
    assert "Raw temp cleanup issue" in failure_message
    assert "Persistent raw-temp cleanup failure" in failure_message
    assert "Residual raw operation root:" in failure_message
    residual_roots = [
        path
        for path in tmp_path.iterdir()
        if path.is_dir() and path.name.startswith(".visual-capture-")
    ]
    assert len(residual_roots) == 1
    assert str(residual_roots[0]) in failure_message
    assert (residual_roots[0] / "sandbox" / ".foundry-capture-outer-stdout.tmp").is_file()
    assert (residual_roots[0] / "sandbox" / ".foundry-capture-outer-stderr.tmp").is_file()


def test_filtered_retention_accepts_exact_supervisor_monitor_with_residual_raw_temps(
    config, tmp_path
) -> None:
    request = _inputs(config, tmp_path)
    observed_monitor: dict[str, object] = {}

    def supervisor_monitored_nonzero(config, sandbox, runtime_sha, script_sha):
        execution = _fake_runner()(config, sandbox, runtime_sha, script_sha)
        monitor = json.loads(execution.monitor_report.read_text(encoding="utf-8"))
        monitor["passed"] = False
        monitor["failure_stage"] = "phase:capture"
        monitor["failure_message"] = "capture phase exited nonzero"
        monitor["phase_results"][-1]["exit_code"] = 1
        execution.monitor_report.write_text(json.dumps(monitor), encoding="utf-8")
        monitor_bytes = execution.monitor_report.read_bytes()
        observed_monitor.update(sha256=_sha(monitor_bytes), size_bytes=len(monitor_bytes))
        (sandbox / ".foundry-capture-outer-stdout.tmp").write_bytes(b"raw stdout")
        (sandbox / ".foundry-capture-outer-stderr.tmp").write_bytes(b"raw stderr")
        raise FoundryError("supervisor-monitored capture exited nonzero")

    with pytest.raises(FoundryError, match="supervisor-monitored capture exited nonzero"):
        capture_animation_visual_matrix(
            config,
            request,
            tmp_path / "visual-capture",
            runner=supervisor_monitored_nonzero,
        )

    failure_directory = tmp_path / "visual-capture.failed"
    retained_monitor = (
        failure_directory
        / "sandbox"
        / "output"
        / "animation-visual-godot-monitor.json"
    )
    assert retained_monitor.is_file()
    assert _sha(retained_monitor.read_bytes()) == observed_monitor["sha256"]
    assert retained_monitor.stat().st_size == observed_monitor["size_bytes"]
    assert not (
        failure_directory / "sandbox" / "output" / "animation-visual-outer-watchdog.json"
    ).exists()
    assert not [
        path
        for path in failure_directory.rglob("*")
        if path.name.startswith(".foundry-capture-outer-")
    ]
    residual_roots = [
        path
        for path in tmp_path.iterdir()
        if path.is_dir() and path.name.startswith(".visual-capture-")
    ]
    assert len(residual_roots) == 1
    source_monitor = (
        residual_roots[0]
        / "sandbox"
        / "output"
        / "animation-visual-godot-monitor.json"
    )
    assert source_monitor.is_file()
    assert _sha(source_monitor.read_bytes()) == observed_monitor["sha256"]
