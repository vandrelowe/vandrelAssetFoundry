"""Strict monitored Godot validation/capture for clean bodies."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.clean_meshy_body import (
    CLEAN_BODY_REST_VIEWS,
    CLEAN_BODY_SHARED_PHASES,
    CleanBodyValidationRequest,
)
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, utc_now
from vandrel_foundry.domain.release_descriptor import (
    ReleaseDescriptorV2,
    format_release_revision,
    validate_release_descriptor,
)
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.domain.workflow_policy import invalidate_approval, transition_workflow
from vandrel_foundry.services.audit_library import audit_library_asset
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path

PROCESSOR = Processor(name="godot_clean_body_shared_animation_validation", version="1")


@dataclass(frozen=True)
class CleanBodyValidationExecution:
    technical_report: Path
    monitor_report: Path
    capture_manifest: Path


@dataclass(frozen=True)
class SharedAnimationLibraryBinding:
    payload_path: Path
    payload_sha256: str
    payload_size_bytes: int
    descriptor_path: Path
    descriptor_sha256: str
    semantics: tuple[str, ...]


class CleanBodyValidationRunner(Protocol):
    def __call__(self, config: FoundryConfig, sandbox: Path) -> CleanBodyValidationExecution: ...


def validate_clean_meshy_body(
    config: FoundryConfig,
    asset_id: str,
    request_path: Path,
    runner: CleanBodyValidationRunner | None = None,
) -> list[Artifact]:
    request = _load_request(request_path)
    if request.asset_id != asset_id:
        raise FoundryError("Clean-body validation request targets another asset.")
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.workflow.state not in {WorkflowState.PROCESSED, WorkflowState.REVIEW}:
        raise FoundryError("Clean-body validation requires a processed candidate.")
    model = _latest(manifest.artifacts, "processed_model")
    buffer = _latest(manifest.artifacts, "processed_clean_body_buffer")
    albedo = _latest(manifest.artifacts, "processed_clean_body_albedo")
    if model.processor is None or model.processor.name != "blender_clean_meshy_body":
        raise FoundryError("Clean-body validation rejects other processor routes.")
    asset_root = repository.asset_directory(asset_id)
    for item in (model, buffer, albedo):
        _verify(contained_path(asset_root, item.path), item.sha256, item.size_bytes, item.role)
    resolved = [
        (_resolve(request_path, request.accepted_bone_map.path), request.accepted_bone_map, "BoneMap"),
        (_resolve(request_path, request.accepted_import_sidecar_policy.path), request.accepted_import_sidecar_policy, "sidecar policy"),
    ]
    for path, binding, label in resolved:
        _verify(path, binding.sha256, binding.size_bytes, label)
    shared_library = _resolve_shared_animation_library(config, request)
    attempt_root = asset_root / "reports" / "clean_body_validation_001"
    if attempt_root.exists() or attempt_root.with_name(attempt_root.name + ".failed").exists():
        raise FoundryError("Clean-body validation attempt already exists; unchanged-input retry is forbidden.")
    operation = Path(tempfile.mkdtemp(prefix=".clean-body-validation-", dir=asset_root / "reports"))
    try:
        sandbox = operation / "sandbox"
        _stage_sandbox(asset_root, model, buffer, albedo, request, resolved, shared_library, sandbox)
        execution = (runner or _run_monitored)(config, sandbox)
        facts = _validate_reports(request, shared_library, model.sha256, execution)
        durable = operation / "durable"
        durable.mkdir()
        for source, name in ((execution.technical_report, "technical.json"), (execution.monitor_report, "monitor.json"), (execution.capture_manifest, "capture-manifest.json")):
            shutil.copyfile(source, durable / name)
        for cell in facts["cells"]:
            source = execution.capture_manifest.parent / cell["path"]
            _verify(source, cell["sha256"], cell["size_bytes"], "capture cell")
            shutil.copyfile(source, durable / Path(cell["path"]).name)
        _remove_scratch_tree(sandbox)
        os.replace(durable, attempt_root)
        operation.rmdir()
    except BaseException:
        if operation.exists(): os.replace(operation, attempt_root.with_name(attempt_root.name + ".failed"))
        raise
    specs = [
        ("clean_body_technical_report_001", "clean_body_technical_report", "json", "technical.json"),
        ("clean_body_godot_monitor_report_001", "clean_body_godot_monitor_report", "json", "monitor.json"),
        ("clean_body_visual_capture_manifest_001", "clean_body_visual_capture_manifest", "json", "capture-manifest.json"),
    ]
    artifacts: list[Artifact] = []
    for artifact_id, role, fmt, name in specs:
        digest, size = _hash(attempt_root / name)
        artifacts.append(Artifact(artifact_id=artifact_id, role=role, stage="validation", format=fmt, path=RelativeManifestPath(f"reports/clean_body_validation_001/{name}"), sha256=digest, size_bytes=size, derived_from=[model.artifact_id], processor=PROCESSOR))
    for index, cell in enumerate(facts["cells"], start=1):
        name = Path(cell["path"]).name
        artifacts.append(Artifact(artifact_id=f"clean_body_capture_evidence_{index:03d}", role="clean_body_capture_evidence", stage="validation", format=Path(name).suffix.removeprefix("."), path=RelativeManifestPath(f"reports/clean_body_validation_001/{name}"), sha256=cell["sha256"], size_bytes=cell["size_bytes"], derived_from=[model.artifact_id], processor=PROCESSOR))
    revision = manifest.revision
    manifest.artifacts.extend(artifacts)
    manifest.validation.result = "not_run"
    manifest.validation.checks = [
        {"name": "clean_body_technical_probe", "passed": True, "processed_body_sha256": model.sha256, "report_sha256": artifacts[0].sha256, "shared_animation_library_asset_id": request.shared_animation_library_asset_id, "shared_animation_library_release_revision": request.shared_animation_library_release_revision, "shared_animation_library_sha256": shared_library.payload_sha256, "shared_animation_library_descriptor_sha256": shared_library.descriptor_sha256},
        {"name": "clean_body_monitored_godot", "passed": True, "processed_body_sha256": model.sha256, "report_sha256": artifacts[1].sha256},
        {"name": "clean_body_visual_review", "passed": False, "manual_review_required": True},
    ]
    transition_workflow(manifest, WorkflowState.REVIEW); invalidate_approval(manifest)
    manifest.revision += 1; manifest.asset.updated_at = utc_now()
    try:
        repository.save(manifest, "asset.clean_body_validated_for_manual_review", expected_revision=revision)
    except BaseException:
        live = repository.load(asset_id)
        if live.revision == manifest.revision and _references(live.artifacts, artifacts):
            return artifacts
        if live.revision == revision and not _references(live.artifacts, artifacts):
            shutil.rmtree(attempt_root)
        raise
    return artifacts


def _remove_scratch_tree(path: Path) -> None:
    """Remove run-owned Godot cache after process-zero without losing durable evidence."""
    delays = (0.0, 0.05, 0.1, 0.2, 0.4, 0.8)
    last_error: OSError | None = None
    for delay in delays:
        if delay:
            time.sleep(delay)
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError as error:
            last_error = error
    raise FoundryError(f"Clean-body scratch cleanup failed after process-zero: {last_error}")


def _run_monitored(config: FoundryConfig, sandbox: Path) -> CleanBodyValidationExecution:
    # The dedicated supervisor owns this route; importing the animation runner is forbidden here.
    from vandrel_foundry.services.run_clean_meshy_body_godot import run_monitored_clean_body
    return run_monitored_clean_body(config, sandbox)


def _stage_sandbox(asset_root: Path, model: Artifact, buffer: Artifact, albedo: Artifact, request: CleanBodyValidationRequest, resolved: list, shared_library: SharedAnimationLibraryBinding, sandbox: Path) -> None:
    (sandbox / "input").mkdir(parents=True)
    (sandbox / "output").mkdir()
    shutil.copyfile(contained_path(asset_root, model.path), sandbox / "input/body.gltf")
    shutil.copyfile(contained_path(asset_root, buffer.path), sandbox / "input/body.bin")
    shutil.copyfile(contained_path(asset_root, albedo.path), sandbox / "input/albedo.png")
    shutil.copyfile(resolved[0][0], sandbox / "input/bone_map.tres")
    shutil.copyfile(shared_library.payload_path, sandbox / "input/shared_animation_library.res")
    runtime = {
        "schema_version": "vandrel_foundry_clean_meshy_body_runtime/1.0",
        "asset_id": request.asset_id,
        "processed_body_sha256": model.sha256,
        "accepted_bone_map": {"sha256": request.accepted_bone_map.sha256, "size_bytes": request.accepted_bone_map.size_bytes},
        "sidecar_policy_source_sha256": request.accepted_import_sidecar_policy.sha256,
        "sidecar_policy_copied": False,
        "shared_animation_library": {"asset_id": request.shared_animation_library_asset_id, "release_revision": request.shared_animation_library_release_revision, "sha256": shared_library.payload_sha256, "size_bytes": shared_library.payload_size_bytes, "descriptor_sha256": shared_library.descriptor_sha256},
        "shared_semantics": request.shared_semantics,
        "import_policy": request.import_policy,
        "camera_policy": request.camera_policy,
        "camera_config_sha256": request.camera_config_sha256,
    }
    (sandbox / "runtime.json").write_text(json.dumps(runtime, indent=2) + "\n", encoding="utf-8")
    (sandbox / "project.godot").write_text('[application]\nconfig/name="FoundryCleanBody"\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n', encoding="utf-8")
    scripts = Path(__file__).parents[1] / "godot"
    for name in ("configure_clean_meshy_body_import.gd", "validate_clean_meshy_body.gd", "capture_clean_meshy_body.gd"):
        shutil.copyfile(scripts / name, sandbox / name)


def _validate_reports(request: CleanBodyValidationRequest, shared_library: SharedAnimationLibraryBinding, body_sha: str, execution: CleanBodyValidationExecution) -> dict:
    technical = json.loads(execution.technical_report.read_text(encoding="utf-8"))
    monitor = json.loads(execution.monitor_report.read_text(encoding="utf-8"))
    capture = json.loads(execution.capture_manifest.read_text(encoding="utf-8"))
    expected = {"schema_version": "vandrel_foundry_clean_body_technical/1.1", "processed_body_sha256": body_sha, "bone_map_sha256": request.accepted_bone_map.sha256, "sidecar_policy_source_sha256": request.accepted_import_sidecar_policy.sha256, "shared_animation_library_sha256": shared_library.payload_sha256, "shared_animation_library_descriptor_sha256": shared_library.descriptor_sha256, "skeleton_name": "GeneralSkeleton", "mapped_bone_count": 22, "skeleton_count": 1, "animation_count": 0, "skin_present": True, "bind_count_positive": True, "weights_present": True, "rest_pose_valid": True, "import_policy_valid": True, "external_lit_albedo": True, "casts_shadows": True, "scale_finite_positive": True, "grounded": True, "shared_animation_pool_compatible": True}
    if any(technical.get(key) != value for key, value in expected.items()):
        raise FoundryError("Clean-body technical report does not prove the exact acceptance facts.")
    if not isinstance(technical.get("material_surface_count"), int) or technical["material_surface_count"] < 1:
        raise FoundryError("Clean-body technical report has no validated material surfaces.")
    if sorted(technical.get("shared_semantics", [])) != sorted(request.shared_semantics):
        raise FoundryError("Clean-body technical report has different shared semantics.")
    expected_phases = ["initial_import", "configure_import", "retargeted_import", "technical_validate", "visual_capture"]
    _validate_monitor(monitor, expected_phases)
    if capture.get("schema_version") != "vandrel_foundry_clean_body_capture/1.0" or capture.get("processed_body_sha256") != body_sha or capture.get("shared_animation_library_sha256") != shared_library.payload_sha256 or capture.get("shared_animation_library_descriptor_sha256") != shared_library.descriptor_sha256 or capture.get("camera_config_sha256") != request.camera_config_sha256 or capture.get("review_status") != "manual_review_required" or capture.get("cells") is None:
        raise FoundryError("Clean-body capture manifest is not exact or is self-approving.")
    expected_cells = 3 + len(request.shared_semantics)
    if len(capture["cells"]) != expected_cells or len({cell["sha256"] for cell in capture["cells"]}) != expected_cells:
        raise FoundryError("Clean-body capture requires unique rest and shared-motion evidence cells.")
    rest = capture["cells"][:3]
    motion = capture["cells"][3:]
    if [cell.get("kind") for cell in rest] != ["rest"] * 3 or [cell.get("label") for cell in rest] != list(CLEAN_BODY_REST_VIEWS) or any(cell.get("phases") != [] or cell.get("result") is not None for cell in rest):
        raise FoundryError("Clean-body capture does not contain exact manual-null rest views.")
    if [cell.get("kind") for cell in motion] != ["motion"] * len(motion) or [cell.get("label") for cell in motion] != request.shared_semantics or any(tuple(cell.get("phases", [])) != CLEAN_BODY_SHARED_PHASES or cell.get("result") is not None for cell in motion):
        raise FoundryError("Clean-body capture does not contain exact manual-null motion phases.")
    for cell in capture["cells"]:
        path = Path(str(cell.get("path", "")))
        if path.name != str(path) or path.suffix.casefold() != ".png" or not isinstance(cell.get("size_bytes"), int) or cell["size_bytes"] < 1 or not isinstance(cell.get("sha256"), str) or len(cell["sha256"]) != 64:
            raise FoundryError("Clean-body capture cell binding is not portable and exact.")
    return capture


def _validate_monitor(monitor: object, expected_phases: list[str]) -> None:
    top_keys = {
        "schema_version", "policy", "run_started_utc", "run_ended_utc",
        "console_executable_name", "console_file_version", "godot_console_sha256",
        "supervisor_sha256", "runtime_guard_sha256", "crash_evidence_authority_sha256",
        "process_zero_preflight", "child_environment", "phase_results",
        "outer_timeout_seconds_per_phase", "maximum_output_bytes", "internal_iteration_bomb",
        "post_exit_poll_seconds", "timed_out", "output_limited", "cleanup_failed", "failure",
        "application_error_windows", "application_events", "wer_and_dump_paths",
        "final_godot_processes", "has_crash_evidence", "passed",
    }
    if not isinstance(monitor, dict) or set(monitor) != top_keys:
        raise FoundryError("Clean-body monitor does not use the exact closed schema.")
    hashes = ("godot_console_sha256", "supervisor_sha256", "runtime_guard_sha256", "crash_evidence_authority_sha256")
    if any(not isinstance(monitor[key], str) or len(monitor[key]) != 64 or any(character not in "0123456789abcdef" for character in monitor[key]) for key in hashes):
        raise FoundryError("Clean-body monitor authority hashes are incomplete.")
    if (
        monitor["schema_version"] != "vandrel_foundry_clean_body_godot_monitor/1.0"
        or monitor["policy"] != "vandrel_monitored_godot_clean_body_corridor_2026-08-21"
        or not isinstance(monitor["console_executable_name"], str)
        or not monitor["console_executable_name"].casefold().endswith("console.exe")
        or not isinstance(monitor["console_file_version"], str)
        or not monitor["console_file_version"]
        or monitor["passed"] is not True
        or monitor["has_crash_evidence"] is not False
        or monitor["timed_out"] is not False
        or monitor["output_limited"] is not False
        or monitor["cleanup_failed"] is not False
        or monitor["failure"] != ""
        or monitor["process_zero_preflight"] is not True
        or monitor["child_environment"] != {"DOTNET_ROLL_FORWARD": "LatestMajor"}
        or not isinstance(monitor["outer_timeout_seconds_per_phase"], int)
        or not 1 <= monitor["outer_timeout_seconds_per_phase"] <= 900
        or not isinstance(monitor["maximum_output_bytes"], int)
        or not 1 <= monitor["maximum_output_bytes"] <= 50_000_000
        or monitor["internal_iteration_bomb"] != 600
        or not isinstance(monitor["post_exit_poll_seconds"], int)
        or monitor["post_exit_poll_seconds"] < 5
        or monitor["final_godot_processes"] != []
        or monitor["application_error_windows"] != []
        or monitor["application_events"] != []
        or monitor["wer_and_dump_paths"] != []
    ):
        raise FoundryError("Clean-body monitored Godot evidence did not pass.")
    phase_keys = {"phase", "exit_code", "timed_out", "cleanup_failed", "has_crash_evidence", "crash_evidence_path", "stdout_path", "stderr_path", "godot_log_path"}
    phases = monitor["phase_results"]
    if not isinstance(phases, list) or [item.get("phase") for item in phases if isinstance(item, dict)] != expected_phases:
        raise FoundryError("Clean-body monitor phase membership differs.")
    for item in phases:
        if set(item) != phase_keys or item["exit_code"] != 0 or item["timed_out"] is not False or item["cleanup_failed"] is not False or item["has_crash_evidence"] is not False:
            raise FoundryError("Clean-body monitor contains a failed or incomplete phase.")
        for key in ("crash_evidence_path", "stdout_path", "stderr_path", "godot_log_path"):
            path = Path(item[key])
            if path.name != str(path) or not path.name:
                raise FoundryError("Clean-body monitor phase evidence path is not portable.")


def _resolve_shared_animation_library(config: FoundryConfig, request: CleanBodyValidationRequest) -> SharedAnimationLibraryBinding:
    """Resolve one exact immutable, audited animation-library release from custody."""
    root = config.foundry.asset_library_root
    catalog_path = root / "catalog.json"
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        asset_entry = catalog["assets"][request.shared_animation_library_asset_id]
        release_entry = next(
            entry
            for entry in asset_entry["releases"]
            if entry.get("revision") == request.shared_animation_library_release_revision
        )
    except (OSError, json.JSONDecodeError, KeyError, StopIteration, TypeError) as exc:
        raise FoundryError("Requested shared animation-library release is not cataloged.") from exc
    expected_descriptor = (
        f"assets/{request.shared_animation_library_asset_id}/"
        f"{format_release_revision(request.shared_animation_library_release_revision)}/asset-release.json"
    )
    if release_entry.get("path") != expected_descriptor:
        raise FoundryError("Shared animation-library descriptor path is not canonical.")
    descriptor_path = contained_path(root, expected_descriptor)
    descriptor_sha256, _ = _hash(descriptor_path)
    if release_entry.get("descriptor_sha256") != descriptor_sha256:
        raise FoundryError("Shared animation-library catalog descriptor binding changed.")
    try:
        descriptor = validate_release_descriptor(
            json.loads(descriptor_path.read_text(encoding="utf-8"))
        )
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise FoundryError("Shared animation-library descriptor is invalid.") from exc
    if (
        not isinstance(descriptor, ReleaseDescriptorV2)
        or descriptor.asset_id != request.shared_animation_library_asset_id
        or descriptor.release_revision != request.shared_animation_library_release_revision
        or descriptor.lane != "animation_library"
        or descriptor.primary_payload != "animation_library"
        or descriptor.animation_library is None
    ):
        raise FoundryError("Requested release is not an immutable animation-library payload.")
    payload_files = [item for item in descriptor.files if item.role == "animation_library"]
    if len(payload_files) != 1:
        raise FoundryError("Shared animation-library release has no unique primary payload.")
    payload = payload_files[0]
    payload_path = contained_path(descriptor_path.parent, payload.path)
    _verify(payload_path, payload.sha256, payload.size_bytes, "shared animation library")
    if payload.sha256 != request.shared_animation_library_sha256:
        raise FoundryError("Shared animation-library payload differs from the request binding.")
    semantics = tuple(item.semantic for item in descriptor.animation_library.selected_sources)
    if semantics != tuple(request.shared_semantics):
        raise FoundryError("Shared animation-library semantics differ from the immutable release.")
    audit = audit_library_asset(config, request.shared_animation_library_asset_id)
    if audit is None or not audit.passed:
        raise FoundryError("Shared animation-library release failed the immutable-library audit.")
    return SharedAnimationLibraryBinding(
        payload_path=payload_path,
        payload_sha256=payload.sha256,
        payload_size_bytes=payload.size_bytes,
        descriptor_path=descriptor_path,
        descriptor_sha256=descriptor_sha256,
        semantics=semantics,
    )


def _load_request(path: Path) -> CleanBodyValidationRequest:
    try: return CleanBodyValidationRequest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError) as exc: raise FoundryError(f"Invalid clean-body validation request: {exc}") from exc


def _resolve(request: Path, value: str) -> Path:
    path = Path(value); return path if path.is_absolute() else request.parent / path


def _latest(artifacts: list[Artifact], role: str) -> Artifact:
    values = [item for item in artifacts if item.role == role]
    if not values: raise FoundryError(f"Clean-body artifact role is missing: {role}")
    return values[-1]


def _verify(path: Path, sha: str, size: int, label: str) -> None:
    if not path.is_file() or _hash(path) != (sha, size): raise FoundryError(f"Clean-body {label} changed.")


def _hash(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256(); size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024): digest.update(chunk); size += len(chunk)
    return digest.hexdigest(), size


def _references(live: list[Artifact], targets: list[Artifact]) -> bool:
    expected = {(item.artifact_id, item.sha256, item.size_bytes) for item in targets}
    actual = {(item.artifact_id, item.sha256, item.size_bytes) for item in live}
    return expected.issubset(actual)
