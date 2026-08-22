"""Import explicit, hash-bound manual review for clean-body capture cells."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from pydantic import ValidationError

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.clean_meshy_body import CleanBodyVisualReviewRequest
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.domain.workflow_policy import invalidate_approval, transition_workflow
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path

PROCESSOR = Processor(name="manual_clean_meshy_body_visual_review", version="1")


def import_clean_meshy_body_visual_review(config: FoundryConfig, asset_id: str, request_path: Path) -> list[Artifact]:
    try: request = CleanBodyVisualReviewRequest.model_validate_json(request_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError) as exc: raise FoundryError(f"Invalid clean-body visual review: {exc}") from exc
    if request.asset_id != asset_id: raise FoundryError("Clean-body visual review targets another asset.")
    repository = ManifestRepository(config.foundry.workspace_root); manifest = repository.load(asset_id)
    if manifest.workflow.state is not WorkflowState.REVIEW: raise FoundryError("Clean-body visual import requires review state.")
    model = _latest(manifest.artifacts, "processed_model"); technical = _latest(manifest.artifacts, "clean_body_technical_report"); monitor = _latest(manifest.artifacts, "clean_body_godot_monitor_report")
    if (request.processed_body_sha256, request.technical_report_sha256, request.monitor_report_sha256) != (model.sha256, technical.sha256, monitor.sha256): raise FoundryError("Clean-body review bindings are stale.")
    technical_check = next((item for item in manifest.validation.checks if item.get("name") == "clean_body_technical_probe"), None)
    if technical_check is None or technical_check.get("shared_animation_library_sha256") != request.shared_animation_library_sha256: raise FoundryError("Clean-body review shared-library binding is stale.")
    expected_semantics = json.loads(contained_path(repository.asset_directory(asset_id), technical.path).read_text())["shared_semantics"]
    if sorted(item.semantic for item in request.motion_cells) != sorted(expected_semantics): raise FoundryError("Clean-body review does not cover exact shared-library semantics.")
    asset_root = repository.asset_directory(asset_id); reviews = asset_root / "reviews"; reviews.mkdir(exist_ok=True)
    destination = reviews / "clean_body_visual_001"
    cells = [*request.rest_cells, *request.motion_cells]
    captured = [item for item in manifest.artifacts if item.role == "clean_body_capture_evidence"]
    if [(cell.evidence.sha256, cell.evidence.size_bytes) for cell in cells] != [(item.sha256, item.size_bytes) for item in captured]:
        raise FoundryError("Clean-body manual review is not bound to the exact captured cells.")
    operation = Path(tempfile.mkdtemp(prefix=".clean-body-review-", dir=reviews))
    try:
        for index, cell in enumerate(cells, start=1):
            source = Path(cell.evidence.path); source = source if source.is_absolute() else request_path.parent / source
            if _hash(source) != (cell.evidence.sha256, cell.evidence.size_bytes): raise FoundryError("Clean-body visual evidence bytes differ from review request.")
            shutil.copyfile(source, operation / f"cell-{index:03d}{source.suffix.casefold()}")
        report = request.model_dump(mode="json"); report["result"] = "PASS" if all(cell.result == "PASS" for cell in cells) else "FAIL"; report["failed_cells"] = [getattr(cell, "view", getattr(cell, "semantic", "unknown")) for cell in cells if cell.result == "FAIL"]
        (operation / "review.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        if destination.exists(): raise FoundryError("Clean-body visual review destination already exists.")
        os.replace(operation, destination)
    except BaseException:
        if operation.exists(): shutil.rmtree(operation)
        raise
    artifacts: list[Artifact] = []
    for index, cell in enumerate(cells, start=1):
        source = Path(cell.evidence.path); name = f"cell-{index:03d}{source.suffix.casefold()}"
        digest, size = _hash(destination / name)
        artifacts.append(Artifact(artifact_id=f"clean_body_visual_evidence_{index:03d}", role="clean_body_visual_evidence", stage="review", format=source.suffix.removeprefix(".").casefold(), path=RelativeManifestPath(f"reviews/clean_body_visual_001/{name}"), sha256=digest, size_bytes=size, derived_from=[model.artifact_id], processor=PROCESSOR))
    digest, size = _hash(destination / "review.json")
    report_artifact = Artifact(artifact_id="clean_body_visual_review_report_001", role="clean_body_visual_review_report", stage="review", format="json", path=RelativeManifestPath("reviews/clean_body_visual_001/review.json"), sha256=digest, size_bytes=size, derived_from=[item.artifact_id for item in artifacts], processor=PROCESSOR)
    artifacts.append(report_artifact); revision = manifest.revision; manifest.artifacts.extend(artifacts)
    failed = [getattr(cell, "view", getattr(cell, "semantic", "unknown")) for cell in cells if cell.result == "FAIL"]
    manifest.validation.result = "passed" if not failed else "failed"
    manifest.validation.checks = [item for item in manifest.validation.checks if item.get("name") != "clean_body_visual_review"] + [{"name":"clean_body_visual_review","passed":not failed,"processed_body_sha256":model.sha256,"technical_report_sha256":technical.sha256,"monitor_report_sha256":monitor.sha256,"shared_animation_library_sha256":request.shared_animation_library_sha256,"report_sha256":report_artifact.sha256,"failed_cells":failed}]
    transition_workflow(manifest, WorkflowState.REVIEW); invalidate_approval(manifest); manifest.revision += 1; manifest.asset.updated_at = utc_now()
    try:
        repository.save(manifest, "asset.clean_body_visual_review_imported", expected_revision=revision)
    except BaseException:
        live = repository.load(asset_id)
        if live.revision == manifest.revision and _references(live.artifacts, artifacts):
            return artifacts
        if live.revision == revision and not _references(live.artifacts, artifacts):
            shutil.rmtree(destination)
        raise
    return artifacts


def _latest(artifacts: list[Artifact], role: str) -> Artifact:
    values=[item for item in artifacts if item.role==role]
    if not values: raise FoundryError(f"Clean-body artifact role is missing: {role}")
    return values[-1]


def _hash(path: Path) -> tuple[str,int]:
    digest=hashlib.sha256(); size=0
    with path.open("rb") as stream:
        while chunk:=stream.read(1024*1024): digest.update(chunk); size+=len(chunk)
    return digest.hexdigest(),size


def _references(live: list[Artifact], targets: list[Artifact]) -> bool:
    expected={(item.artifact_id,item.sha256,item.size_bytes) for item in targets}
    actual={(item.artifact_id,item.sha256,item.size_bytes) for item in live}
    return expected.issubset(actual)
