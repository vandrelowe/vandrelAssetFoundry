"""Selective, animation-only intake, evidence, and approval services."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import sys
import time
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import ParamSpec, Protocol, TypeVar

from pydantic import ValidationError

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.animation_library import (
    ANIMATION_IMPORT_POLICY,
    AnimationLibraryIntakeRequest,
    AnimationVisualMatrixRequest,
)
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.domain.workflow_policy import invalidate_approval, transition_workflow
from vandrel_foundry.storage.atomic import json_bytes
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path

ANIMATION_LIBRARY_LANE = "animation_library"
PROCESSOR_NAME = "godot_selective_animation_library"
PROCESSOR_VERSION = "3"
TECHNICAL_SCHEMA = "vandrel_foundry_animation_library_technical/1.0"
HIPS_HORIZONTAL_POLICY = "hold_hips_xz_at_first_key_preserve_y_time_interpolation_v1"
HORIZONTAL_ROOT_TOLERANCE = 0.0001
MONITOR_SCHEMA = "vandrel_foundry_animation_godot_monitor/1.0"
VISUAL_REPORT_SCHEMA = "vandrel_foundry_animation_visual_matrix_result/1.0"

SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")
P = ParamSpec("P")
R = TypeVar("R")
_ACTIVE_OPERATION_ROOTS: ContextVar[tuple[Path, ...]] = ContextVar(
    "animation_library_operation_roots",
    default=(),
)


@dataclass(frozen=True)
class AnimationPipelineExecution:
    animation_library: Path
    technical_report: Path
    isolation_report: Path
    monitor_report: Path


class AnimationPipelineRunner(Protocol):
    def __call__(
        self,
        config: FoundryConfig,
        sandbox: Path,
    ) -> AnimationPipelineExecution: ...


def _transactional_operation(function: Callable[P, R]) -> Callable[P, R]:
    """Clean successful staging while retaining failed operation evidence."""

    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        token = _ACTIVE_OPERATION_ROOTS.set(())
        try:
            return function(*args, **kwargs)
        finally:
            primary_failure = sys.exc_info()[0] is not None
            try:
                if not primary_failure:
                    for root in reversed(_ACTIVE_OPERATION_ROOTS.get()):
                        if root.is_dir():
                            _remove_operation_root(root)
            finally:
                _ACTIVE_OPERATION_ROOTS.reset(token)

    return wrapped


def _remove_operation_root(root: Path) -> None:
    last_error: OSError | None = None
    for delay_seconds in (0.05, 0.15, 0.4):
        try:
            shutil.rmtree(root)
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            last_error = exc
            time.sleep(delay_seconds)
    assert last_error is not None
    raise last_error


@_transactional_operation
def intake_animation_library(
    config: FoundryConfig,
    asset_id: str,
    request_path: Path,
) -> tuple[Artifact, ...]:
    """Copy only an exact request-selected set of local FBXs into candidate custody."""
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.asset.lane != ANIMATION_LIBRARY_LANE:
        raise FoundryError("Animation-only intake requires the animation_library lane.")
    if manifest.workflow.state is not WorkflowState.DRAFT:
        raise FoundryError("Animation-only intake requires a draft candidate.")
    request, request_bytes = _load_intake_request(request_path, asset_id)
    selected_hashes = {item.source_sha256 for item in request.motions}
    policy_bytes = json_bytes(request.package_policy.model_dump(mode="json"))
    if hashlib.sha256(policy_bytes).hexdigest() != request.package_policy_sha256:
        raise FoundryError("Animation package policy hash is stale.")
    selected_fingerprint = hashlib.sha256(
        json_bytes([item.source_sha256 for item in request.motions])
    ).hexdigest()
    forbidden = set(request.package_policy.forbidden_aggregate_payload_sha256s)
    if selected_hashes & forbidden or selected_fingerprint in forbidden:
        raise FoundryError("Animation package policy rejects a superseded aggregate payload.")

    resolved: list[tuple[object, Path]] = []
    for motion in request.motions:
        path = Path(motion.source_path)
        if not path.is_absolute():
            path = request_path.resolve().parent / path
        path = path.resolve()
        if path.suffix.casefold() != ".fbx" or not path.is_file():
            raise FoundryError(f"Animation source is not an existing FBX: {motion.semantic}")
        digest, size = _hash_file(path)
        if digest != motion.source_sha256 or size != motion.source_size_bytes:
            raise FoundryError(f"Animation source bytes do not match request: {motion.semantic}")
        resolved.append((motion, path))

    asset_root = config.foundry.workspace_root / "assets" / asset_id
    request_relative = RelativeManifestPath("input/animation-library-request.json")
    operation_root = _new_operation_root(asset_root, "animation-intake")
    request_destination = operation_root / request_relative
    _write_new(request_destination, request_bytes)
    promotions: list[tuple[Path, RelativeManifestPath, str]] = [
        (request_destination, request_relative, hashlib.sha256(request_bytes).hexdigest())
    ]
    artifacts = [
        Artifact(
            artifact_id="animation_library_intake_request_001",
            role="animation_library_intake_request",
            stage="source",
            format="json",
            path=request_relative,
            sha256=hashlib.sha256(request_bytes).hexdigest(),
            size_bytes=len(request_bytes),
        )
    ]
    for index, (motion, source) in enumerate(resolved, start=1):
        relative = RelativeManifestPath(f"source/{motion.semantic}.fbx")
        destination = operation_root / relative
        _copy_new(source, destination)
        promotions.append((destination, relative, motion.source_sha256))
        artifacts.append(
            Artifact(
                artifact_id=f"animation_source_{index:03d}",
                role="animation_source_fbx",
                stage="source",
                format="fbx",
                path=relative,
                sha256=motion.source_sha256,
                size_bytes=motion.source_size_bytes,
            )
        )

    manifest.artifacts.extend(artifacts)
    manifest.vandrel_technical["animation_library_membership"] = {
        "schema_version": "vandrel_foundry_animation_library_membership/1.0",
        "request_sha256": artifacts[0].sha256,
        "selected": [
            {
                "semantic": motion.semantic,
                "source_artifact_id": artifacts[index].artifact_id,
                "source_sha256": motion.source_sha256,
                "source_size_bytes": motion.source_size_bytes,
                "loop_mode": motion.loop_mode,
            }
            for index, motion in enumerate(request.motions, start=1)
        ],
        "explicit_exclusions": [item.model_dump(mode="json") for item in request.explicit_exclusions],
        "import_policy": request.import_policy,
        "package_policy": request.package_policy.model_dump(mode="json"),
        "package_policy_sha256": request.package_policy_sha256,
    }
    invalidate_approval(manifest)
    transition_workflow(manifest, WorkflowState.DOWNLOADED)
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    _promote_and_save(
        repository,
        manifest,
        asset_root,
        operation_root,
        promotions,
        "animation_library.intaken",
    )
    return tuple(artifacts)


@_transactional_operation
def normalize_animation_library(
    config: FoundryConfig,
    asset_id: str,
    runner: AnimationPipelineRunner | None = None,
) -> AnimationPipelineExecution:
    """Run one exact selected set through the monitored Godot import/finalize corridor."""
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.asset.lane != ANIMATION_LIBRARY_LANE:
        raise FoundryError("Animation normalization requires the animation_library lane.")
    if manifest.workflow.state is not WorkflowState.DOWNLOADED:
        raise FoundryError("Animation normalization requires downloaded exact sources.")
    membership = _membership(manifest)
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    _verify_membership_artifacts(asset_root, manifest, membership)
    operation_root = _new_operation_root(asset_root, "animation-normalize")
    sandbox = operation_root / "sandbox"
    _stage_animation_sandbox(asset_root, sandbox, membership)

    if runner is None:
        from vandrel_foundry.services.run_animation_godot import (
            run_monitored_animation_pipeline,
        )

        runner = run_monitored_animation_pipeline
    execution = runner(config, sandbox)
    for path in (
        execution.animation_library,
        execution.technical_report,
        execution.isolation_report,
        execution.monitor_report,
    ):
        if not path.is_file() or path.resolve().parent != (sandbox / "output").resolve():
            raise FoundryError("Animation pipeline output is missing or outside its sandbox.")
    library_sha, library_size = _hash_file(execution.animation_library)
    forbidden = set(membership["package_policy"]["forbidden_aggregate_payload_sha256s"])
    if library_sha in forbidden:
        raise FoundryError("Animation pipeline reproduced a superseded aggregate payload.")
    technical = _load_json(execution.technical_report, "animation technical report")
    _validate_technical_report(technical, membership, library_sha, library_size)
    isolation = _load_json(execution.isolation_report, "animation isolation report")
    if (
        not isinstance(isolation, dict)
        or isolation.get("schema_version")
        != "vandrel_foundry_animation_library_isolation/1.0"
        or isolation.get("animation_library_sha256") != library_sha
        or isolation.get("selected_semantics")
        != [item["semantic"] for item in membership["selected"]]
        or isolation.get("external_dependencies") != []
        or isolation.get("source_fbx_directory_present") is not False
        or isolation.get("prior_import_cache_present") is not False
        or isolation.get("passed") is not True
    ):
        raise FoundryError("Finished animation library is not isolated and self-contained.")
    monitor = _load_json(execution.monitor_report, "animation Godot monitor report")
    supervisor = (
        Path(__file__).resolve().parent.parent
        / "godot"
        / "Invoke-FoundryAnimationLibraryMonitored.ps1"
    )
    executable = config.tools.godot_executable
    if executable is None:
        raise FoundryError("Animation Godot console identity is unavailable.")
    _validate_monitor_report(
        monitor,
        expected_supervisor_sha256=_hash_file(supervisor)[0],
        expected_godot_sha256=_hash_file(executable)[0],
        expected_timeout_seconds=int(config.tools.godot_timeout_seconds),
    )

    processed_relative = RelativeManifestPath("processed/animation_library.res")
    technical_relative = RelativeManifestPath("reports/animation-library-technical-001.json")
    isolation_relative = RelativeManifestPath("reports/animation-library-isolation-001.json")
    monitor_relative = RelativeManifestPath("reports/animation-library-godot-monitor-001.json")
    destinations = (
        (execution.animation_library, processed_relative),
        (execution.technical_report, technical_relative),
        (execution.isolation_report, isolation_relative),
        (execution.monitor_report, monitor_relative),
    )
    processor = Processor(name=PROCESSOR_NAME, version=PROCESSOR_VERSION)
    source_ids = [item["source_artifact_id"] for item in membership["selected"]]
    library_artifact = _artifact_from_source(
        execution.animation_library,
        "processed_animation_library_001",
        "processed_animation_library",
        "processed",
        "res",
        processed_relative,
        source_ids,
        processor,
    )
    technical_artifact = _artifact_from_source(
        execution.technical_report,
        "animation_library_technical_report_001",
        "animation_library_technical_report",
        "validation",
        "json",
        technical_relative,
        [library_artifact.artifact_id, *source_ids],
        processor,
    )
    monitor_artifact = _artifact_from_source(
        execution.monitor_report,
        "animation_library_godot_monitor_001",
        "animation_library_godot_monitor_report",
        "validation",
        "json",
        monitor_relative,
        [library_artifact.artifact_id],
        processor,
    )
    isolation_artifact = _artifact_from_source(
        execution.isolation_report,
        "animation_library_isolation_report_001",
        "animation_library_isolation_report",
        "validation",
        "json",
        isolation_relative,
        [library_artifact.artifact_id],
        processor,
    )
    manifest.artifacts.extend(
        [library_artifact, technical_artifact, monitor_artifact, isolation_artifact]
    )
    manifest.quality.observed.update(
        {
            "animation_count": len(membership["selected"]),
            "inspected_processed_artifact_id": library_artifact.artifact_id,
            "inspected_processed_sha256": library_artifact.sha256,
        }
    )
    manifest.validation.checks = [
        item
        for item in manifest.validation.checks
        if item.get("name")
        not in {
            "animation_library_monitored_godot",
            "animation_library_technical_probe",
            "animation_library_isolation",
        }
    ] + [
        {
            "name": "animation_library_monitored_godot",
            "passed": True,
            "report": str(monitor_relative),
            "report_sha256": monitor_artifact.sha256,
            "animation_library_sha256": library_artifact.sha256,
            "policy": monitor["policy"],
        },
        {
            "name": "animation_library_isolation",
            "passed": True,
            "report": str(isolation_relative),
            "report_sha256": isolation_artifact.sha256,
            "animation_library_sha256": library_artifact.sha256,
            "external_dependencies": [],
        },
        {
            "name": "animation_library_technical_probe",
            "passed": True,
            "report": str(technical_relative),
            "report_sha256": technical_artifact.sha256,
            "animation_library_sha256": library_artifact.sha256,
            "selected_semantics": [item["semantic"] for item in membership["selected"]],
            "import_policy": ANIMATION_IMPORT_POLICY,
        },
    ]
    manifest.validation.result = "passed"
    invalidate_approval(manifest)
    transition_workflow(manifest, WorkflowState.PROCESSED)
    transition_workflow(manifest, WorkflowState.REVIEW)
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    _promote_and_save(
        repository,
        manifest,
        asset_root,
        operation_root,
        [
            (source, relative, _hash_file(source)[0])
            for source, relative in destinations
        ],
        "animation_library.normalized",
    )
    return AnimationPipelineExecution(
        animation_library=contained_path(asset_root, processed_relative),
        technical_report=contained_path(asset_root, technical_relative),
        isolation_report=contained_path(asset_root, isolation_relative),
        monitor_report=contained_path(asset_root, monitor_relative),
    )


@_transactional_operation
def import_animation_visual_matrix(
    config: FoundryConfig,
    asset_id: str,
    request_path: Path,
) -> Artifact:
    """Import an exact three-body fixed-phase decision matrix without inferring PASS."""
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.asset.lane != ANIMATION_LIBRARY_LANE or manifest.workflow.state is not WorkflowState.REVIEW:
        raise FoundryError("Animation visual evidence requires an animation library in review.")
    request = _load_visual_request(request_path, asset_id)
    library = _latest_artifact(manifest, "processed_animation_library")
    technical = _latest_artifact(manifest, "animation_library_technical_report")
    if (
        request.animation_library_sha256 != library.sha256
        or request.technical_report_sha256 != technical.sha256
    ):
        raise FoundryError("Visual evidence is stale for the current animation library.")
    semantics = [item["semantic"] for item in _membership(manifest)["selected"]]
    body_ids = [body.body_id for body in request.bodies]
    expected_cells = {(semantic, body) for semantic in semantics for body in body_ids}
    actual_cells = {(cell.semantic, cell.body_id) for cell in request.cells}
    if actual_cells != expected_cells:
        raise FoundryError("Visual evidence must contain the exact semantic x three-body grid.")

    asset_root = config.foundry.workspace_root / "assets" / asset_id
    operation_root = _new_operation_root(asset_root, "animation-visual")
    request_root = request_path.resolve().parent
    evidence_artifacts: list[Artifact] = []
    promotions: list[tuple[Path, RelativeManifestPath, str]] = []
    cells: list[dict[str, object]] = []
    evidence_index = 0
    for cell in request.cells:
        copied: list[dict[str, object]] = []
        for evidence in cell.evidence:
            source = Path(evidence.path)
            if not source.is_absolute():
                source = request_root / source
            source = source.resolve()
            digest, size = _hash_file(source)
            if digest != evidence.sha256 or size != evidence.size_bytes:
                raise FoundryError(
                    f"Visual evidence bytes do not match: {cell.semantic}/{cell.body_id}"
                )
            evidence_index += 1
            suffix = source.suffix.lower() or ".bin"
            relative = RelativeManifestPath(
                "reports/animation-visual-evidence/"
                f"{evidence_index:04d}-{digest[:12]}{suffix}"
            )
            staged = operation_root / relative
            _copy_new(source, staged)
            promotions.append((staged, relative, digest))
            artifact = Artifact(
                artifact_id=f"animation_visual_evidence_{evidence_index:04d}",
                role="animation_visual_evidence",
                stage="review",
                format=suffix.lstrip("."),
                path=relative,
                sha256=digest,
                size_bytes=size,
                derived_from=[library.artifact_id],
                processor=Processor(name="animation_visual_matrix_import", version="1"),
            )
            evidence_artifacts.append(artifact)
            copied.append(
                {
                    "artifact_id": artifact.artifact_id,
                    "path": str(relative),
                    "sha256": digest,
                    "size_bytes": size,
                }
            )
        cells.append(
            {
                "semantic": cell.semantic,
                "body_id": cell.body_id,
                "result": cell.result,
                "observed_phases": cell.observed_phases,
                "evidence": copied,
                "notes": cell.notes,
            }
        )
    passed = all(cell.result == "PASS" for cell in request.cells)
    report_value = {
        "schema_version": VISUAL_REPORT_SCHEMA,
        "asset_id": asset_id,
        "animation_library_sha256": library.sha256,
        "technical_report_sha256": technical.sha256,
        "selected_semantics": semantics,
        "bodies": [body.model_dump(mode="json") for body in request.bodies],
        "camera_policy": request.camera_policy,
        "camera_config_sha256": request.camera_config_sha256,
        "cells": cells,
        "reviewer": request.reviewer,
        "reviewed_at": request.reviewed_at,
        "passed": passed,
        "authority": "foundry_hash_bound_three_body_visual_review",
    }
    relative = RelativeManifestPath("reports/animation-visual-matrix-001.json")
    staged_report = operation_root / relative
    _write_new(staged_report, json_bytes(report_value))
    report = _artifact_from_source(
        staged_report,
        "animation_library_visual_matrix_report_001",
        "animation_library_visual_matrix_report",
        "review",
        "json",
        relative,
        [library.artifact_id, technical.artifact_id, *(item.artifact_id for item in evidence_artifacts)],
        Processor(name="animation_visual_matrix_import", version="1"),
    )
    manifest.artifacts.extend([*evidence_artifacts, report])
    manifest.validation.checks = [
        item for item in manifest.validation.checks if item.get("name") != "animation_library_visual_matrix"
    ] + [
        {
            "name": "animation_library_visual_matrix",
            "passed": passed,
            "report": str(relative),
            "report_sha256": report.sha256,
            "animation_library_sha256": library.sha256,
            "technical_report_sha256": technical.sha256,
            "body_count": 3,
            "cell_count": len(cells),
            "failed_cells": [
                f"{cell.semantic}/{cell.body_id}"
                for cell in request.cells
                if cell.result == "FAIL"
            ],
        }
    ]
    manifest.validation.result = "passed" if passed else "failed"
    invalidate_approval(manifest)
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    promotions.append((staged_report, relative, report.sha256))
    _promote_and_save(
        repository,
        manifest,
        asset_root,
        operation_root,
        promotions,
        "animation_library.visual_matrix_imported",
    )
    return report


def approve_animation_library(
    config: FoundryConfig,
    asset_id: str,
    reviewer: str,
    notes: str = "",
):
    """Delegate animation approval to the governing generic approval owner."""
    from vandrel_foundry.services.review_asset import approve_asset

    return approve_asset(config, asset_id, reviewer, notes)


def _load_intake_request(path: Path, asset_id: str) -> tuple[AnimationLibraryIntakeRequest, bytes]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        request = AnimationLibraryIntakeRequest.model_validate(value)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
        raise FoundryError(f"Animation intake request is invalid: {exc}") from exc
    if request.asset_id != asset_id:
        raise FoundryError("Animation intake request asset identity does not match candidate.")
    return request, json_bytes(request.model_dump(mode="json"))


def _load_visual_request(path: Path, asset_id: str) -> AnimationVisualMatrixRequest:
    try:
        request = AnimationVisualMatrixRequest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValidationError) as exc:
        raise FoundryError(f"Animation visual matrix request is invalid: {exc}") from exc
    if request.asset_id != asset_id:
        raise FoundryError("Animation visual matrix asset identity does not match candidate.")
    return request


def _membership(manifest) -> dict[str, object]:
    value = manifest.vandrel_technical.get("animation_library_membership")
    if not isinstance(value, dict) or value.get("schema_version") != "vandrel_foundry_animation_library_membership/1.0":
        raise FoundryError("Animation-library exact membership is unavailable.")
    return value


def _verify_membership_artifacts(asset_root: Path, manifest, membership: dict[str, object]) -> None:
    artifacts = {item.artifact_id: item for item in manifest.artifacts}
    selected = membership.get("selected")
    if not isinstance(selected, list) or len(selected) < 2:
        raise FoundryError("Animation-library membership is incomplete.")
    for item in selected:
        artifact = artifacts.get(item.get("source_artifact_id")) if isinstance(item, dict) else None
        if artifact is None or artifact.role != "animation_source_fbx" or artifact.sha256 != item.get("source_sha256"):
            raise FoundryError("Animation-library source binding is stale.")
        _verify_artifact(asset_root, artifact)


def _stage_animation_sandbox(asset_root: Path, sandbox: Path, membership: dict[str, object]) -> None:
    package_root = Path(__file__).resolve().parent.parent
    sandbox.mkdir(parents=True)
    (sandbox / "sources").mkdir()
    (sandbox / "output").mkdir()
    scripts = package_root / "godot"
    for name in (
        "animation_library_bone_map.tres",
        "configure_animation_library_imports.gd",
        "finalize_animation_library.gd",
        "validate_isolated_animation_library.gd",
    ):
        _copy_new(scripts / name, sandbox / name)
    selected = membership["selected"]
    runtime_request = {
        "schema_version": "vandrel_foundry_animation_library_runtime/1.0",
        "import_policy": membership["import_policy"],
        "motions": [],
    }
    for item in selected:
        source = contained_path(asset_root, RelativeManifestPath(f"source/{item['semantic']}.fbx"))
        destination = sandbox / "sources" / f"{item['semantic']}.fbx"
        _copy_new(source, destination)
        runtime_request["motions"].append(
            {
                "semantic": item["semantic"],
                "source_path": f"res://sources/{item['semantic']}.fbx",
                "source_sha256": item["source_sha256"],
                "source_size_bytes": item["source_size_bytes"],
                "loop_mode": item["loop_mode"],
            }
        )
    _write_new(sandbox / "animation-library-runtime.json", json_bytes(runtime_request))
    _write_new(
        sandbox / "project.godot",
        b'[application]\nconfig/name="Foundry Animation Library"\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n',
    )


def _validate_technical_report(
    report: object,
    membership: dict[str, object],
    library_sha: str,
    library_size: int,
) -> None:
    selected = membership["selected"]
    expected = [(item["semantic"], item["source_sha256"], item["source_size_bytes"]) for item in selected]
    if not isinstance(report, dict) or report.get("schema_version") != TECHNICAL_SCHEMA:
        raise FoundryError("Animation technical report schema is invalid.")
    if (
        report.get("passed") is not True
        or report.get("import_policy") != ANIMATION_IMPORT_POLICY
        or report.get("horizontal_root_policy") != HIPS_HORIZONTAL_POLICY
        or report.get("animation_library_sha256") != library_sha
        or report.get("animation_library_size_bytes") != library_size
    ):
        raise FoundryError("Animation technical report is failed or stale.")
    motions = report.get("motions")
    if not isinstance(motions, list) or [
        (item.get("semantic"), item.get("source_sha256"), item.get("source_size_bytes"))
        for item in motions
        if isinstance(item, dict)
    ] != expected:
        raise FoundryError("Animation technical report membership differs from intake.")
    for item in motions:
        carrier_tracks = item.get("known_carrier_tracks")
        recognized_carriers = item.get("known_carrier_track_recognized_count")
        removed_carriers = item.get("known_carrier_track_removed_count")
        if (
            item.get("passed") is not True
            or item.get("hips_position_track_count") != 1
            or item.get("mapped_rotation_track_count") != 22
            or item.get("scale_track_count") != 0
            or item.get("non_hips_position_track_count") != 0
            or item.get("other_track_count") != 0
            or item.get("finite_keys") is not True
            or item.get("hips_horizontal_transform_policy") != HIPS_HORIZONTAL_POLICY
            or item.get("hips_horizontal_transform_applied") is not True
            or item.get("hips_vertical_time_interpolation_preserved") is not True
            or not _valid_horizontal_transform_facts(item)
            or type(recognized_carriers) is not int
            or recognized_carriers not in (0, 1)
            or type(removed_carriers) is not int
            or removed_carriers != recognized_carriers
            or not isinstance(carrier_tracks, list)
            or len(carrier_tracks) != recognized_carriers
            or any(
                not isinstance(track, dict)
                or set(track)
                != {"track_index", "path", "type", "key_count", "removed"}
                or type(track.get("track_index")) is not int
                or track.get("track_index") < 0
                or track.get("path") != "Armature"
                or type(track.get("type")) is not int
                or track.get("type") != 2
                or type(track.get("key_count")) is not int
                or track.get("key_count") < 0
                or track.get("removed") is not True
                for track in carrier_tracks
            )
            or item.get("output_library_sha256") != library_sha
        ):
            raise FoundryError(f"Animation technical track contract failed: {item.get('semantic')}")


def _valid_horizontal_transform_facts(item: dict[str, object]) -> bool:
    pre = item.get("hips_horizontal_pre_transform")
    post = item.get("hips_horizontal_post_transform")
    preservation_pre = item.get("hips_preservation_pre_transform")
    preservation_post = item.get("hips_preservation_post_transform")
    if (
        not _valid_horizontal_facts(pre)
        or not _valid_horizontal_facts(post)
        or not _valid_preservation_facts(preservation_pre)
        or not _valid_preservation_facts(preservation_post)
    ):
        return False
    assert isinstance(pre, dict) and isinstance(post, dict)
    assert isinstance(preservation_pre, dict) and isinstance(preservation_post, dict)
    return (
        preservation_post == preservation_pre
        and len(preservation_pre["keys"]) == pre["key_count"]
        and len(preservation_post["keys"]) == post["key_count"]
        and post["key_count"] == pre["key_count"]
        and post["initial_offset_x"] == pre["initial_offset_x"]
        and post["initial_offset_z"] == pre["initial_offset_z"]
        and float(post["span_x"]) <= HORIZONTAL_ROOT_TOLERANCE
        and float(post["span_z"]) <= HORIZONTAL_ROOT_TOLERANCE
        and float(post["max_delta_from_first"]) <= HORIZONTAL_ROOT_TOLERANCE
    )


def _valid_horizontal_facts(value: object) -> bool:
    keys = {
        "span_x",
        "span_z",
        "max_delta_from_first",
        "initial_offset_x",
        "initial_offset_z",
        "key_count",
        "finite",
    }
    if not isinstance(value, dict) or set(value) != keys:
        return False
    if value.get("finite") is not True:
        return False
    key_count = value.get("key_count")
    if type(key_count) is not int or key_count < 1:
        return False
    numeric_keys = keys - {"key_count", "finite"}
    if any(
        isinstance(value.get(key), bool)
        or not isinstance(value.get(key), (int, float))
        or not math.isfinite(float(value[key]))
        for key in numeric_keys
    ):
        return False
    return all(float(value[key]) >= 0.0 for key in ("span_x", "span_z", "max_delta_from_first"))


def _valid_preservation_facts(value: object) -> bool:
    if (
        not isinstance(value, dict)
        or set(value)
        != {"track_interpolation_type", "track_interpolation_loop_wrap", "keys", "finite"}
        or value.get("finite") is not True
        or type(value.get("track_interpolation_type")) is not int
        or not isinstance(value.get("track_interpolation_loop_wrap"), bool)
        or not isinstance(value.get("keys"), list)
        or not value["keys"]
    ):
        return False
    for key in value["keys"]:
        if not isinstance(key, dict) or set(key) != {"y", "time", "transition"}:
            return False
        if any(
            isinstance(key.get(name), bool)
            or not isinstance(key.get(name), (int, float))
            or not math.isfinite(float(key[name]))
            for name in ("y", "time", "transition")
        ):
            return False
    return True


def _validate_monitor_report(
    report: object,
    *,
    expected_supervisor_sha256: str,
    expected_godot_sha256: str,
    expected_timeout_seconds: int,
) -> None:
    phases = [
        "initial_import",
        "configure_imports",
        "retargeted_import",
        "finalize_probe",
        "isolated_validate",
    ]
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
    }
    if (
        not isinstance(report, dict)
        or set(report) != expected_keys
        or report.get("schema_version") != MONITOR_SCHEMA
        or report.get("policy") != "vandrel_monitored_godot_animation_library_corridor_2026-08-21"
        or report.get("passed") is not True
        or report.get("process_zero_preflight") is not True
        or not isinstance(report.get("console_file_version"), str)
        or not report.get("console_file_version")
        or not isinstance(report.get("run_started_utc"), str)
        or not isinstance(report.get("run_ended_utc"), str)
        or not isinstance(report.get("console_executable_name"), str)
        or not report.get("console_executable_name", "").casefold().endswith("console.exe")
        or report.get("child_environment") != {"DOTNET_ROLL_FORWARD": "LatestMajor"}
        or report.get("internal_iteration_bomb") != 600
        or report.get("outer_timeout_seconds_per_phase") != expected_timeout_seconds
        or report.get("post_exit_poll_seconds") != 5
        or report.get("timed_out") is not False
        or report.get("output_limited") is not False
        or report.get("cleanup_failed") is not False
        or report.get("cleanup_issue") != ""
        or report.get("application_error_windows") != []
        or report.get("application_events") != []
        or report.get("has_crash_evidence") is not False
        or report.get("final_godot_processes") != []
        or report.get("wer_and_dump_paths") != []
        or report.get("supervisor_sha256") != expected_supervisor_sha256
        or report.get("godot_console_sha256") != expected_godot_sha256
        or report.get("phases") != phases
        or not isinstance(phase_results, list)
        or len(phase_results) != 5
        or [item.get("phase") for item in phase_results if isinstance(item, dict)] != phases
        or any(
            not isinstance(item, dict)
            or set(item)
            != {
                "phase",
                "started_utc",
                "ended_utc",
                "exit_code",
                "stdout_path",
                "stderr_path",
                "godot_log_path",
            }
            or item.get("exit_code") != 0
            for item in phase_results
        )
    ):
        raise FoundryError("Animation Godot monitor evidence is incomplete or failed.")


def _latest_artifact(manifest, role: str) -> Artifact:
    artifacts = [item for item in manifest.artifacts if item.role == role]
    if not artifacts:
        raise FoundryError(f"Animation-library artifact is missing: {role}")
    return artifacts[-1]


def _artifact_for_file(
    asset_root: Path,
    artifact_id: str,
    role: str,
    stage: str,
    format_name: str,
    relative: RelativeManifestPath,
    derived_from,
    processor: Processor,
) -> Artifact:
    digest, size = _hash_file(contained_path(asset_root, relative))
    return Artifact(
        artifact_id=artifact_id,
        role=role,
        stage=stage,
        format=format_name,
        path=relative,
        sha256=digest,
        size_bytes=size,
        derived_from=list(derived_from),
        processor=processor,
    )


def _artifact_from_source(
    source: Path,
    artifact_id: str,
    role: str,
    stage: str,
    format_name: str,
    relative: RelativeManifestPath,
    derived_from,
    processor: Processor,
) -> Artifact:
    digest, size = _hash_file(source)
    return Artifact(
        artifact_id=artifact_id,
        role=role,
        stage=stage,
        format=format_name,
        path=relative,
        sha256=digest,
        size_bytes=size,
        derived_from=list(derived_from),
        processor=processor,
    )


def _verify_artifact(asset_root: Path, artifact: Artifact) -> None:
    digest, size = _hash_file(contained_path(asset_root, artifact.path))
    if digest != artifact.sha256 or size != artifact.size_bytes:
        raise FoundryError(f"Animation-library artifact changed: {artifact.artifact_id}")


def _load_json(path: Path, label: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FoundryError(f"Could not read {label}: {exc}") from exc


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise FoundryError(f"Could not hash animation-library file: {exc}") from exc
    return digest.hexdigest(), size


def _copy_new(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with source.open("rb") as input_stream, destination.open("xb") as output_stream:
            shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
            output_stream.flush()
            os.fsync(output_stream.fileno())
    except OSError as exc:
        raise FoundryError(f"Could not copy animation-library artifact: {exc}") from exc


def _write_new(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise FoundryError(f"Could not write animation-library evidence: {exc}") from exc


def _new_operation_root(asset_root: Path, label: str) -> Path:
    short_label = SAFE_COMPONENT.sub("-", label).strip("-.")[:1] or "a"
    root = asset_root / ".ops" / f"{short_label}-{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=False)
    _ACTIVE_OPERATION_ROOTS.set((*_ACTIVE_OPERATION_ROOTS.get(), root))
    return root


def _promote_and_save(
    repository: ManifestRepository,
    manifest,
    asset_root: Path,
    operation_root: Path,
    promotions: list[tuple[Path, RelativeManifestPath, str]],
    event_type: str,
) -> None:
    promoted: list[tuple[Path, str]] = []
    source_revision = manifest.revision - 1
    try:
        for source, relative, expected_sha in promotions:
            destination = contained_path(asset_root, relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                raise FoundryError(f"Animation operation target already exists: {relative}")
            os.replace(source, destination)
            if _hash_file(destination)[0] != expected_sha:
                raise FoundryError(f"Promoted animation artifact changed: {relative}")
            promoted.append((destination, expected_sha))
        repository.save(
            manifest,
            event_type,
            expected_revision=source_revision,
        )
    except BaseException:
        live = repository.load(manifest.asset.asset_id)
        if (
            live.revision == manifest.revision
            and live.model_dump(mode="json") == manifest.model_dump(mode="json")
            and _references_promotions(live, promotions)
        ):
            diagnosis = repository.diagnose_pending_save(manifest.asset.asset_id)
            if diagnosis.status in {"event_missing", "event_partial", "event_complete"}:
                repository.reconcile_pending_save(manifest.asset.asset_id)
            elif diagnosis.status != "complete":
                raise FoundryError(
                    "Animation operation target manifest has no reconcilable save diagnosis."
                )
            durable = repository.load(manifest.asset.asset_id)
            if (
                durable.revision != manifest.revision
                or durable.model_dump(mode="json") != manifest.model_dump(mode="json")
                or not _references_promotions(durable, promotions)
                or repository.diagnose_pending_save(manifest.asset.asset_id).status
                != "complete"
            ):
                raise FoundryError(
                    "Animation operation target manifest did not remain durable."
                )
            for path, expected_sha in promoted:
                if not path.is_file() or _hash_file(path)[0] != expected_sha:
                    raise FoundryError(
                        "Animation operation durable manifest references changed output bytes."
                    )
            return
        if live.revision == source_revision and not _references_any_promotion(
            live, promotions
        ):
            for path, expected_sha in reversed(promoted):
                if path.is_file() and _hash_file(path)[0] == expected_sha:
                    path.unlink()
        raise
    finally:
        if operation_root.is_dir():
            shutil.rmtree(operation_root)


def _references_promotions(manifest, promotions) -> bool:
    by_path = {str(item.path): item for item in manifest.artifacts}
    return all(
        (artifact := by_path.get(str(relative))) is not None
        and artifact.sha256 == expected_sha
        for _source, relative, expected_sha in promotions
    )


def _references_any_promotion(manifest, promotions) -> bool:
    paths = {str(item.path) for item in manifest.artifacts}
    return any(str(relative) in paths for _source, relative, _expected_sha in promotions)
