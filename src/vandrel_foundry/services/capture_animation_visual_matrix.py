"""Produce unsigned, exact three-body animation visual-capture evidence."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.animation_library import FIXED_PHASES
from vandrel_foundry.domain.animation_visual_capture import (
    CAMERA_POLICY,
    HORIZONTAL_ROOT_MOTION_TOLERANCE,
    AnimationVisualCaptureManifest,
    AnimationVisualCaptureRequest,
)
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.storage.atomic import json_bytes

CAPTURE_REPORT_SCHEMA = "vandrel_foundry_animation_visual_capture_result/1.0"
ENTRY_SENTINEL_BYTES = b'{"entrypoint":"_initialize","schema_version":"vandrel_foundry_animation_visual_capture_entry/1.0"}\n'
ENTRY_SENTINEL_SHA256 = hashlib.sha256(ENTRY_SENTINEL_BYTES).hexdigest()
MONITOR_SCHEMA = "vandrel_foundry_animation_visual_capture_monitor/1.0"
MONITOR_POLICY = "vandrel_monitored_godot_animation_visual_capture_corridor_2026-08-21"
CAMERA_CONFIG = {
    "schema_version": "vandrel_fixed_animation_review_camera/1.0",
    "phase_view_size": [1280, 720],
    "contact_sheet_grid": [4, 2],
    "position": [0.0, 0.28, 5.4],
    "target": [0.0, 0.95, 0.0],
    "up": [0.0, 1.0, 0.0],
    "fov_degrees": 38.0,
    "camera_follow_enabled": False,
    "per_phase_reframing": False,
    "body_origin": [0.0, 0.0, 0.0],
    "fixed_phases": list(FIXED_PHASES),
}
CAMERA_CONFIG_SHA256 = hashlib.sha256(json_bytes(CAMERA_CONFIG)).hexdigest()
RAW_OUTER_TEMP_NAMES = {
    ".foundry-capture-outer-stdout.tmp",
    ".foundry-capture-outer-stderr.tmp",
}
TRANSIENT_FAILURE_DIRECTORY_NAMES = {".godot"}


@dataclass(frozen=True)
class AnimationVisualCaptureExecution:
    capture_report: Path
    monitor_report: Path
    evidence_directory: Path


@dataclass(frozen=True)
class AnimationVisualCapturePackage:
    output_directory: Path
    manifest: Path
    review_template: Path
    capture_report: Path
    monitor_report: Path


CaptureRunner = Callable[
    [FoundryConfig, Path, str, str],
    AnimationVisualCaptureExecution,
]


def capture_animation_visual_matrix(
    config: FoundryConfig,
    request_path: Path,
    output_directory: Path,
    runner: CaptureRunner | None = None,
) -> AnimationVisualCapturePackage:
    """Capture evidence without mutating a candidate or asserting anatomy PASS."""
    request = _load_request(request_path)
    if request.camera_policy != CAMERA_POLICY:
        raise FoundryError("Visual capture camera policy is not the accepted fixed policy.")
    if request.camera_config_sha256 != CAMERA_CONFIG_SHA256:
        raise FoundryError("Visual capture camera configuration hash is not canonical.")
    library = _resolve_exact_input(
        request_path, request.animation_library, {".res"}, "animation library"
    )
    technical_path = _resolve_exact_input(
        request_path, request.technical_report, {".json"}, "technical report"
    )
    bodies = [
        (
            body,
            _resolve_exact_input(request_path, body, {".fbx"}, body.body_id),
            _resolve_exact_input(
                request_path,
                body.import_sidecar,
                {".import"},
                f"{body.body_id} import sidecar",
            ),
            _resolve_exact_input(
                request_path,
                body.bone_map,
                {".tres"},
                f"{body.body_id} BoneMap",
            ),
        )
        for body in request.bodies
    ]
    for body, _source, sidecar, _bone_map in bodies:
        _validate_body_import_sidecar(body, sidecar)
    technical = _load_json(technical_path, "animation technical report")
    semantics = _validate_technical_report(
        technical,
        request.animation_library.sha256,
        request.animation_library.size_bytes,
    )
    output_directory = output_directory.resolve()
    if output_directory.exists():
        raise FoundryError("Visual capture output destination already exists.")
    if not output_directory.parent.is_dir():
        raise FoundryError("Visual capture output parent does not exist.")
    failure_directory = output_directory.with_name(f"{output_directory.name}.failed")
    if failure_directory.exists():
        raise FoundryError(
            f"Prior visual capture failure evidence requires disposition: {failure_directory}"
        )

    operation_root = Path(
        tempfile.mkdtemp(prefix=f".{output_directory.name}-", dir=output_directory.parent)
    )
    succeeded = False
    try:
        sandbox = operation_root / "sandbox"
        runtime_sha = _stage_sandbox(
            sandbox,
            request,
            library,
            technical_path,
            bodies,
            semantics,
        )
        if runner is None:
            from vandrel_foundry.services.run_animation_visual_capture import (
                run_monitored_animation_visual_capture,
            )

            runner = run_monitored_animation_visual_capture
        capture_script_sha = _hash_file(sandbox / "capture_animation_visual_matrix.gd")[0]
        execution = runner(config, sandbox, runtime_sha, capture_script_sha)
        _require_entry_sentinel(sandbox)
        capture_report_path = _require_sandbox_output(
            execution.capture_report, sandbox, "capture report"
        )
        monitor_report_path = _require_sandbox_output(
            execution.monitor_report, sandbox, "monitor report"
        )
        evidence_directory = execution.evidence_directory.resolve()
        if evidence_directory != (sandbox / "output" / "cells").resolve():
            raise FoundryError("Visual capture evidence directory is outside its sandbox.")
        capture_report = _load_json(capture_report_path, "visual capture report")
        cells = _validate_capture_report(
            capture_report,
            request,
            semantics,
            evidence_directory,
        )
        monitor = _load_json(monitor_report_path, "visual capture monitor report")
        _validate_monitor_report(config, monitor, runtime_sha, capture_script_sha)
        _verify_exact_inputs(
            request_path,
            request,
            library,
            technical_path,
            bodies,
        )

        package = operation_root / "package"
        package.mkdir()
        (package / "cells").mkdir()
        packaged_cells: list[dict[str, object]] = []
        for cell in cells:
            source = evidence_directory / Path(str(cell["evidence"]["path"])).name
            destination = package / "cells" / source.name
            _copy_new(source, destination)
            digest, size = _hash_file(destination)
            if digest != cell["evidence"]["sha256"] or size != cell["evidence"]["size_bytes"]:
                raise FoundryError("Visual capture evidence changed during packaging.")
            packaged_cells.append(
                {
                    **cell,
                    "evidence": {
                        "path": f"cells/{source.name}",
                        "sha256": digest,
                        "size_bytes": size,
                    },
                }
            )
        capture_report_destination = package / "capture-report.json"
        monitor_destination = package / "godot-monitor.json"
        _copy_new(capture_report_path, capture_report_destination)
        _copy_new(monitor_report_path, monitor_destination)
        capture_report_sha = _hash_file(capture_report_destination)[0]
        monitor_report_sha = _hash_file(monitor_destination)[0]
        body_bindings = [
            {"body_id": body.body_id, "payload_sha256": body.sha256}
            for body, _path, _sidecar, _bone_map in bodies
        ]
        manifest_value = {
            "schema_version": "vandrel_foundry_animation_visual_capture_manifest/1.0",
            "target_import_schema_version": "vandrel_foundry_animation_visual_matrix/1.0",
            "asset_id": request.asset_id,
            "animation_library_sha256": request.animation_library.sha256,
            "technical_report_sha256": request.technical_report.sha256,
            "selected_semantics": semantics,
            "bodies": body_bindings,
            "camera_policy": CAMERA_POLICY,
            "camera_config_sha256": CAMERA_CONFIG_SHA256,
            "observed_phases": list(FIXED_PHASES),
            "cells": packaged_cells,
            "capture_report_path": "capture-report.json",
            "capture_report_sha256": capture_report_sha,
            "monitor_report_path": "godot-monitor.json",
            "monitor_report_sha256": monitor_report_sha,
            "review_status": "manual_review_required",
            "anatomy_acceptance": "not_assessed",
            "reviewer": None,
            "reviewed_at": None,
        }
        try:
            validated_manifest = AnimationVisualCaptureManifest.model_validate(
                manifest_value
            )
        except ValidationError as exc:
            raise FoundryError(f"Visual capture manifest is invalid: {exc}") from exc
        manifest_path = package / "capture-manifest.json"
        _write_new(manifest_path, json_bytes(validated_manifest.model_dump(mode="json")))
        review_template = package / "animation-visual-matrix-review-template.json"
        _write_new(
            review_template,
            json_bytes(
                _review_template(
                    validated_manifest.model_dump(mode="json"),
                )
            ),
        )
        os.rename(package, output_directory)
        succeeded = True
        return AnimationVisualCapturePackage(
            output_directory=output_directory,
            manifest=output_directory / manifest_path.name,
            review_template=output_directory / review_template.name,
            capture_report=output_directory / capture_report_destination.name,
            monitor_report=output_directory / monitor_destination.name,
        )
    except Exception as exc:
        if operation_root.is_dir() and not output_directory.exists():
            residual_raw = [
                path
                for path in operation_root.rglob("*")
                if path.name in RAW_OUTER_TEMP_NAMES
            ]
            if residual_raw:
                try:
                    retention_issue = _retain_filtered_failure(
                        operation_root,
                        failure_directory,
                    )
                except OSError as retention_error:
                    raise FoundryError(
                        "Visual capture failed and bounded failure evidence could not be "
                        f"retained; residual operation root {operation_root}: "
                        f"{retention_error}"
                    ) from exc
                suffix = (
                    f" Filtered-retention cleanup issue: {retention_issue}"
                    if retention_issue is not None
                    else ""
                )
                raise FoundryError(
                    f"{exc} Bounded failure evidence retained at {failure_directory}. "
                    "Persistent raw-temp cleanup failure prevented whole-root promotion. "
                    f"Residual raw operation root: {operation_root}.{suffix}"
                ) from exc
            try:
                os.rename(operation_root, failure_directory)
            except OSError as retention_error:
                raise FoundryError(
                    "Visual capture failed and its evidence could not be moved; "
                    f"inspect operation root {operation_root}: {retention_error}"
                ) from exc
            raise FoundryError(
                f"{exc} Failure evidence retained at {failure_directory}"
            ) from exc
        raise
    finally:
        if succeeded and operation_root.is_dir():
            shutil.rmtree(operation_root)


def _load_request(path: Path) -> AnimationVisualCaptureRequest:
    try:
        return AnimationVisualCaptureRequest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValidationError) as exc:
        raise FoundryError(f"Animation visual capture request is invalid: {exc}") from exc


def _resolve_exact_input(request_path: Path, item, suffixes: set[str], label: str) -> Path:
    path = Path(item.path)
    if not path.is_absolute():
        path = request_path.resolve().parent / path
    path = path.resolve()
    if path.suffix.casefold() not in suffixes or not path.is_file():
        raise FoundryError(f"Visual capture {label} input is missing or unsupported.")
    if _hash_file(path) != (item.sha256, item.size_bytes):
        raise FoundryError(f"Visual capture {label} bytes do not match the request.")
    return path


def _validate_technical_report(report: object, library_sha: str, library_size: int) -> list[str]:
    if (
        not isinstance(report, dict)
        or report.get("schema_version")
        != "vandrel_foundry_animation_library_technical/1.0"
        or report.get("animation_library_sha256") != library_sha
        or report.get("animation_library_size_bytes") != library_size
        or report.get("passed") is not True
    ):
        raise FoundryError("Visual capture technical report is failed or bound elsewhere.")
    motions = report.get("motions")
    if not isinstance(motions, list) or not motions:
        raise FoundryError("Visual capture technical report has no exact motion membership.")
    semantics = [item.get("semantic") for item in motions if isinstance(item, dict)]
    if (
        len(semantics) != len(motions)
        or len(set(semantics)) != len(semantics)
        or any(
            not isinstance(item, str)
            or re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", item) is None
            for item in semantics
        )
        or any(
            item.get("passed") is not True
            or item.get("output_library_sha256") != library_sha
            or item.get("hips_position_track_count") != 1
            or item.get("mapped_rotation_track_count") != 22
            or item.get("scale_track_count") != 0
            or item.get("non_hips_position_track_count") != 0
            or item.get("other_track_count") != 0
            or item.get("finite_keys") is not True
            for item in motions
        )
    ):
        raise FoundryError("Visual capture technical motion membership is stale or failed.")
    return semantics


def _stage_sandbox(
    sandbox: Path,
    request: AnimationVisualCaptureRequest,
    library: Path,
    technical_report: Path,
    bodies,
    semantics: list[str],
) -> str:
    sandbox.mkdir()
    (sandbox / "library").mkdir()
    (sandbox / "bodies").mkdir()
    (sandbox / "output").mkdir()
    _copy_new(library, sandbox / "library" / "animation_library.res")
    _copy_new(technical_report, sandbox / "library" / "technical-report.json")
    runtime_bodies = []
    for body, source, sidecar, bone_map in bodies:
        destination = _sandbox_resource_path(sandbox, body.resource_path)
        sidecar_destination = _sandbox_resource_path(
            sandbox, body.import_sidecar.resource_path
        )
        bone_map_destination = _sandbox_resource_path(
            sandbox, body.bone_map.resource_path
        )
        _copy_or_verify_exact(source, destination)
        _copy_or_verify_exact(sidecar, sidecar_destination)
        _copy_or_verify_exact(bone_map, bone_map_destination)
        staged_payload_sha, staged_payload_size = _hash_file(destination)
        staged_sidecar_sha, staged_sidecar_size = _hash_file(sidecar_destination)
        staged_bone_map_sha, staged_bone_map_size = _hash_file(bone_map_destination)
        runtime_bodies.append(
            {
                "body_id": body.body_id,
                "path": body.resource_path,
                "payload_sha256": body.sha256,
                "size_bytes": body.size_bytes,
                "staging_policy": "accepted_exact_unchanged_godot_body_import_v1",
                "staged_payload_sha256": staged_payload_sha,
                "staged_payload_size_bytes": staged_payload_size,
                "import_sidecar_resource_path": body.import_sidecar.resource_path,
                "import_sidecar_sha256": body.import_sidecar.sha256,
                "import_sidecar_size_bytes": body.import_sidecar.size_bytes,
                "staged_import_sidecar_sha256": staged_sidecar_sha,
                "staged_import_sidecar_size_bytes": staged_sidecar_size,
                "bone_map_resource_path": body.bone_map.resource_path,
                "bone_map_sha256": body.bone_map.sha256,
                "bone_map_size_bytes": body.bone_map.size_bytes,
                "staged_bone_map_sha256": staged_bone_map_sha,
                "staged_bone_map_size_bytes": staged_bone_map_size,
            }
        )
    script = (
        Path(__file__).resolve().parent.parent
        / "godot"
        / "capture_animation_visual_matrix.gd"
    )
    _copy_new(script, sandbox / script.name)
    runtime = {
        "schema_version": "vandrel_foundry_animation_visual_capture_runtime/1.0",
        "asset_id": request.asset_id,
        "animation_library_path": "res://library/animation_library.res",
        "animation_library_sha256": request.animation_library.sha256,
        "animation_library_size_bytes": request.animation_library.size_bytes,
        "technical_report_path": "res://library/technical-report.json",
        "technical_report_sha256": request.technical_report.sha256,
        "selected_semantics": semantics,
        "bodies": runtime_bodies,
        "camera_policy": CAMERA_POLICY,
        "camera_config": CAMERA_CONFIG,
        "camera_config_sha256": CAMERA_CONFIG_SHA256,
        "horizontal_root_motion_tolerance": HORIZONTAL_ROOT_MOTION_TOLERANCE,
        "anatomy_acceptance": "not_assessed",
    }
    runtime_path = sandbox / "animation-visual-runtime.json"
    _write_new(runtime_path, json_bytes(runtime))
    _write_new(
        sandbox / "project.godot",
        b'[application]\nconfig/name="Foundry Animation Visual Capture"\n[rendering]\nrenderer/rendering_method="gl_compatibility"\nrenderer/rendering_method.mobile="gl_compatibility"\n',
    )
    return _hash_file(runtime_path)[0]


def _validate_capture_report(
    report: object,
    request: AnimationVisualCaptureRequest,
    semantics: list[str],
    evidence_directory: Path,
) -> list[dict[str, object]]:
    expected_bodies = [
        {
            "body_id": body.body_id,
            "payload_sha256": body.sha256,
            "payload_size_bytes": body.size_bytes,
            "staged_payload_sha256": body.sha256,
            "staged_payload_size_bytes": body.size_bytes,
            "resource_path": body.resource_path,
            "staging_policy": "accepted_exact_unchanged_godot_body_import_v1",
            "import_sidecar_resource_path": body.import_sidecar.resource_path,
            "import_sidecar_sha256": body.import_sidecar.sha256,
            "import_sidecar_size_bytes": body.import_sidecar.size_bytes,
            "staged_import_sidecar_sha256": body.import_sidecar.sha256,
            "staged_import_sidecar_size_bytes": body.import_sidecar.size_bytes,
            "bone_map_resource_path": body.bone_map.resource_path,
            "bone_map_sha256": body.bone_map.sha256,
            "bone_map_size_bytes": body.bone_map.size_bytes,
            "staged_bone_map_sha256": body.bone_map.sha256,
            "staged_bone_map_size_bytes": body.bone_map.size_bytes,
        }
        for body in request.bodies
    ]
    if (
        not isinstance(report, dict)
        or report.get("schema_version") != CAPTURE_REPORT_SCHEMA
        or report.get("entry_sentinel_sha256") != ENTRY_SENTINEL_SHA256
        or report.get("animation_library_sha256") != request.animation_library.sha256
        or report.get("technical_report_sha256") != request.technical_report.sha256
        or report.get("selected_semantics") != semantics
        or report.get("bodies") != expected_bodies
        or report.get("camera_policy") != CAMERA_POLICY
        or report.get("camera_config_sha256") != CAMERA_CONFIG_SHA256
        or report.get("observed_phases") != list(FIXED_PHASES)
        or report.get("camera_follow_enabled") is not False
        or report.get("per_phase_reframing") is not False
        or report.get("anatomy_acceptance") != "not_assessed"
        or report.get("capture_passed") is not True
    ):
        raise FoundryError("Visual capture report is failed, stale, or policy-incomplete.")
    cells = report.get("cells")
    expected_keys = {
        (semantic, body.body_id) for semantic in semantics for body in request.bodies
    }
    if not isinstance(cells, list) or {
        (item.get("semantic"), item.get("body_id"))
        for item in cells
        if isinstance(item, dict)
    } != expected_keys or len(cells) != len(expected_keys):
        raise FoundryError("Visual capture report does not contain the exact cell grid.")
    evidence_hashes: list[str] = []
    for cell in cells:
        try:
            motion_facts = [
                float(cell.get("horizontal_root_motion_span_x", 1.0)),
                float(cell.get("horizontal_root_motion_span_z", 1.0)),
                float(cell.get("horizontal_root_motion_initial_offset_x", float("nan"))),
                float(cell.get("horizontal_root_motion_initial_offset_z", float("nan"))),
                float(cell.get("horizontal_root_motion_max_delta_from_first", 1.0)),
            ]
        except (AttributeError, TypeError, ValueError):
            motion_facts = [float("nan")]
        if (
            not isinstance(cell, dict)
            or cell.get("observed_phases") != list(FIXED_PHASES)
            or cell.get("camera_follow_enabled") is not False
            or cell.get("per_phase_reframing") is not False
            or not all(math.isfinite(value) for value in motion_facts)
            or max(motion_facts[0], motion_facts[1], motion_facts[4])
            > HORIZONTAL_ROOT_MOTION_TOLERANCE
        ):
            raise FoundryError("Visual capture cell violates fixed-phase/root-motion policy.")
        evidence = cell.get("evidence")
        if not isinstance(evidence, dict):
            raise FoundryError("Visual capture cell has no evidence binding.")
        relative = str(evidence.get("path", ""))
        path = evidence_directory / Path(relative).name
        digest, size = _hash_file(path)
        if (
            relative != f"cells/{path.name}"
            or digest != evidence.get("sha256")
            or size != evidence.get("size_bytes")
        ):
            raise FoundryError("Visual capture cell evidence bytes are stale.")
        evidence_hashes.append(digest)
    if len(evidence_hashes) != len(set(evidence_hashes)):
        raise FoundryError("Visual capture evidence is not unique per semantic/body cell.")
    return cells


def _validate_monitor_report(
    config: FoundryConfig,
    report: object,
    runtime_sha: str,
    capture_script_sha: str,
) -> None:
    executable = config.tools.godot_executable
    if executable is None:
        raise FoundryError("Visual capture Godot console identity is unavailable.")
    supervisor = (
        Path(__file__).resolve().parent.parent
        / "godot"
        / "Invoke-FoundryAnimationVisualCaptureMonitored.ps1"
    )
    phases = ["import", "capture"]
    phase_results = report.get("phase_results") if isinstance(report, dict) else None
    expected_keys = {
        "schema_version",
        "policy",
        "run_started_utc",
        "run_ended_utc",
        "console_executable_name",
        "console_file_version",
        "godot_console_sha256",
        "supervisor_sha256",
        "runtime_request_sha256",
        "capture_script_sha256",
        "camera_config_sha256",
        "preflights",
        "process_zero_preflight",
        "child_environment",
        "phases",
        "phase_results",
        "outer_timeout_seconds_per_phase",
        "internal_iteration_bomb",
        "post_exit_poll_seconds",
        "timed_out",
        "output_limited",
        "cleanup_failed",
        "cleanup_issue",
        "application_error_windows",
        "application_events",
        "wer_and_dump_paths",
        "final_godot_processes",
        "has_crash_evidence",
        "passed",
        "failure_stage",
        "failure_message",
    }
    phase_keys = {
        "phase",
        "process_zero_preflight",
        "post_exit_poll_seconds",
        "started_utc",
        "ended_utc",
        "exit_code",
        "stdout_path",
        "stderr_path",
        "godot_log_path",
    }
    if (
        not isinstance(report, dict)
        or set(report) != expected_keys
        or report.get("schema_version") != MONITOR_SCHEMA
        or report.get("policy") != MONITOR_POLICY
        or report.get("runtime_request_sha256") != runtime_sha
        or report.get("capture_script_sha256") != capture_script_sha
        or report.get("camera_config_sha256") != CAMERA_CONFIG_SHA256
        or report.get("preflights")
        != {
            "sandbox": True,
            "runtime_request": True,
            "capture_script": True,
            "camera_config": True,
            "godot_console": True,
            "initial_process_zero": True,
        }
        or report.get("godot_console_sha256") != _hash_file(executable)[0]
        or report.get("supervisor_sha256") != _hash_file(supervisor)[0]
        or report.get("process_zero_preflight") is not True
        or not isinstance(report.get("run_started_utc"), str)
        or not isinstance(report.get("run_ended_utc"), str)
        or not str(report.get("console_executable_name", "")).casefold().endswith(
            "console.exe"
        )
        or not isinstance(report.get("console_file_version"), str)
        or not report.get("console_file_version")
        or report.get("child_environment") != {"DOTNET_ROLL_FORWARD": "LatestMajor"}
        or report.get("internal_iteration_bomb") != 600
        or report.get("outer_timeout_seconds_per_phase")
        != int(config.tools.godot_timeout_seconds)
        or report.get("post_exit_poll_seconds") != 5
        or report.get("timed_out") is not False
        or report.get("output_limited") is not False
        or report.get("cleanup_failed") is not False
        or report.get("cleanup_issue") != ""
        or report.get("application_error_windows") != []
        or report.get("application_events") != []
        or report.get("wer_and_dump_paths") != []
        or report.get("final_godot_processes") != []
        or report.get("has_crash_evidence") is not False
        or report.get("phases") != phases
        or not isinstance(phase_results, list)
        or len(phase_results) != 2
        or [item.get("phase") for item in phase_results if isinstance(item, dict)]
        != phases
        or any(
            not isinstance(item, dict)
            or set(item) != phase_keys
            or item.get("process_zero_preflight") is not True
            or item.get("post_exit_poll_seconds") != 5
            or item.get("exit_code") != 0
            for item in phase_results
        )
        or report.get("passed") is not True
        or report.get("failure_stage") is not None
        or report.get("failure_message") is not None
    ):
        raise FoundryError("Visual capture monitored Godot evidence is incomplete or failed.")


def _verify_exact_inputs(request_path, request, library, technical, bodies) -> None:
    _resolve_exact_input(request_path, request.animation_library, {".res"}, "animation library")
    _resolve_exact_input(request_path, request.technical_report, {".json"}, "technical report")
    if library != library.resolve() or technical != technical.resolve():
        raise FoundryError("Visual capture input resolution changed.")
    for body, _path, _sidecar, _bone_map in bodies:
        _resolve_exact_input(request_path, body, {".fbx"}, body.body_id)
        sidecar = _resolve_exact_input(
            request_path,
            body.import_sidecar,
            {".import"},
            f"{body.body_id} import sidecar",
        )
        _resolve_exact_input(
            request_path,
            body.bone_map,
            {".tres"},
            f"{body.body_id} BoneMap",
        )
        _validate_body_import_sidecar(body, sidecar)


def _review_template(manifest: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": manifest["target_import_schema_version"],
        "asset_id": manifest["asset_id"],
        "animation_library_sha256": manifest["animation_library_sha256"],
        "technical_report_sha256": manifest["technical_report_sha256"],
        "bodies": manifest["bodies"],
        "camera_policy": manifest["camera_policy"],
        "camera_config_sha256": manifest["camera_config_sha256"],
        "reviewer": None,
        "reviewed_at": None,
        "cells": [
            {
                "semantic": cell["semantic"],
                "body_id": cell["body_id"],
                "result": None,
                "observed_phases": cell["observed_phases"],
                "evidence": [cell["evidence"]],
                "notes": "",
            }
            for cell in manifest["cells"]
        ],
    }


def _require_sandbox_output(path: Path, sandbox: Path, label: str) -> Path:
    path = path.resolve()
    if not path.is_file() or path.parent != (sandbox / "output").resolve():
        raise FoundryError(f"Visual capture {label} is missing or outside its sandbox.")
    return path


def _require_entry_sentinel(sandbox: Path) -> Path:
    path = (sandbox / "output" / "capture-entry.json").resolve()
    expected_parent = (sandbox / "output").resolve()
    try:
        value = path.read_bytes()
    except OSError as exc:
        raise FoundryError(
            "Visual capture engine exited without entering the SceneTree script."
        ) from exc
    if path.parent != expected_parent or value != ENTRY_SENTINEL_BYTES:
        raise FoundryError("Visual capture entry sentinel is stale or invalid.")
    digest, size = _hash_file(path)
    if digest != ENTRY_SENTINEL_SHA256 or size != len(ENTRY_SENTINEL_BYTES):
        raise FoundryError("Visual capture entry sentinel hash binding differs.")
    return path


def _load_json(path: Path, label: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FoundryError(f"Could not read {label}: {exc}") from exc


def _copy_new(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with source.open("rb") as input_stream, destination.open("xb") as output_stream:
            shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
            output_stream.flush()
            os.fsync(output_stream.fileno())
    except OSError as exc:
        raise FoundryError(f"Could not copy visual capture file: {exc}") from exc


def _write_new(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise FoundryError(f"Could not write visual capture file: {exc}") from exc


def _validate_body_import_sidecar(body, sidecar: Path) -> None:
    try:
        value = sidecar.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise FoundryError(f"Could not read {body.body_id} import sidecar: {exc}") from exc
    source_paths = re.findall(r'^source_file="([^"]+)"$', value, flags=re.MULTILINE)
    animation_import = re.findall(
        r"^animation/import\s*=\s*(true|false)\s*$",
        value,
        flags=re.MULTILINE,
    )
    skeleton_blocks = re.findall(
        r'^_subresources\s*=\s*\{\s*\n'
        r'\s*"nodes"\s*:\s*\{\s*\n'
        r'\s*"PATH:Armature/Skeleton3D"\s*:\s*\{\s*\n'
        r'(.*?)'
        r'^\s*\}\s*\n\s*\}\s*\n\s*\}\s*$',
        value,
        flags=re.MULTILINE | re.DOTALL,
    )
    skeleton_policy: dict[str, str] = {}
    if len(skeleton_blocks) == 1:
        for line in skeleton_blocks[0].splitlines():
            if not line.strip():
                continue
            match = re.fullmatch(r'\s*"([^"]+)"\s*:\s*(.*?)\s*,?\s*', line)
            if match is None or match.group(1) in skeleton_policy:
                skeleton_policy = {}
                break
            skeleton_policy[match.group(1)] = match.group(2)
    required_policy = {
        "rest_pose/external_animation_library": "null",
        "retarget/bone_map": f'Resource("{body.bone_map.resource_path}")',
        "retarget/bone_renamer/rename_bones": "true",
        "retarget/bone_renamer/unique_node/make_unique": "true",
        "retarget/bone_renamer/unique_node/skeleton_name": '"GeneralSkeleton"',
        "retarget/remove_tracks/except_bone_transform": "false",
        "retarget/remove_tracks/unimportant_positions": "true",
        "retarget/remove_tracks/unmapped_bones": "0",
        "retarget/rest_fixer/apply_node_transforms": "true",
        "retarget/rest_fixer/fix_silhouette/base_height_adjustment": "0.0",
        "retarget/rest_fixer/fix_silhouette/enable": "false",
        "retarget/rest_fixer/fix_silhouette/filter": "[]",
        "retarget/rest_fixer/fix_silhouette/threshold": "15.0",
        "retarget/rest_fixer/keep_global_rest_on_leftovers": "true",
        "retarget/rest_fixer/normalize_position_tracks": "true",
        "retarget/rest_fixer/reset_all_bone_poses_after_import": "true",
        "retarget/rest_fixer/retarget_method": "1",
    }
    if (
        source_paths != [body.resource_path]
        or animation_import != ["false"]
        or len(skeleton_blocks) != 1
        or skeleton_policy != required_policy
    ):
        raise FoundryError(
            f"Visual capture {body.body_id} import sidecar is not the accepted body policy."
        )


def _sandbox_resource_path(sandbox: Path, resource_path: str) -> Path:
    relative = resource_path.removeprefix("res://")
    destination = (sandbox / Path(*relative.split("/"))).resolve()
    sandbox_root = sandbox.resolve()
    if destination == sandbox_root or sandbox_root not in destination.parents:
        raise FoundryError("Visual capture resource path escapes its sandbox.")
    return destination


def _copy_or_verify_exact(source: Path, destination: Path) -> None:
    if destination.exists():
        if not destination.is_file() or _hash_file(destination) != _hash_file(source):
            raise FoundryError(
                f"Visual capture staged resource collision differs: {destination}"
            )
        return
    _copy_new(source, destination)


def _retain_filtered_failure(
    operation_root: Path,
    failure_directory: Path,
) -> str | None:
    """Atomically retain bounded failure evidence while excluding raw outer logs."""
    staging_root = Path(
        tempfile.mkdtemp(
            prefix=f".{failure_directory.name}-retention-",
            dir=failure_directory.parent,
        )
    )
    staged = staging_root / "retained"
    staged.mkdir()
    try:
        entries = sorted(
            operation_root.rglob("*"),
            key=lambda path: (len(path.relative_to(operation_root).parts), str(path)),
        )
        for source in entries:
            relative = source.relative_to(operation_root)
            if source.name in RAW_OUTER_TEMP_NAMES:
                continue
            if any(part in TRANSIENT_FAILURE_DIRECTORY_NAMES for part in relative.parts):
                continue
            if source.is_symlink():
                raise OSError(f"Filtered failure retention rejects symlink: {source}")
            destination = staged / relative
            if source.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            elif source.is_file():
                _copy_new(source, destination)
            else:
                raise OSError(f"Durable failure evidence disappeared during retention: {source}")
        _verify_filtered_watchdog_evidence(operation_root, staged)
        os.rename(staged, failure_directory)
    except (OSError, FoundryError) as exc:
        raise OSError(
            f"filtered retention staging remains at {staging_root}: {exc}"
        ) from exc
    try:
        staging_root.rmdir()
    except OSError as exc:
        return f"empty retention staging directory remains at {staging_root}: {exc}"
    return None


def _verify_filtered_watchdog_evidence(operation_root: Path, staged: Path) -> None:
    raw = [path for path in staged.rglob("*") if path.name in RAW_OUTER_TEMP_NAMES]
    if raw:
        raise OSError("Filtered failure retention contains raw outer temp files.")
    transient = [
        path
        for path in staged.rglob("*")
        if any(part in TRANSIENT_FAILURE_DIRECTORY_NAMES for part in path.relative_to(staged).parts)
    ]
    if transient:
        raise OSError("Filtered failure retention contains transient Godot cache.")
    source_output = operation_root / "sandbox" / "output"
    output = staged / "sandbox" / "output"
    supervisor_name = "animation-visual-godot-monitor.json"
    source_supervisor = source_output / supervisor_name
    retained_supervisor = output / supervisor_name
    if source_supervisor.is_file():
        _verify_exact_retained_file(
            source_supervisor,
            retained_supervisor,
            "supervisor monitor",
        )
        try:
            monitor = json.loads(retained_supervisor.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OSError(f"Filtered supervisor monitor is unreadable: {exc}") from exc
        if (
            not isinstance(monitor, dict)
            or monitor.get("schema_version")
            != "vandrel_foundry_animation_visual_capture_monitor/1.0"
        ):
            raise OSError("Filtered supervisor monitor schema is invalid.")
        return
    if retained_supervisor.exists() or retained_supervisor.is_symlink():
        raise OSError("Filtered retention contains an unbound supervisor monitor.")
    record_path = output / "animation-visual-outer-watchdog.json"
    source_record_path = source_output / record_path.name
    _verify_exact_retained_file(source_record_path, record_path, "outer-watchdog record")
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OSError(f"Filtered outer-watchdog record is unavailable: {exc}") from exc
    maximum = record.get("maximum_output_bytes") if isinstance(record, dict) else None
    if not isinstance(maximum, int) or maximum < 1:
        raise OSError("Filtered outer-watchdog byte bound is invalid.")
    retained = 0
    for key in ("stdout_evidence", "stderr_evidence"):
        binding = record.get(key)
        if not isinstance(binding, dict):
            raise OSError("Filtered outer-watchdog stream binding is unavailable.")
        relative = str(binding.get("path", ""))
        path = output / Path(relative).name
        digest, size = _hash_file(path)
        if (
            relative != path.name
            or digest != binding.get("sha256")
            or size != binding.get("size_bytes")
        ):
            raise OSError("Filtered outer-watchdog stream binding is stale.")
        retained += size
    if retained > maximum:
        raise OSError("Filtered outer-watchdog evidence exceeds its byte bound.")


def _verify_exact_retained_file(source: Path, retained: Path, label: str) -> None:
    if not source.is_file() or not retained.is_file():
        raise OSError(f"Filtered {label} is unavailable.")
    if _hash_file(source) != _hash_file(retained):
        raise OSError(f"Filtered {label} bytes differ from the captured attempt.")


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise FoundryError(f"Could not hash visual capture file: {exc}") from exc
    return digest.hexdigest(), size
