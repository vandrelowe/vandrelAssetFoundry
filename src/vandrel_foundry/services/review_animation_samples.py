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
    sheets = [item for item in manifest.artifacts if item.role == "animation_sample_contact_sheet"]
    reports = [item for item in manifest.artifacts if item.role == "animation_sample_report"]
    playback_reports = [
        item for item in manifest.artifacts if item.role == "creature_playback_report"
    ]
    playback_videos = [
        item for item in manifest.artifacts if item.role == "creature_playback_video"
    ]
    creature_review = manifest.asset.lane == "creature"
    if not models or (creature_review and (not playback_reports or not playback_videos)) or (
        not creature_review and (not sheets or not reports)
    ):
        raise FoundryError("Animation visual review evidence is incomplete.")
    model = models[-1]
    sheet = None if creature_review else sheets[-1]
    report = playback_reports[-1] if creature_review else reports[-1]
    if sheet is not None and model.artifact_id not in sheet.derived_from:
        raise FoundryError("Animation sample sheet is stale for the current processed model.")
    if model.artifact_id not in report.derived_from:
        raise FoundryError("Animation sample report is stale for the current processed model.")
    reviewed_videos = []
    if creature_review:
        video_ids = set(report.derived_from) - {model.artifact_id}
        reviewed_videos = [item for item in playback_videos if item.artifact_id in video_ids]
        if not video_ids or {item.artifact_id for item in reviewed_videos} != video_ids:
            raise FoundryError("Creature playback report does not bind its complete video set.")
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    for artifact in (model, report, *reviewed_videos, *((sheet,) if sheet else ())):
        _verify_artifact(asset_root, artifact)

    number = sum(item.role == "animation_visual_review" for item in manifest.artifacts) + 1
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
        "animation_sample_contact_sheet": _binding(sheet) if sheet else None,
        "animation_sample_report": _binding(report) if not creature_review else None,
        "creature_continuous_playback_report": (
            _binding(report) if creature_review else None
        ),
        "creature_continuous_playback_videos": [
            _binding(item) for item in reviewed_videos
        ],
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
        derived_from=[
            model.artifact_id,
            report.artifact_id,
            *(item.artifact_id for item in reviewed_videos),
            *((sheet.artifact_id,) if sheet else ()),
        ],
        processor=processor,
    )
    manifest.artifacts.append(artifact)
    check = {
        "name": "animation_visual_review",
        "passed": True,
        "report": str(relative),
        "processed_model_sha256": model.sha256,
        "contact_sheet_sha256": sheet.sha256 if sheet else None,
        "continuous_playback_report_sha256": report.sha256 if creature_review else None,
        "continuous_playback_clip_count": len(reviewed_videos) if creature_review else None,
        "reviewer": reviewer,
    }
    manifest.validation.checks = [
        item for item in manifest.validation.checks if item.get("name") != "animation_visual_review"
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
