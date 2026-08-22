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
    bodies = []
    for body_id in ("female_average", "male_average", "feral_apeman"):
        payload = f"exact-body:{body_id}".encode()
        path = tmp_path / f"{body_id}.fbx"
        path.write_bytes(payload)
        bodies.append(
            {
                "body_id": body_id,
                "path": path.name,
                "sha256": _sha(payload),
                "size_bytes": len(payload),
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
            "animation_library_sha256": runtime["animation_library_sha256"],
            "technical_report_sha256": runtime["technical_report_sha256"],
            "selected_semantics": runtime["selected_semantics"],
            "bodies": [
                {
                    "body_id": body["body_id"],
                    "payload_sha256": body["payload_sha256"],
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
        "sandbox/bodies/female_average.fbx",
        "sandbox/bodies/male_average.fbx",
        "sandbox/bodies/feral_apeman.fbx",
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
