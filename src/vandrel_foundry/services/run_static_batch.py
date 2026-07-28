import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image
from pydantic import ValidationError

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.batch import (
    BatchCandidate,
    BatchLedger,
    BatchPlan,
    BatchStage,
    BatchStageRecord,
    ForegroundCoverage,
)
from vandrel_foundry.domain.errors import AssetNotFoundError, FoundryError
from vandrel_foundry.domain.lanes import LaneConfiguration
from vandrel_foundry.domain.manifest import Artifact, AssetManifest
from vandrel_foundry.domain.states import next_actions
from vandrel_foundry.services.add_source import add_external_glb, add_external_package
from vandrel_foundry.services.audit_asset import audit_asset
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.inspect_glb import inspect_processed_glb
from vandrel_foundry.services.process_asset import process_passthrough
from vandrel_foundry.services.render_multi_angle_preview import render_multi_angle_preview
from vandrel_foundry.services.render_preview import render_local_preview
from vandrel_foundry.services.stage_godot import prepare_godot_sandbox
from vandrel_foundry.services.validate_godot import validate_godot_sandbox
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import contained_path

FOREGROUND_BOUNDING_BOX_MINIMUM = 0.25


def load_batch_plan(path: Path) -> BatchPlan:
    try:
        return BatchPlan.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise FoundryError(f"Could not load batch plan {path}: {exc}") from exc


def run_static_batch(
    config: FoundryConfig,
    lanes: LaneConfiguration,
    plan: BatchPlan,
    ledger_path: Path,
) -> BatchLedger:
    if ledger_path.exists():
        raise FoundryError(f"Batch ledger destination already exists: {ledger_path}")
    started = _now()
    records: list[BatchStageRecord] = []
    failed_candidates = 0
    completed_candidates = 0
    attempted_candidates: set[str] = set()
    stop = False
    for candidate in plan.candidates:
        if stop:
            break
        attempted_candidates.add(candidate.asset_id)
        candidate_failed = False
        for stage in candidate.stages:
            record = _run_stage(config, lanes, plan, candidate, stage)
            records.append(record)
            if record.result == "failed":
                candidate_failed = True
                if plan.failure_policy == "stop":
                    stop = True
                break
        if candidate_failed:
            failed_candidates += 1
        else:
            completed_candidates += 1
    ledger = BatchLedger(
        plan_schema_version=plan.schema_version,
        started_at=started,
        ended_at=_now(),
        failure_policy=plan.failure_policy,
        rerun_policy=plan.rerun_policy,
        records=records,
        planned_candidates=len(plan.candidates),
        completed_candidates=completed_candidates,
        failed_candidates=failed_candidates,
        not_run_candidates=[
            candidate.asset_id
            for candidate in plan.candidates
            if candidate.asset_id not in attempted_candidates
        ],
    )
    _write_new_json(ledger_path, ledger.model_dump(mode="json"))
    return ledger


def _run_stage(
    config: FoundryConfig,
    lanes: LaneConfiguration,
    plan: BatchPlan,
    candidate: BatchCandidate,
    stage: BatchStage,
) -> BatchStageRecord:
    repository = ManifestRepository(config.foundry.workspace_root)
    before = _load_optional(repository, candidate.asset_id)
    started_at = _now()
    started_clock = time.perf_counter()
    result = "completed"
    error_category = None
    detail = None
    coverage: list[ForegroundCoverage] = []
    try:
        completed = _stage_completed(before, candidate, stage)
        if completed and plan.rerun_policy == "fail":
            raise FoundryError(f"Stage already completed under fail rerun policy: {stage}")
        if completed:
            result = "skipped"
            detail = "already complete; existing immutable evidence retained"
        else:
            produced = _execute_stage(config, lanes, candidate, stage)
            if stage == "render-multi-angle-preview":
                after_render = repository.load(candidate.asset_id)
                coverage = _measure_multi_angle(config, after_render, produced)
    except (FoundryError, OSError, ValueError, KeyError, ValidationError) as exc:
        result = "failed"
        error_category = type(exc).__name__
        detail = str(exc)
    ended_at = _now()
    duration = time.perf_counter() - started_clock
    after = _load_optional(repository, candidate.asset_id)
    before_count, before_bytes = _artifact_totals(before)
    after_count, after_bytes = _artifact_totals(after)
    return BatchStageRecord(
        candidate=candidate.asset_id,
        stage=stage,
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=duration,
        result=result,
        error_category=error_category,
        detail=detail,
        manifest_revision_before=before.revision if before else None,
        manifest_revision_after=after.revision if after else None,
        artifact_count_delta=after_count - before_count,
        artifact_bytes_delta=after_bytes - before_bytes,
        operator_required_next_action=next_actions(after.workflow.state) if after else ["create"],
        foreground_coverage=coverage,
    )


def _execute_stage(
    config: FoundryConfig,
    lanes: LaneConfiguration,
    candidate: BatchCandidate,
    stage: BatchStage,
) -> list[Artifact]:
    if stage == "create":
        assert candidate.display_name is not None
        assert candidate.prompt_file is not None
        create_asset(
            config,
            lanes,
            candidate.asset_id,
            candidate.lane,
            candidate.display_name,
            candidate.prompt_file,
        )
        return []
    elif stage == "add-source":
        assert candidate.source is not None
        if candidate.source.suffix.lower() in {".fbx", ".gltf"}:
            add_external_package(config, candidate.asset_id, candidate.source)
        else:
            add_external_glb(config, candidate.asset_id, candidate.source)
        return []
    elif stage == "process":
        process_passthrough(config, candidate.asset_id)
        return []
    elif stage == "inspect":
        inspect_processed_glb(config, lanes, candidate.asset_id)
        return []
    elif stage == "prepare-godot":
        prepare_godot_sandbox(config, lanes, candidate.asset_id)
        return []
    elif stage == "validate-godot":
        result = validate_godot_sandbox(config, candidate.asset_id)
        if not result.passed:
            raise FoundryError("Godot sandbox validation failed; inspect its report.")
        return []
    elif stage == "render-preview":
        render_local_preview(config, candidate.asset_id)
        return []
    elif stage == "render-multi-angle-preview":
        return render_multi_angle_preview(config, candidate.asset_id)
    elif stage == "audit":
        result = audit_asset(config, candidate.asset_id)
        if not result.passed:
            raise FoundryError(f"Integrity audit failed: {candidate.asset_id}")
        return []
    raise FoundryError(f"Unsupported static batch stage: {stage}")


def _stage_completed(
    manifest: AssetManifest | None, candidate: BatchCandidate, stage: BatchStage
) -> bool:
    if stage == "create":
        return (
            manifest is not None
            and manifest.asset.lane == candidate.lane
            and (
                candidate.display_name is None
                or manifest.asset.display_name == candidate.display_name
            )
        )
    if manifest is None:
        return False
    artifacts = manifest.artifacts
    source = _current_source(manifest)
    processed = _current_processed(manifest)
    if stage == "add-source":
        return source is not None and _source_matches_plan(manifest, candidate)
    if stage == "process":
        return (
            processed is not None
            and source is not None
            and source.artifact_id in processed.derived_from
        )
    if stage == "inspect":
        return processed is not None and (
            manifest.quality.observed.get("inspected_processed_artifact_id")
            == processed.artifact_id
            and manifest.quality.observed.get("inspected_processed_sha256") == processed.sha256
        )
    if stage == "prepare-godot":
        return processed is not None and any(
            item.role == "godot_staged_model" and processed.artifact_id in item.derived_from
            for item in artifacts
        )
    if stage == "validate-godot":
        current_staged = [
            item
            for item in artifacts
            if item.role == "godot_staged_model"
            and processed is not None
            and processed.artifact_id in item.derived_from
        ]
        current_wrappers = [
            item
            for item in artifacts
            if item.role == "godot_wrapper_scene"
            and current_staged
            and current_staged[-1].artifact_id in item.derived_from
        ]
        current_projects = [
            item
            for item in artifacts
            if item.role == "godot_validation_project"
            and current_wrappers
            and current_wrappers[-1].artifact_id in item.derived_from
        ]
        return bool(current_projects) and any(
            item.role == "godot_validation_report"
            and current_projects[-1].artifact_id in item.derived_from
            for item in artifacts
        )
    if stage == "render-preview":
        return processed is not None and any(
            item.role == "local_preview" and processed.artifact_id in item.derived_from
            for item in artifacts
        )
    if stage == "render-multi-angle-preview":
        return (
            processed is not None
            and len(
                [
                    item
                    for item in artifacts
                    if item.role == "multi_angle_preview"
                    and processed.artifact_id in item.derived_from
                ]
            )
            >= 4
        )
    return False


def _current_source(manifest: AssetManifest) -> Artifact | None:
    selected = manifest.generation.selected_task_key
    candidates = [
        item
        for item in manifest.artifacts
        if item.role == "source_model" and (selected is None or item.source_task_key == selected)
    ]
    return candidates[-1] if candidates else None


def _source_matches_plan(manifest: AssetManifest, candidate: BatchCandidate) -> bool:
    source_path = candidate.source
    if source_path is None or not source_path.is_file():
        return False
    digest = hashlib.sha256()
    with source_path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    role = (
        "external_source_model"
        if source_path.suffix.lower() in {".fbx", ".gltf"}
        else "source_model"
    )
    return any(
        item.role == role and item.sha256 == digest.hexdigest() for item in manifest.artifacts
    )


def _current_processed(manifest: AssetManifest) -> Artifact | None:
    source = _current_source(manifest)
    if source is None:
        return None
    candidates = [
        item
        for item in manifest.artifacts
        if item.role == "processed_model" and source.artifact_id in item.derived_from
    ]
    return candidates[-1] if candidates else None


def _measure_multi_angle(
    config: FoundryConfig, manifest: AssetManifest, produced: list[Artifact]
) -> list[ForegroundCoverage]:
    images = [item for item in produced if item.role == "multi_angle_preview"]
    if len(images) != 4:
        raise FoundryError("Multi-angle renderer did not return exactly four image artifacts.")
    asset_root = config.foundry.workspace_root / "assets" / manifest.asset.asset_id
    measurements = []
    for artifact in images:
        path = contained_path(asset_root, artifact.path)
        with Image.open(path) as opened:
            image = opened.convert("RGBA")
            alpha = image.getchannel("A")
            bounds = alpha.getbbox()
            width, height = image.size
            foreground = sum(alpha.histogram()[1:])
        box_area = 0 if bounds is None else (bounds[2] - bounds[0]) * (bounds[3] - bounds[1])
        fraction = box_area / (width * height)
        measurements.append(
            ForegroundCoverage(
                artifact_id=artifact.artifact_id,
                path=str(artifact.path),
                width=width,
                height=height,
                bounding_box_fraction=fraction,
                nonzero_alpha_pixel_fraction=foreground / (width * height),
                excessive_empty_canvas=fraction < FOREGROUND_BOUNDING_BOX_MINIMUM,
            )
        )
    return measurements


def _load_optional(repository: ManifestRepository, asset_id: str) -> AssetManifest | None:
    try:
        return repository.load(asset_id)
    except AssetNotFoundError:
        return None


def _artifact_totals(manifest: AssetManifest | None) -> tuple[int, int]:
    if manifest is None:
        return 0, 0
    return len(manifest.artifacts), sum(item.size_bytes for item in manifest.artifacts)


def _now() -> datetime:
    return datetime.now(UTC)


def _write_new_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        path.unlink(missing_ok=True)
        raise FoundryError(f"Could not write batch ledger {path}: {exc}") from exc
