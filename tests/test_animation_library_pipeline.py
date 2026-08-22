import hashlib
import json
from pathlib import Path

import pytest

import vandrel_foundry.services.animation_library as animation_service
import vandrel_foundry.services.plan_release as plan_release_service
import vandrel_foundry.storage.manifests as manifest_storage
from tests.conftest import bind_documented_test_custody
from vandrel_foundry.domain.animation_library import (
    ANIMATION_CARRIER_BAKE_IMPORT_POLICY,
    ANIMATION_IMPORT_POLICY,
    CARRIER_BAKE_POLICY,
    CARRIER_REMOVE_POLICY,
    FIXED_PHASES,
)
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.lanes import LaneConfiguration
from vandrel_foundry.services.animation_library import (
    AnimationPipelineExecution,
    approve_animation_library,
    import_animation_visual_matrix,
    intake_animation_library,
    normalize_animation_library,
)
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.plan_release import plan_release
from vandrel_foundry.storage.manifests import ManifestRepository

ASSET_ID = "b2_selective_reactions_001"


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _lanes() -> LaneConfiguration:
    return LaneConfiguration.model_validate(
        {
            "lanes": {
                "animation_library": {
                    "wrapper_template": "animation_library",
                    "collision_policy": "none",
                    "requires_materials": False,
                    "requires_skeleton": True,
                    "release_enabled": True,
                }
            }
        }
    )


def _create_candidate(config, prompt: Path) -> None:
    create_asset(
        config,
        _lanes(),
        ASSET_ID,
        "animation_library",
        "B2 Selective Reactions",
        prompt,
    )


def _configure_fake_godot(config, tmp_path: Path) -> None:
    executable = tmp_path / "Godot_console.exe"
    executable.write_bytes(b"fake Godot console identity")
    config.tools.godot_executable = executable


def _request(tmp_path: Path, *, duplicate_hash: bool = False) -> Path:
    first = b"first exact fbx"
    second = first if duplicate_hash else b"second exact fbx"
    (tmp_path / "first.fbx").write_bytes(first)
    (tmp_path / "second.fbx").write_bytes(second)
    policy = {
        "schema_version": "vandrel_foundry_animation_package_policy/1.0",
        "policy_id": "b2_selective_reactions_v1",
        "exact_selected_source_sha256s": [_sha(first), _sha(second)],
        "exact_excluded_source_sha256s": ["a" * 64],
        "forbidden_aggregate_payload_sha256s": ["f" * 64],
        "superseded_route_ids": [
            "historical_one_fbx_canary_carrier",
            "historical_complete_reaction_bundle",
            "historical_body_bound_motion_routes",
        ],
    }
    value = {
        "schema_version": "vandrel_foundry_animation_library_intake/1.0",
        "asset_id": ASSET_ID,
        "import_policy": ANIMATION_IMPORT_POLICY,
        "motions": [
            {
                "semantic": "AngryStomp",
                "source_path": "first.fbx",
                "source_sha256": _sha(first),
                "source_size_bytes": len(first),
                "loop_mode": "none",
            },
            {
                "semantic": "StandDodge",
                "source_path": "second.fbx",
                "source_sha256": _sha(second),
                "source_size_bytes": len(second),
                "loop_mode": "none",
            },
        ],
        "explicit_exclusions": [
            {"semantic": "FallAbdominal", "source_sha256": "a" * 64, "reason": "failed"}
        ],
        "package_policy": policy,
        "package_policy_sha256": _sha(
            (json.dumps(policy, indent=2, ensure_ascii=False) + "\n").encode()
        ),
    }
    path = tmp_path / "request.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _one_motion_request(tmp_path: Path) -> Path:
    value = json.loads(_request(tmp_path).read_text(encoding="utf-8"))
    value["motions"] = value["motions"][:1]
    policy = value["package_policy"]
    policy["exact_selected_source_sha256s"] = policy[
        "exact_selected_source_sha256s"
    ][:1]
    value["package_policy_sha256"] = _sha(
        (json.dumps(policy, indent=2, ensure_ascii=False) + "\n").encode()
    )
    path = tmp_path / "one-motion-request.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _sleep_carrier_bake_request(tmp_path: Path) -> Path:
    value = json.loads(_one_motion_request(tmp_path).read_text(encoding="utf-8"))
    value["import_policy"] = ANIMATION_CARRIER_BAKE_IMPORT_POLICY
    value["motions"][0]["semantic"] = "SleepNormally"
    value["motions"][0]["carrier_orientation_policy"] = CARRIER_BAKE_POLICY
    path = tmp_path / "sleep-carrier-bake-request.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _carrier_bake_fact() -> dict:
    half = 2**-0.5
    carrier = {
        "x": half,
        "y": 0.0,
        "z": 0.0,
        "w": half,
        "length": 1.0,
        "finite": True,
        "unit": True,
    }
    identity = {
        "x": 0.0,
        "y": 0.0,
        "z": 0.0,
        "w": 1.0,
        "length": 1.0,
        "finite": True,
        "unit": True,
    }
    hips_pre = {
        "x": 0.0,
        "y": half,
        "z": 0.0,
        "w": half,
        "length": 1.0,
        "finite": True,
        "unit": True,
    }
    carrier_times_hips = {
        "x": 0.5,
        "y": 0.5,
        "z": 0.5,
        "w": 0.5,
        "length": 1.0,
        "finite": True,
        "unit": True,
    }
    rotation_common = {
        "track_index": 2,
        "path": "%GeneralSkeleton:Hips",
        "type": 2,
        "key_count": 2,
        "interpolation_type": 1,
        "interpolation_loop_wrap": True,
    }
    root_pre = {
        "track_index": 1,
        "path": "%GeneralSkeleton:Hips",
        "type": 1,
        "key_count": 3,
        "interpolation_type": 1,
        "interpolation_loop_wrap": True,
        "keys": [
            {
                "time": 0.0,
                "transition": 1.0,
                "x": 0.25,
                "y": 1.0,
                "z": -0.1,
                "finite": True,
            },
            {
                "time": 0.5,
                "transition": 0.8,
                "x": 0.4,
                "y": 0.9,
                "z": 0.2,
                "finite": True,
            },
            {
                "time": 1.0,
                "transition": 1.0,
                "x": 0.1,
                "y": 0.8,
                "z": 0.0,
                "finite": True,
            },
        ],
    }
    root_post = json.loads(json.dumps(root_pre))
    root_post["keys"][0].update({"y": 0.1, "z": 1.0})
    root_post["keys"][1].update({"y": -0.2, "z": 0.9})
    root_post["keys"][2].update({"y": 0.0, "z": 0.8})
    return {
        "policy": CARRIER_BAKE_POLICY,
        "applied": True,
        "passed": True,
        "rotation_composition_order": "carrier_times_hips",
        "position_transform": "carrier_rotate_hips_position",
        "carrier_position_track_count": 0,
        "carrier_scale_track_count": 0,
        "carrier_other_track_count": 0,
        "carrier": {
            "track_index": 0,
            "path": "Armature",
            "type": 2,
            "key_count": 1,
            "key_time": 0.0,
            "interpolation_type": 1,
            "interpolation_loop_wrap": True,
            "quaternion": carrier,
        },
        "hips_rotation_pre": rotation_common
        | {
            "keys": [
                {"time": 0.0, "transition": 1.0, "quaternion": hips_pre},
                {"time": 1.0, "transition": 1.0, "quaternion": identity},
            ]
        },
        "hips_rotation_post": rotation_common
        | {
            "keys": [
                {
                    "time": 0.0,
                    "transition": 1.0,
                    "quaternion": carrier_times_hips,
                },
                {"time": 1.0, "transition": 1.0, "quaternion": carrier},
            ]
        },
        "hips_root_pre": root_pre,
        "hips_root_post": root_post,
        "carrier_removed": True,
        "rotation_key_structure_preserved": True,
        "root_key_structure_preserved": True,
        "root_values_transformed": True,
    }


def _fake_pipeline(config, sandbox: Path) -> AnimationPipelineExecution:
    library = b"selective animation library"
    library_path = sandbox / "output" / "animation_library.res"
    library_path.write_bytes(library)
    runtime = json.loads((sandbox / "animation-library-runtime.json").read_text())
    library_sha = _sha(library)
    technical = {
        "schema_version": "vandrel_foundry_animation_library_technical/1.0",
        "import_policy": runtime["import_policy"],
        "horizontal_root_policy": animation_service.HIPS_HORIZONTAL_POLICY,
        "animation_library_sha256": library_sha,
        "animation_library_size_bytes": len(library),
        "motions": [
            {
                "semantic": item["semantic"],
                "source_sha256": item["source_sha256"],
                "source_size_bytes": item["source_size_bytes"],
                "hips_position_track_count": 1,
                "mapped_rotation_track_count": 22,
                "scale_track_count": 0,
                "non_hips_position_track_count": 0,
                "other_track_count": 0,
                "finite_keys": True,
                "hips_horizontal_transform_policy": animation_service.HIPS_HORIZONTAL_POLICY,
                "hips_horizontal_transform_applied": True,
                "hips_vertical_time_interpolation_preserved": True,
                "hips_horizontal_pre_transform": {
                    "span_x": 0.4,
                    "span_z": 0.3,
                    "max_delta_from_first": 0.5,
                    "initial_offset_x": 0.25,
                    "initial_offset_z": -0.1,
                    "key_count": 3,
                    "finite": True,
                },
                "hips_horizontal_post_transform": {
                    "span_x": 0.0,
                    "span_z": 0.0,
                    "max_delta_from_first": 0.0,
                    "initial_offset_x": 0.25,
                    "initial_offset_z": -0.1,
                    "key_count": 3,
                    "finite": True,
                },
                "hips_preservation_pre_transform": {
                    "track_interpolation_type": 1,
                    "track_interpolation_loop_wrap": True,
                    "keys": [
                        {"y": 0.0, "time": 0.0, "transition": 1.0},
                        {"y": 0.2, "time": 0.5, "transition": 0.8},
                        {"y": 0.0, "time": 1.0, "transition": 1.0},
                    ],
                    "finite": True,
                },
                "hips_preservation_post_transform": {
                    "track_interpolation_type": 1,
                    "track_interpolation_loop_wrap": True,
                    "keys": [
                        {"y": 0.0, "time": 0.0, "transition": 1.0},
                        {"y": 0.2, "time": 0.5, "transition": 0.8},
                        {"y": 0.0, "time": 1.0, "transition": 1.0},
                    ],
                    "finite": True,
                },
                "known_carrier_track_recognized_count": 1,
                "known_carrier_track_removed_count": 1,
                "known_carrier_tracks": [
                    {
                        "track_index": 0,
                        "path": "Armature",
                        "type": 2,
                        "key_count": 2,
                        "removed": True,
                    }
                ],
                "optimized_rest_leaf_completion_policy": (
                    animation_service.REST_LEAF_COMPLETION_POLICY
                ),
                "optimized_rest_leaf_animation_length": 1.0,
                "optimized_rest_leaf_tracks_added": [],
                "optimized_rest_leaf_completion_passed": True,
                "output_library_sha256": library_sha,
                "passed": True,
            }
            for item in runtime["motions"]
        ],
        "passed": True,
    }
    if runtime["import_policy"] == ANIMATION_CARRIER_BAKE_IMPORT_POLICY:
        for motion in technical["motions"]:
            motion["known_carrier_tracks"][0]["key_count"] = 1
            motion["carrier_orientation_policy"] = CARRIER_BAKE_POLICY
            motion["carrier_orientation_bake"] = _carrier_bake_fact()
            motion["hips_horizontal_pre_transform"] = {
                "span_x": 0.3,
                "span_z": 0.2,
                "max_delta_from_first": 0.25,
                "initial_offset_x": 0.25,
                "initial_offset_z": 1.0,
                "key_count": 3,
                "finite": True,
            }
            motion["hips_horizontal_post_transform"] = {
                "span_x": 0.0,
                "span_z": 0.0,
                "max_delta_from_first": 0.0,
                "initial_offset_x": 0.25,
                "initial_offset_z": 1.0,
                "key_count": 3,
                "finite": True,
            }
            preservation = {
                "track_interpolation_type": 1,
                "track_interpolation_loop_wrap": True,
                "keys": [
                    {"y": 0.1, "time": 0.0, "transition": 1.0},
                    {"y": -0.2, "time": 0.5, "transition": 0.8},
                    {"y": 0.0, "time": 1.0, "transition": 1.0},
                ],
                "finite": True,
            }
            motion["hips_preservation_pre_transform"] = preservation
            motion["hips_preservation_post_transform"] = json.loads(
                json.dumps(preservation)
            )
    technical_path = sandbox / "output" / "animation-library-technical.json"
    technical_path.write_text(json.dumps(technical), encoding="utf-8")
    isolation_path = sandbox / "output" / "animation-library-isolation.json"
    isolation_path.write_text(
        json.dumps(
            {
                "schema_version": "vandrel_foundry_animation_library_isolation/1.0",
                "animation_library_sha256": library_sha,
                "selected_semantics": [item["semantic"] for item in runtime["motions"]],
                "external_dependencies": [],
                "source_fbx_directory_present": False,
                "prior_import_cache_present": False,
                "passed": True,
            }
        ),
        encoding="utf-8",
    )
    supervisor = (
        Path(__file__).parents[1]
        / "src"
        / "vandrel_foundry"
        / "godot"
        / "Invoke-FoundryAnimationLibraryMonitored.ps1"
    )
    monitor = {
        "schema_version": "vandrel_foundry_animation_godot_monitor/1.0",
        "policy": "vandrel_monitored_godot_animation_library_corridor_2026-08-21",
        "run_started_utc": "2026-08-21T12:00:00Z",
        "run_ended_utc": "2026-08-21T12:00:05Z",
        "console_executable_name": "Godot_console.exe",
        "process_zero_preflight": True,
        "console_file_version": "4.7.2",
        "child_environment": {"DOTNET_ROLL_FORWARD": "LatestMajor"},
        "internal_iteration_bomb": 600,
        "outer_timeout_seconds_per_phase": int(config.tools.godot_timeout_seconds),
        "post_exit_poll_seconds": 5,
        "timed_out": False,
        "output_limited": False,
        "cleanup_failed": False,
        "cleanup_issue": "",
        "application_error_windows": [],
        "application_events": [],
        "has_crash_evidence": False,
        "final_godot_processes": [],
        "wer_and_dump_paths": [],
        "supervisor_sha256": _sha(supervisor.read_bytes()),
        "godot_console_sha256": _sha(config.tools.godot_executable.read_bytes()),
        "phases": [
            "initial_import",
            "configure_imports",
            "retargeted_import",
            "finalize_probe",
            "isolated_validate",
        ],
        "phase_results": [
            {
                "phase": phase,
                "started_utc": "2026-08-21T12:00:00Z",
                "ended_utc": "2026-08-21T12:00:01Z",
                "exit_code": 0,
                "stdout_path": f"{phase}.stdout",
                "stderr_path": f"{phase}.stderr",
                "godot_log_path": f"{phase}.godot",
            }
            for phase in (
                "initial_import",
                "configure_imports",
                "retargeted_import",
                "finalize_probe",
                "isolated_validate",
            )
        ],
        "passed": True,
    }
    monitor_path = sandbox / "output" / "animation-library-godot-monitor.json"
    monitor_path.parent.mkdir(parents=True, exist_ok=True)
    monitor_path.write_text(json.dumps(monitor), encoding="utf-8")
    return AnimationPipelineExecution(
        library_path, technical_path, isolation_path, monitor_path
    )


def _fake_failed_monitor(config, sandbox: Path) -> AnimationPipelineExecution:
    execution = _fake_pipeline(config, sandbox)
    value = json.loads(execution.monitor_report.read_text(encoding="utf-8"))
    value["cleanup_failed"] = True
    value["cleanup_issue"] = "run-owned process tree did not exit"
    value["passed"] = False
    execution.monitor_report.write_text(json.dumps(value), encoding="utf-8")
    return execution


def _assert_no_active_operations(config) -> None:
    root = config.foundry.workspace_root / "assets" / ASSET_ID / ".ops"
    assert not root.exists() or list(root.iterdir()) == []


def _visual_request(config, tmp_path: Path, *, failed: tuple[str, str] | None = None) -> Path:
    manifest = ManifestRepository(config.foundry.workspace_root).load(ASSET_ID)
    library = [item for item in manifest.artifacts if item.role == "processed_animation_library"][-1]
    technical = [
        item for item in manifest.artifacts if item.role == "animation_library_technical_report"
    ][-1]
    bodies = ["female_average", "male_average", "feral_apeman"]
    semantics = [
        item["semantic"]
        for item in manifest.vandrel_technical["animation_library_membership"]["selected"]
    ]
    cells = []
    for semantic in semantics:
        for body in bodies:
            evidence = f"fixed-phase:{semantic}:{body}".encode()
            evidence_name = f"{semantic}-{body}.png"
            (tmp_path / evidence_name).write_bytes(evidence)
            cells.append(
                {
                    "semantic": semantic,
                    "body_id": body,
                    "result": "FAIL" if failed == (semantic, body) else "PASS",
                    "observed_phases": list(FIXED_PHASES),
                    "evidence": [
                        {
                            "path": evidence_name,
                            "sha256": _sha(evidence),
                            "size_bytes": len(evidence),
                        }
                    ],
                    "notes": "fixed camera",
                }
            )
    value = {
        "schema_version": "vandrel_foundry_animation_visual_matrix/1.0",
        "asset_id": ASSET_ID,
        "animation_library_sha256": library.sha256,
        "technical_report_sha256": technical.sha256,
        "bodies": [
            {"body_id": body, "payload_sha256": _sha(f"payload:{body}".encode())}
            for body in bodies
        ],
        "camera_policy": "vandrel_fixed_animation_review_camera_v1",
        "camera_config_sha256": _sha(b"fixed camera config"),
        "reviewer": "Independent visual reviewer",
        "reviewed_at": "2026-08-21T12:00:00Z",
        "cells": cells,
    }
    path = tmp_path / "visual.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_intake_rejects_duplicate_bytes_and_request_policy_laundering(
    config, prompt, tmp_path
) -> None:
    _create_candidate(config, prompt)
    with pytest.raises(FoundryError, match="selected hashes must be unique"):
        intake_animation_library(config, ASSET_ID, _request(tmp_path, duplicate_hash=True))

    value = json.loads(_request(tmp_path).read_text())
    value["explicit_exclusions"] = []
    path = tmp_path / "laundered.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(FoundryError, match="Excluded sources differ"):
        intake_animation_library(config, ASSET_ID, path)


def test_one_motion_intake_still_requires_exact_package_membership(
    config, prompt, tmp_path
) -> None:
    _create_candidate(config, prompt)
    value = json.loads(_one_motion_request(tmp_path).read_text(encoding="utf-8"))
    value["package_policy"]["exact_selected_source_sha256s"] = ["b" * 64]
    value["package_policy_sha256"] = _sha(
        (
            json.dumps(value["package_policy"], indent=2, ensure_ascii=False) + "\n"
        ).encode()
    )
    path = tmp_path / "one-motion-mismatched-policy.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(FoundryError, match="Selected sources differ"):
        intake_animation_library(config, ASSET_ID, path)


@pytest.mark.parametrize(
    ("import_policy", "carrier_policy", "message"),
    [
        (
            ANIMATION_IMPORT_POLICY,
            CARRIER_BAKE_POLICY,
            "Ordinary animation imports cannot request carrier baking",
        ),
        (
            ANIMATION_CARRIER_BAKE_IMPORT_POLICY,
            CARRIER_REMOVE_POLICY,
            "Carrier-bake imports require explicit bake policy",
        ),
    ],
)
def test_intake_requires_exact_carrier_policy_route_pairing(
    config, prompt, tmp_path, import_policy, carrier_policy, message
) -> None:
    _create_candidate(config, prompt)
    value = json.loads(_one_motion_request(tmp_path).read_text(encoding="utf-8"))
    value["import_policy"] = import_policy
    value["motions"][0]["carrier_orientation_policy"] = carrier_policy
    path = tmp_path / "mismatched-carrier-policy.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(FoundryError, match=message):
        intake_animation_library(config, ASSET_ID, path)


def test_carrier_bake_one_motion_normalizes_and_preserves_release_gates(
    config, prompt, tmp_path
) -> None:
    _create_candidate(config, prompt)
    _configure_fake_godot(config, tmp_path)
    intake_animation_library(config, ASSET_ID, _sleep_carrier_bake_request(tmp_path))

    execution = normalize_animation_library(config, ASSET_ID, runner=_fake_pipeline)

    report = json.loads(execution.technical_report.read_text(encoding="utf-8"))
    manifest = ManifestRepository(config.foundry.workspace_root).load(ASSET_ID)
    library = [
        item
        for item in manifest.artifacts
        if item.role == "processed_animation_library"
    ][-1]
    assert library.processor is not None
    assert library.processor.name == animation_service.PROCESSOR_NAME
    assert library.processor.version == animation_service.PROCESSOR_CARRIER_BAKE_VERSION
    assert report["import_policy"] == ANIMATION_CARRIER_BAKE_IMPORT_POLICY
    assert report["motions"][0]["carrier_orientation_policy"] == CARRIER_BAKE_POLICY
    assert report["motions"][0]["carrier_orientation_bake"] == _carrier_bake_fact()

    import_animation_visual_matrix(config, ASSET_ID, _visual_request(config, tmp_path))
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(ASSET_ID)
    bind_documented_test_custody(
        manifest, config.foundry.workspace_root / "assets" / ASSET_ID
    )
    manifest.revision += 1
    repository.save(manifest, expected_revision=manifest.revision - 1)

    approve_animation_library(config, ASSET_ID, "Independent reviewer")
    plan = plan_release(config, _lanes(), ASSET_ID)
    assert plan.descriptor["primary_payload"] == "animation_library"
    assert (
        plan.descriptor["animation_library"]["import_policy"]
        == ANIMATION_CARRIER_BAKE_IMPORT_POLICY
    )
    assert len(plan.descriptor["animation_library"]["selected_sources"]) == 1


@pytest.mark.parametrize(
    "mismatch",
    ["technical_check_policy", "processor_version", "technical_report_policy"],
)
def test_release_rejects_animation_policy_or_processor_mismatch(
    config, prompt, tmp_path, mismatch
) -> None:
    _create_candidate(config, prompt)
    _configure_fake_godot(config, tmp_path)
    intake_animation_library(config, ASSET_ID, _one_motion_request(tmp_path))
    normalize_animation_library(config, ASSET_ID, runner=_fake_pipeline)
    import_animation_visual_matrix(config, ASSET_ID, _visual_request(config, tmp_path))
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(ASSET_ID)
    bind_documented_test_custody(
        manifest, config.foundry.workspace_root / "assets" / ASSET_ID
    )
    manifest.revision += 1
    repository.save(manifest, expected_revision=manifest.revision - 1)
    approve_animation_library(config, ASSET_ID, "Independent reviewer")
    manifest = repository.load(ASSET_ID)
    checks = {item["name"]: item for item in manifest.validation.checks}
    library = next(
        item
        for item in manifest.artifacts
        if item.role == "processed_animation_library"
    )
    technical = next(
        item
        for item in manifest.artifacts
        if item.role == "animation_library_technical_report"
    )
    if mismatch == "technical_check_policy":
        checks["animation_library_technical_probe"]["import_policy"] = (
            ANIMATION_CARRIER_BAKE_IMPORT_POLICY
        )
    elif mismatch == "processor_version":
        assert library.processor is not None
        library.processor.version = animation_service.PROCESSOR_CARRIER_BAKE_VERSION
    elif mismatch == "technical_report_policy":
        report_path = (
            config.foundry.workspace_root / "assets" / ASSET_ID / technical.path
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["import_policy"] = ANIMATION_CARRIER_BAKE_IMPORT_POLICY
        report_path.write_text(json.dumps(report), encoding="utf-8")
        technical.sha256 = _sha(report_path.read_bytes())
        technical.size_bytes = report_path.stat().st_size
        manifest.approval.approved_artifact_hashes[
            "animation_library_technical_report"
        ] = technical.sha256
        checks["animation_library_technical_probe"]["report_sha256"] = technical.sha256
        checks["animation_library_visual_matrix"][
            "technical_report_sha256"
        ] = technical.sha256

    if mismatch == "technical_report_policy":
        with pytest.raises(FoundryError, match="import policy.*processor differ"):
            plan_release_service._animation_library_release_evidence(
                manifest,
                config.foundry.workspace_root / "assets" / ASSET_ID,
            )
    else:
        manifest.revision += 1
        repository.save(manifest, expected_revision=manifest.revision - 1)
        with pytest.raises(FoundryError, match="import policy.*processor differ"):
            plan_release(config, _lanes(), ASSET_ID)


@pytest.mark.parametrize(
    "mutation",
    [
        "carrier_nonunit",
        "post_quaternion",
        "root_changed",
        "carrier_key_count",
        "carrier_position_track",
        "interpolation_changed",
        "detached_carrier_fact",
        "track_index_collision",
        "reversed_noncommuting_rotation",
        "horizontal_handoff",
        "preservation_handoff",
    ],
)
def test_carrier_bake_rejects_nonexact_transform_evidence(
    config, prompt, tmp_path, mutation
) -> None:
    _create_candidate(config, prompt)
    _configure_fake_godot(config, tmp_path)
    intake_animation_library(config, ASSET_ID, _sleep_carrier_bake_request(tmp_path))

    def invalid_bake(config, sandbox: Path) -> AnimationPipelineExecution:
        execution = _fake_pipeline(config, sandbox)
        report = json.loads(execution.technical_report.read_text(encoding="utf-8"))
        bake = report["motions"][0]["carrier_orientation_bake"]
        if mutation == "carrier_nonunit":
            bake["carrier"]["quaternion"]["unit"] = False
        elif mutation == "post_quaternion":
            bake["hips_rotation_post"]["keys"][0]["quaternion"]["x"] = 0.0
        elif mutation == "root_changed":
            bake["hips_root_post"]["keys"][0]["y"] = 2.0
        elif mutation == "carrier_key_count":
            bake["carrier"]["key_count"] = 2
        elif mutation == "carrier_position_track":
            bake["carrier_position_track_count"] = 1
        elif mutation == "interpolation_changed":
            bake["hips_rotation_post"]["interpolation_type"] = 2
        elif mutation == "detached_carrier_fact":
            report["motions"][0]["known_carrier_tracks"][0]["track_index"] = 9
        elif mutation == "track_index_collision":
            bake["hips_root_pre"]["track_index"] = 2
            bake["hips_root_post"]["track_index"] = 2
        elif mutation == "reversed_noncommuting_rotation":
            bake["hips_rotation_post"]["keys"][0]["quaternion"]["z"] = -0.5
        elif mutation == "horizontal_handoff":
            for stage in ("pre", "post"):
                report["motions"][0][f"hips_horizontal_{stage}_transform"][
                    "initial_offset_x"
                ] = 0.5
        elif mutation == "preservation_handoff":
            for stage in ("pre", "post"):
                report["motions"][0][f"hips_preservation_{stage}_transform"][
                    "keys"
                ][0]["y"] = 0.2
        execution.technical_report.write_text(json.dumps(report), encoding="utf-8")
        return execution

    with pytest.raises(FoundryError, match="carrier-bake contract failed"):
        normalize_animation_library(config, ASSET_ID, runner=invalid_bake)


def test_visual_failure_is_preserved_and_blocks_approval(config, prompt, tmp_path) -> None:
    _create_candidate(config, prompt)
    _configure_fake_godot(config, tmp_path)
    intake_animation_library(config, ASSET_ID, _request(tmp_path))
    normalize_animation_library(config, ASSET_ID, runner=_fake_pipeline)
    report = import_animation_visual_matrix(
        config,
        ASSET_ID,
        _visual_request(config, tmp_path, failed=("StandDodge", "feral_apeman")),
    )
    value = json.loads(
        (config.foundry.workspace_root / "assets" / ASSET_ID / report.path).read_text()
    )
    assert value["passed"] is False
    assert next(
        cell
        for cell in value["cells"]
        if cell["semantic"] == "StandDodge" and cell["body_id"] == "feral_apeman"
    )["result"] == "FAIL"
    with pytest.raises(FoundryError, match="every recorded validation check"):
        approve_animation_library(config, ASSET_ID, "Reviewer")


def test_failed_monitor_is_rejected_without_partial_outputs(config, prompt, tmp_path) -> None:
    _create_candidate(config, prompt)
    _configure_fake_godot(config, tmp_path)
    intake_animation_library(config, ASSET_ID, _request(tmp_path))

    with pytest.raises(FoundryError, match="monitor evidence is incomplete or failed"):
        normalize_animation_library(config, ASSET_ID, runner=_fake_failed_monitor)

    asset_root = config.foundry.workspace_root / "assets" / ASSET_ID
    assert not (asset_root / "processed" / "animation_library.res").exists()
    assert not (asset_root / "reports" / "animation-library-technical-001.json").exists()
    assert ManifestRepository(config.foundry.workspace_root).load(ASSET_ID).workflow.state.value == (
        "downloaded"
    )
    operation_roots = list((asset_root / ".ops").iterdir())
    assert len(operation_roots) == 1
    assert (
        operation_roots[0]
        / "sandbox"
        / "output"
        / "animation-library-godot-monitor.json"
    ).is_file()


def test_finalize_script_builds_general_skeleton_paths_without_percent_formatting() -> None:
    script = (
        Path(animation_service.__file__).parent.parent
        / "godot"
        / "finalize_animation_library.gd"
    ).read_text(encoding="utf-8")

    assert animation_service.PROCESSOR_VERSION == "4"
    assert animation_service.PROCESSOR_CARRIER_BAKE_VERSION == "5"
    assert animation_service.HIPS_HORIZONTAL_POLICY in script
    assert '"%GeneralSkeleton:" + bone' in script
    assert '"%GeneralSkeleton:%s" % bone' not in script
    assert 'print("FOUNDRY_ANIMATION_TRACK_FACT " + JSON.stringify(fact))' in script
    assert "_bake_known_armature_carrier_into_hips(animation)" in script
    assert "else _strip_known_armature_carrier(animation)" in script
    assert "(carrier_quaternion * before_rotation).normalized()" in script
    assert "_rotation_bake_matches" in script
    assert '"rotation_composition_order": "carrier_times_hips"' in script
    assert '"position_transform": "carrier_rotate_hips_position"' in script
    assert "carrier_quaternion * before_position" in script
    assert "_position_bake_matches" in script
    assert "var finite: bool = value is Vector3" in script
    assert "var finite := value is Vector3" not in script
    assert "var rest_leaf_completion := _complete_optimized_rest_leaf_tracks(animation)" in script
    assert "var horizontal_transform := _hold_hips_horizontal_at_first_key(animation)" in script
    assert 'track_path == "Armature"' in script
    assert "animation.remove_track(int(matches[0].track_index))" in script
    assert 'fact["known_carrier_track_removed_count"] = carrier.removed_count' in script
    assert animation_service.REST_LEAF_COMPLETION_POLICY in script
    assert 'fact["optimized_rest_leaf_tracks_added"]' in script
    assert "Quaternion.IDENTITY" in script
    assert "REST_LEAF_BONES := [\"LeftHand\", \"RightHand\"]" in script
    assert '"unexpected_tracks": unexpected_tracks' in script
    assert '"non_finite_keys": non_finite_keys' in script
    assert "animation.track_set_key_value(" in script
    assert "Vector3(first_value.x, value.y, first_value.z)" in script
    assert "animation.track_get_key_time(track_index, key_index)" in script
    assert "animation.track_get_key_transition(track_index, key_index)" in script
    assert "animation.track_get_interpolation_type(track_index)" in script
    assert "animation.track_get_interpolation_loop_wrap(track_index)" in script
    assert "Vector2(value.x - first_value.x, value.z - first_value.z).length()" in script
    assert 'fact["hips_horizontal_pre_transform"]' in script
    assert 'fact["hips_horizontal_post_transform"]' in script

    loop_start = script.index('\tfor motion in request.get("motions", []):')
    failure_gate = script.index("\tif not failures.is_empty():", loop_start)
    loop_body = script[loop_start:failure_gate]
    technical_check = loop_body.index('if not bool(fact.get("passed", false)):')
    later_probe = loop_body.index('print("FOUNDRY_ANIMATION_TRACK_FACT "')
    assert later_probe < technical_check
    assert "\t\t\tcontinue" in loop_body[technical_check:]
    assert "_fail(" not in loop_body
    assert 'print("FOUNDRY_ANIMATION_FAILURE_SUMMARY "' in script[failure_gate:]

    isolation_script = (
        Path(animation_service.__file__).parent.parent
        / "godot"
        / "validate_isolated_animation_library.gd"
    ).read_text(encoding="utf-8")
    assert "var actual: Array[String] = []" in isolation_script
    assert "actual.append(actual_semantic)" in isolation_script
    assert "if actual != expected:" not in isolation_script
    assert "Array(library.get_animation_list())" not in isolation_script


def test_isolation_script_accepts_unsorted_exact_string_membership() -> None:
    script = (
        Path(animation_service.__file__).parent.parent
        / "godot"
        / "validate_isolated_animation_library.gd"
    ).read_text(encoding="utf-8")

    requested = ["SquatIdle", "KneelingFixing"]
    godot_canonical = ["KneelingFixing", "SquatIdle"]
    assert requested != godot_canonical
    assert sorted(requested) == sorted(godot_canonical)
    assert "var expected_semantic := str(motion.get(\"semantic\", \"\"))" in script
    assert "var actual_semantic := str(animation_name)" in script
    assert "var expected_sorted := expected.duplicate()" in script
    assert "var actual_sorted := actual.duplicate()" in script
    assert "expected_sorted.sort()" in script
    assert "actual_sorted.sort()" in script
    assert "if actual_sorted != expected_sorted:" in script
    assert '"selected_semantics": expected' in script


def test_isolation_script_rejects_missing_extra_and_duplicate_membership() -> None:
    script = (
        Path(animation_service.__file__).parent.parent
        / "godot"
        / "validate_isolated_animation_library.gd"
    ).read_text(encoding="utf-8")

    assert "var expected_seen: Dictionary = {}" in script
    assert "var actual_seen: Dictionary = {}" in script
    assert "expected_seen.has(expected_semantic)" in script
    assert "actual_seen.has(actual_semantic)" in script
    assert "empty or duplicate semantic" in script
    assert "if actual.size() != expected.size():" in script
    for actual in (
        ["SquatIdle"],
        ["KneelingFixing", "SquatIdle", "Unexpected"],
        ["KneelingFixing", "KneelingFixing"],
    ):
        assert actual != ["KneelingFixing", "SquatIdle"]


@pytest.mark.parametrize(
    ("raw_skeleton_path", "expected_key"),
    [
        ("Armature/Skeleton3D", "PATH:Armature/Skeleton3D"),
        ("target_character/Skeleton3D", "PATH:target_character/Skeleton3D"),
    ],
)
def test_configure_script_derives_exact_single_skeleton_import_key(
    raw_skeleton_path: str,
    expected_key: str,
) -> None:
    script = (
        Path(animation_service.__file__).parent.parent
        / "godot"
        / "configure_animation_library_imports.gd"
    ).read_text(encoding="utf-8")

    assert expected_key == "PATH:" + raw_skeleton_path
    assert 'return "PATH:" + str(relative_path)' in script
    assert "var relative_path := root.get_path_to(skeletons[0])" in script
    assert f'const SKELETON_KEY := "{expected_key}"' not in script
    assert "_configure(source_path + \".import\", bone_map, skeleton_key)" in script
    assert '{"nodes": {skeleton_key: {' in script


def test_configure_script_fails_closed_on_zero_or_multiple_skeletons() -> None:
    script = (
        Path(animation_service.__file__).parent.parent
        / "godot"
        / "configure_animation_library_imports.gd"
    ).read_text(encoding="utf-8")

    assert "var skeletons: Array[Skeleton3D] = []" in script
    assert "_collect_skeletons(root, skeletons)" in script
    assert "if skeletons.size() != 1:" in script
    assert "source must expose exactly one Skeleton3D; found %d" in script
    assert "if node is Skeleton3D:" in script
    assert "for child in node.get_children():" in script
    assert "_collect_skeletons(child, skeletons)" in script


@pytest.mark.parametrize(
    ("mutation", "value"),
    [
        ("post_delta", 0.001),
        ("preserved", False),
        ("post_nonfinite", float("nan")),
        ("initial_changed", 0.5),
        ("key_count_changed", 2),
        ("interpolation_changed", 2),
        ("policy", "stale_horizontal_policy"),
        ("report_policy", "stale_horizontal_policy"),
    ],
)
def test_normalization_rejects_invalid_hips_horizontal_transform_evidence(
    config, prompt, tmp_path, mutation, value
) -> None:
    _create_candidate(config, prompt)
    _configure_fake_godot(config, tmp_path)
    intake_animation_library(config, ASSET_ID, _request(tmp_path))

    def invalid_horizontal_evidence(config, sandbox: Path) -> AnimationPipelineExecution:
        execution = _fake_pipeline(config, sandbox)
        report = json.loads(execution.technical_report.read_text(encoding="utf-8"))
        motion = report["motions"][0]
        if mutation == "post_delta":
            motion["hips_horizontal_post_transform"]["max_delta_from_first"] = value
        elif mutation == "preserved":
            motion["hips_vertical_time_interpolation_preserved"] = value
        elif mutation == "post_nonfinite":
            motion["hips_horizontal_post_transform"]["span_x"] = value
        elif mutation == "initial_changed":
            motion["hips_horizontal_post_transform"]["initial_offset_x"] = value
        elif mutation == "key_count_changed":
            motion["hips_horizontal_post_transform"]["key_count"] = value
        elif mutation == "interpolation_changed":
            motion["hips_preservation_post_transform"]["track_interpolation_type"] = value
        elif mutation == "policy":
            motion["hips_horizontal_transform_policy"] = value
        elif mutation == "report_policy":
            report["horizontal_root_policy"] = value
        execution.technical_report.write_text(json.dumps(report), encoding="utf-8")
        return execution

    expected_message = (
        "failed or stale" if mutation == "report_policy" else "technical track contract failed"
    )
    with pytest.raises(FoundryError, match=expected_message):
        normalize_animation_library(config, ASSET_ID, runner=invalid_horizontal_evidence)


def test_normalization_rejects_missing_known_carrier_evidence(
    config, prompt, tmp_path
) -> None:
    _create_candidate(config, prompt)
    _configure_fake_godot(config, tmp_path)
    intake_animation_library(config, ASSET_ID, _request(tmp_path))

    def missing_carrier_evidence(config, sandbox: Path) -> AnimationPipelineExecution:
        execution = _fake_pipeline(config, sandbox)
        report = json.loads(execution.technical_report.read_text(encoding="utf-8"))
        for motion in report["motions"]:
            motion.pop("known_carrier_tracks")
            motion.pop("known_carrier_track_recognized_count")
            motion.pop("known_carrier_track_removed_count")
        execution.technical_report.write_text(json.dumps(report), encoding="utf-8")
        return execution

    with pytest.raises(FoundryError, match="technical track contract failed"):
        normalize_animation_library(config, ASSET_ID, runner=missing_carrier_evidence)


@pytest.mark.parametrize(
    "malformation",
    [
        "boolean_recognized",
        "unhashable_recognized",
        "duplicate_count",
        "wrong_path",
        "wrong_type",
        "missing_track_index",
        "boolean_track_index",
        "negative_track_index",
        "missing_key_count",
        "boolean_key_count",
        "negative_key_count",
    ],
)
def test_normalization_rejects_malformed_known_carrier_evidence(
    config, prompt, tmp_path, malformation
) -> None:
    _create_candidate(config, prompt)
    _configure_fake_godot(config, tmp_path)
    intake_animation_library(config, ASSET_ID, _request(tmp_path))

    def malformed_carrier_evidence(config, sandbox: Path) -> AnimationPipelineExecution:
        execution = _fake_pipeline(config, sandbox)
        report = json.loads(execution.technical_report.read_text(encoding="utf-8"))
        motion = report["motions"][0]
        track = motion["known_carrier_tracks"][0]
        if malformation == "boolean_recognized":
            motion["known_carrier_track_recognized_count"] = True
        elif malformation == "unhashable_recognized":
            motion["known_carrier_track_recognized_count"] = []
        elif malformation == "duplicate_count":
            motion["known_carrier_track_recognized_count"] = 2
            motion["known_carrier_track_removed_count"] = 2
            motion["known_carrier_tracks"].append(dict(track))
        elif malformation == "wrong_path":
            track["path"] = "Armature/Skeleton3D"
        elif malformation == "wrong_type":
            track["type"] = 1
        elif malformation == "missing_track_index":
            track.pop("track_index")
        elif malformation == "boolean_track_index":
            track["track_index"] = True
        elif malformation == "negative_track_index":
            track["track_index"] = -1
        elif malformation == "missing_key_count":
            track.pop("key_count")
        elif malformation == "boolean_key_count":
            track["key_count"] = False
        elif malformation == "negative_key_count":
            track["key_count"] = -1
        execution.technical_report.write_text(json.dumps(report), encoding="utf-8")
        return execution

    with pytest.raises(FoundryError, match="technical track contract failed"):
        normalize_animation_library(config, ASSET_ID, runner=malformed_carrier_evidence)


def test_normalization_accepts_explicit_zero_carrier_evidence(
    config, prompt, tmp_path
) -> None:
    _create_candidate(config, prompt)
    _configure_fake_godot(config, tmp_path)
    intake_animation_library(config, ASSET_ID, _request(tmp_path))

    def zero_carrier_evidence(config, sandbox: Path) -> AnimationPipelineExecution:
        execution = _fake_pipeline(config, sandbox)
        report = json.loads(execution.technical_report.read_text(encoding="utf-8"))
        for motion in report["motions"]:
            motion["known_carrier_track_recognized_count"] = 0
            motion["known_carrier_track_removed_count"] = 0
            motion["known_carrier_tracks"] = []
        execution.technical_report.write_text(json.dumps(report), encoding="utf-8")
        return execution

    execution = normalize_animation_library(config, ASSET_ID, runner=zero_carrier_evidence)
    assert execution.animation_library.is_file()


@pytest.mark.parametrize(
    "malformation",
    [
        "missing_policy",
        "wrong_policy",
        "wrong_bone",
        "wrong_path",
        "nonidentity",
        "duplicate_bone",
        "boolean_track_index",
        "bad_key_count",
        "bad_first_time",
        "bad_last_time",
        "duplicate_index",
        "false_completion",
        "nonidentity_value",
    ],
)
def test_normalization_rejects_malformed_rest_leaf_completion_evidence(
    config, prompt, tmp_path, malformation
) -> None:
    _create_candidate(config, prompt)
    _configure_fake_godot(config, tmp_path)
    intake_animation_library(config, ASSET_ID, _request(tmp_path))

    def malformed_rest_leaf(config, sandbox: Path) -> AnimationPipelineExecution:
        execution = _fake_pipeline(config, sandbox)
        report = json.loads(execution.technical_report.read_text(encoding="utf-8"))
        motion = report["motions"][0]
        track = {
            "bone": "LeftHand",
            "path": "%GeneralSkeleton:LeftHand",
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
        motion["optimized_rest_leaf_tracks_added"] = [track]
        if malformation == "missing_policy":
            motion.pop("optimized_rest_leaf_completion_policy")
        elif malformation == "wrong_policy":
            motion["optimized_rest_leaf_completion_policy"] = "weakened"
        elif malformation == "wrong_bone":
            track["bone"] = "Head"
        elif malformation == "wrong_path":
            track["path"] = "%GeneralSkeleton:RightHand"
        elif malformation == "nonidentity":
            track["keys"][0]["identity_rotation"] = False
        elif malformation == "duplicate_bone":
            motion["optimized_rest_leaf_tracks_added"].append(dict(track))
        elif malformation == "boolean_track_index":
            track["track_index"] = True
        elif malformation == "bad_key_count":
            track["key_count"] = 3
        elif malformation == "bad_first_time":
            track["keys"][0]["time"] = 0.1
        elif malformation == "bad_last_time":
            track["keys"][1]["time"] = 0.5
        elif malformation == "duplicate_index":
            duplicate = json.loads(json.dumps(track))
            duplicate["bone"] = "RightHand"
            duplicate["path"] = "%GeneralSkeleton:RightHand"
            motion["optimized_rest_leaf_tracks_added"].append(duplicate)
        elif malformation == "false_completion":
            motion["optimized_rest_leaf_completion_passed"] = False
        elif malformation == "nonidentity_value":
            track["keys"][0]["value_x"] = 0.1
        execution.technical_report.write_text(json.dumps(report), encoding="utf-8")
        return execution

    with pytest.raises(FoundryError, match="technical track contract failed"):
        normalize_animation_library(config, ASSET_ID, runner=malformed_rest_leaf)


def test_normalization_accepts_exact_identity_hand_rest_completion(
    config, prompt, tmp_path
) -> None:
    _create_candidate(config, prompt)
    _configure_fake_godot(config, tmp_path)
    intake_animation_library(config, ASSET_ID, _request(tmp_path))

    def exact_rest_leaf(config, sandbox: Path) -> AnimationPipelineExecution:
        execution = _fake_pipeline(config, sandbox)
        report = json.loads(execution.technical_report.read_text(encoding="utf-8"))
        report["motions"][0]["optimized_rest_leaf_tracks_added"] = [
            {
                "bone": bone,
                "path": f"%GeneralSkeleton:{bone}",
                "track_index": 21 + index,
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
            for index, bone in enumerate(("LeftHand", "RightHand"))
        ]
        execution.technical_report.write_text(json.dumps(report), encoding="utf-8")
        return execution

    execution = normalize_animation_library(config, ASSET_ID, runner=exact_rest_leaf)
    assert execution.animation_library.is_file()


def test_primary_operation_failure_retains_staging_and_restores_context(
    tmp_path, monkeypatch
) -> None:
    prior_roots = animation_service._ACTIVE_OPERATION_ROOTS.get()
    cleanup_called = False

    @animation_service._transactional_operation
    def fail_after_staging() -> None:
        animation_service._new_operation_root(tmp_path, "cleanup-regression")
        raise FoundryError("primary operation failure")

    def fail_cleanup(_root: Path) -> None:
        nonlocal cleanup_called
        cleanup_called = True
        raise OSError("seeded cleanup failure")

    monkeypatch.setattr(animation_service, "_remove_operation_root", fail_cleanup)

    with pytest.raises(FoundryError, match="primary operation failure"):
        fail_after_staging()
    assert cleanup_called is False
    assert len(list((tmp_path / ".ops").iterdir())) == 1
    assert animation_service._ACTIVE_OPERATION_ROOTS.get() == prior_roots


def test_cleanup_failure_after_success_remains_actionable(tmp_path, monkeypatch) -> None:
    prior_roots = animation_service._ACTIVE_OPERATION_ROOTS.get()

    @animation_service._transactional_operation
    def succeed_after_staging() -> str:
        animation_service._new_operation_root(tmp_path, "cleanup-regression")
        return "complete"

    def fail_cleanup(_root: Path) -> None:
        raise OSError("seeded cleanup failure")

    monkeypatch.setattr(animation_service, "_remove_operation_root", fail_cleanup)

    with pytest.raises(OSError, match="seeded cleanup failure"):
        succeed_after_staging()
    assert animation_service._ACTIVE_OPERATION_ROOTS.get() == prior_roots


def test_visual_import_failure_retains_staging_and_preserves_review(
    config, prompt, tmp_path
) -> None:
    _create_candidate(config, prompt)
    _configure_fake_godot(config, tmp_path)
    intake_animation_library(config, ASSET_ID, _request(tmp_path))
    normalize_animation_library(config, ASSET_ID, runner=_fake_pipeline)
    request = _visual_request(config, tmp_path)
    value = json.loads(request.read_text(encoding="utf-8"))
    value["cells"][-1]["evidence"][0]["sha256"] = "0" * 64
    request.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(FoundryError, match="Visual evidence bytes do not match"):
        import_animation_visual_matrix(config, ASSET_ID, request)

    asset_root = config.foundry.workspace_root / "assets" / ASSET_ID
    assert not (asset_root / "reports" / "animation-visual-matrix-001.json").exists()
    assert not (asset_root / "reports" / "animation-visual-evidence").exists()
    assert len(list((asset_root / ".ops").iterdir())) == 1


def test_repeated_visual_evidence_bytes_across_cells_are_rejected(
    config, prompt, tmp_path
) -> None:
    _create_candidate(config, prompt)
    _configure_fake_godot(config, tmp_path)
    intake_animation_library(config, ASSET_ID, _request(tmp_path))
    normalize_animation_library(config, ASSET_ID, runner=_fake_pipeline)
    request = _visual_request(config, tmp_path)
    value = json.loads(request.read_text(encoding="utf-8"))
    value["cells"][-1]["evidence"] = value["cells"][0]["evidence"]
    request.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(FoundryError, match="unique across semantic/body cells"):
        import_animation_visual_matrix(config, ASSET_ID, request)

    asset_root = config.foundry.workspace_root / "assets" / ASSET_ID
    assert not (asset_root / "reports" / "animation-visual-matrix-001.json").exists()


def test_post_replace_event_failure_reconciles_and_keeps_exact_outputs(
    config, prompt, tmp_path, monkeypatch
) -> None:
    _create_candidate(config, prompt)
    _configure_fake_godot(config, tmp_path)
    intake_animation_library(config, ASSET_ID, _request(tmp_path))

    def fail_event_append(_path, _value) -> None:
        raise OSError("seeded post-replace event failure")

    monkeypatch.setattr(manifest_storage, "append_event_bytes", fail_event_append)
    execution = normalize_animation_library(config, ASSET_ID, runner=_fake_pipeline)

    repository = ManifestRepository(config.foundry.workspace_root)
    live = repository.load(ASSET_ID)
    assert live.workflow.state.value == "review"
    assert repository.diagnose_pending_save(ASSET_ID).status == "complete"
    for path in (
        execution.animation_library,
        execution.technical_report,
        execution.isolation_report,
        execution.monitor_report,
    ):
        assert path.is_file()
    _assert_no_active_operations(config)


def test_passing_exact_matrix_approves_and_plans_model_free_release(
    config, prompt, tmp_path
) -> None:
    _create_candidate(config, prompt)
    _configure_fake_godot(config, tmp_path)
    intake_animation_library(config, ASSET_ID, _request(tmp_path))
    normalize_animation_library(config, ASSET_ID, runner=_fake_pipeline)
    import_animation_visual_matrix(config, ASSET_ID, _visual_request(config, tmp_path))
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(ASSET_ID)
    bind_documented_test_custody(
        manifest, config.foundry.workspace_root / "assets" / ASSET_ID
    )
    manifest.revision += 1
    repository.save(manifest, expected_revision=manifest.revision - 1)

    approved = approve_animation_library(config, ASSET_ID, "Independent reviewer")
    assert set(approved.approval.approved_artifact_hashes) == {
        "processed_animation_library",
        "animation_library_technical_report",
        "animation_library_godot_monitor_report",
        "animation_library_isolation_report",
        "animation_library_visual_matrix_report",
        *(f"artifact:animation_visual_evidence_{index:04d}" for index in range(1, 7)),
    }
    plan = plan_release(config, _lanes(), ASSET_ID)
    assert plan.descriptor["primary_payload"] == "animation_library"
    assert all(item["role"] != "model" for item in plan.descriptor["files"])
    assert plan.descriptor["animation_library"]["selected_sources"][0]["semantic"] == "AngryStomp"


def test_one_motion_library_preserves_visual_approval_and_release_gates(
    config, prompt, tmp_path
) -> None:
    _create_candidate(config, prompt)
    _configure_fake_godot(config, tmp_path)
    intake_animation_library(config, ASSET_ID, _one_motion_request(tmp_path))
    normalize_animation_library(config, ASSET_ID, runner=_fake_pipeline)
    import_animation_visual_matrix(config, ASSET_ID, _visual_request(config, tmp_path))
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(ASSET_ID)
    bind_documented_test_custody(
        manifest, config.foundry.workspace_root / "assets" / ASSET_ID
    )
    manifest.revision += 1
    repository.save(manifest, expected_revision=manifest.revision - 1)

    approved = approve_animation_library(config, ASSET_ID, "Independent reviewer")
    assert set(approved.approval.approved_artifact_hashes) == {
        "processed_animation_library",
        "animation_library_technical_report",
        "animation_library_godot_monitor_report",
        "animation_library_isolation_report",
        "animation_library_visual_matrix_report",
        *(f"artifact:animation_visual_evidence_{index:04d}" for index in range(1, 4)),
    }
    plan = plan_release(config, _lanes(), ASSET_ID)
    assert plan.descriptor["primary_payload"] == "animation_library"
    assert len(plan.descriptor["animation_library"]["selected_sources"]) == 1
    assert plan.descriptor["animation_library"]["selected_sources"][0] == {
        "semantic": "AngryStomp",
        "source_sha256": _sha(b"first exact fbx"),
        "source_size_bytes": len(b"first exact fbx"),
    }
    assert len(
        [
            item
            for item in plan.descriptor["files"]
            if item["role"] == "animation_visual_evidence"
        ]
    ) == 3
