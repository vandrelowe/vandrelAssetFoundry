import hashlib
import json
import os

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path

ALLOWED_STATES = {
    WorkflowState.PROCESSED,
    WorkflowState.REVIEW,
    WorkflowState.APPROVED,
}


def accept_animation_samples(
    config: FoundryConfig,
    asset_id: str,
    reviewer: str,
    notes: str,
) -> Artifact:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.workflow.state not in ALLOWED_STATES:
        raise FoundryError(
            "Animation visual review requires the processed, review, or approved state."
        )
    reviewer = reviewer.strip()
    notes = notes.strip()
    if not reviewer or not notes:
        raise FoundryError("Animation visual review requires reviewer and notes.")
    models = [item for item in manifest.artifacts if item.role == "processed_model"]
    sheets = [
        item
        for item in manifest.artifacts
        if item.role == "animation_sample_contact_sheet"
    ]
    reports = [
        item for item in manifest.artifacts if item.role == "animation_sample_report"
    ]
    if not models or not sheets or not reports:
        raise FoundryError("Animation visual review evidence is incomplete.")
    model = models[-1]
    sheet = sheets[-1]
    report = reports[-1]
    if model.artifact_id not in sheet.derived_from:
        raise FoundryError("Animation sample sheet is stale for the current processed model.")
    if model.artifact_id not in report.derived_from:
        raise FoundryError("Animation sample report is stale for the current processed model.")
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    for artifact in (model, sheet, report):
        _verify_artifact(asset_root, artifact)

    number = (
        sum(item.role == "animation_visual_review" for item in manifest.artifacts) + 1
    )
    relative = RelativeManifestPath(f"reports/animation-visual-review-{number:03d}.json")
    path = contained_path(asset_root, relative)
    evidence = {
        "schema_version": 1,
        "asset_id": asset_id,
        "accepted": True,
        "reviewer": reviewer,
        "reviewed_at": utc_now().isoformat(),
        "notes": notes,
        "processed_model": _binding(model),
        "animation_sample_contact_sheet": _binding(sheet),
        "animation_sample_report": _binding(report),
        "review_scope": [
            "gross deformation",
            "limb orientation",
            "root displacement",
            "foot contact",
        ],
        "authority": {
            "result_is": "Foundry visual acceptance of the baked candidate samples",
            "result_is_not": "Vandrel clip semantics or runtime animation acceptance",
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_new_json(path, evidence)
    digest, size = _hash_file(path)
    processor = Processor(name="animation_visual_review", version="1")
    artifact = Artifact(
        artifact_id=f"animation_visual_review_{number:03d}",
        role="animation_visual_review",
        stage="review",
        format="json",
        path=relative,
        sha256=digest,
        size_bytes=size,
        derived_from=[model.artifact_id, sheet.artifact_id, report.artifact_id],
        processor=processor,
    )
    manifest.artifacts.append(artifact)
    check = {
        "name": "animation_visual_review",
        "passed": True,
        "report": str(relative),
        "processed_model_sha256": model.sha256,
        "contact_sheet_sha256": sheet.sha256,
        "reviewer": reviewer,
    }
    manifest.validation.checks = [
        item
        for item in manifest.validation.checks
        if item.get("name") != "animation_visual_review"
    ]
    manifest.validation.checks.append(check)
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    repository.save(
        manifest,
        "asset.animation_samples_accepted",
        expected_revision=manifest.revision - 1,
    )
    return artifact


def _binding(artifact: Artifact) -> dict[str, object]:
    return {
        "artifact_id": artifact.artifact_id,
        "path": str(artifact.path),
        "sha256": artifact.sha256,
        "size_bytes": artifact.size_bytes,
    }


def _verify_artifact(asset_root, artifact: Artifact) -> None:
    path = contained_path(asset_root, artifact.path)
    digest, size = _hash_file(path)
    if digest != artifact.sha256 or size != artifact.size_bytes:
        raise FoundryError(f"Animation review artifact changed: {artifact.artifact_id}")


def _hash_file(path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _write_new_json(path, value: dict) -> None:
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise FoundryError(f"Could not write animation visual review: {exc}") from exc
