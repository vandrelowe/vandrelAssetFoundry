import hashlib
import json
import os
import shutil
from pathlib import Path

from PIL import Image

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.validate_godot import ProcessRunner, run_bounded_process
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path

REQUIRED_FAMILIES = {"idle", "eating", "walk", "gallop", "jump", "hit", "attack", "death"}


def render_creature_playback(
    config: FoundryConfig, asset_id: str, runner: ProcessRunner | None = None
) -> Artifact:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.asset.lane != "creature" or manifest.workflow.state not in {
        WorkflowState.PROCESSED, WorkflowState.REVIEW,
    }:
        raise FoundryError("Creature playback requires a processed creature candidate.")
    models = [item for item in manifest.artifacts if item.role == "processed_model"]
    if not models:
        raise FoundryError("Creature playback requires a processed model.")
    model = models[-1]; asset_root = repository.asset_directory(asset_id)
    if model.processor is None or model.processor.name != "blender_compound_creature_derivation":
        raise FoundryError(
            "Creature playback requires the current compound-creature derivation model."
        )
    model_path = contained_path(asset_root, model.path); _verify(model_path, model)
    executable = config.tools.blender_executable
    if executable is None or not executable.is_file() or not executable.is_absolute():
        raise FoundryError("Configure an absolute Blender executable for creature playback.")
    number = sum(item.role == "creature_playback_report" for item in manifest.artifacts) + 1
    directory_relative = RelativeManifestPath(f"preview/creature-playback-{number:03d}")
    report_relative = RelativeManifestPath(f"reports/creature-playback-{number:03d}.json")
    directory = contained_path(asset_root, directory_relative)
    report_path = contained_path(asset_root, report_relative)
    if directory.exists() or report_path.exists():
        raise FoundryError("Creature playback evidence destination already exists.")
    script = Path(__file__).parents[1] / "blender" / "render_creature_playback.py"
    arguments = [str(executable), "--background", "--factory-startup", "--disable-autoexec",
                 "--python-exit-code", "1", "--python", str(script), "--",
                 str(model_path), str(directory), str(report_path)]
    try:
        result = (runner or run_bounded_process)(arguments, asset_root, _environment(),
            config.tools.blender_timeout_seconds, config.tools.maximum_output_bytes)
        if result.return_code != 0 or result.timed_out or result.output_limited:
            detail = (result.stderr or result.stdout or "no tool diagnostic").strip()[-2000:]
            raise FoundryError(
                f"Bounded continuous creature playback rendering failed: {detail}"
            )
        data = json.loads(report_path.read_text(encoding="utf-8"))
        clips = data.get("clips")
        if data.get("schema") != "vandrel_foundry_creature_playback/1.0" or not isinstance(clips, list):
            raise FoundryError("Creature playback report schema is invalid.")
        families = {item.get("family") for item in clips if isinstance(item, dict)}
        if not REQUIRED_FAMILIES.issubset(families):
            raise FoundryError(f"Creature playback is missing clip families: {sorted(REQUIRED_FAMILIES - families)}")
        video_artifacts = []
        for index, clip in enumerate(clips, start=1):
            filename = clip.get("video") if isinstance(clip, dict) else None
            if not isinstance(filename, str) or Path(filename).name != filename:
                raise FoundryError("Creature playback report has an unsafe video path.")
            frames = clip.get("frame_files") if isinstance(clip, dict) else None
            if not isinstance(frames, list) or len(frames) < 2:
                raise FoundryError("Creature playback clip has no continuous frame sequence.")
            frame_paths = [directory / str(value) for value in frames]
            if any(path.suffix.lower() != ".png" or directory not in path.parents for path in frame_paths):
                raise FoundryError("Creature playback frame path is unsafe.")
            images = [Image.open(path).convert("RGB") for path in frame_paths]
            path = directory / filename
            try:
                images[0].save(path, format="WEBP", save_all=True, append_images=images[1:],
                    duration=int(clip.get("frame_duration_ms", 33)), loop=0, quality=82)
            finally:
                for image in images: image.close()
            for frame_path in frame_paths: frame_path.unlink()
            for frame_directory in {path.parent for path in frame_paths}: frame_directory.rmdir()
            digest, size = _hash(path)
            if size <= 0:
                raise FoundryError("Creature playback video is empty.")
            clip["video_sha256"] = digest; clip["video_size_bytes"] = size
            video_artifacts.append(Artifact(
                artifact_id=f"creature_playback_video_{number:03d}_{index:03d}",
                role="creature_playback_video", stage="review", format="webp",
                path=RelativeManifestPath(f"{directory_relative}/{filename}"), sha256=digest,
                size_bytes=size, derived_from=[model.artifact_id],
                processor=Processor(name="blender_creature_playback", version="1"),
            ))
        data["processed_model_sha256"] = model.sha256
        report_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        report_hash, report_size = _hash(report_path)
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True); report_path.unlink(missing_ok=True); raise
    report_artifact = Artifact(
        artifact_id=f"creature_playback_report_{number:03d}", role="creature_playback_report",
        stage="review", format="json", path=report_relative, sha256=report_hash,
        size_bytes=report_size,
        derived_from=[model.artifact_id, *(item.artifact_id for item in video_artifacts)],
        processor=Processor(name="blender_creature_playback", version="1"),
    )
    target_artifacts = [*video_artifacts, report_artifact]
    source_revision = manifest.revision
    manifest.artifacts.extend(target_artifacts)
    manifest.validation.checks = [item for item in manifest.validation.checks if item.get("name") != "creature_continuous_playback"]
    manifest.validation.checks.append({
        "name": "creature_continuous_playback", "passed": True,
        "processed_model_sha256": model.sha256, "report": str(report_relative),
        "clip_count": len(clips), "clip_families": sorted(families),
    })
    manifest.revision += 1; manifest.asset.updated_at = utc_now()
    try:
        repository.save(
            manifest,
            "creature.playback_rendered",
            expected_revision=manifest.revision - 1,
        )
    except BaseException:
        live = repository.load(asset_id)
        if _is_exact_target(live, manifest.revision, target_artifacts):
            diagnosis = repository.diagnose_pending_save(asset_id)
            if diagnosis.status in {"event_missing", "event_partial", "event_complete"}:
                repository.reconcile_pending_save(asset_id)
            return report_artifact
        if live.revision == source_revision and not _references(live, target_artifacts):
            shutil.rmtree(directory, ignore_errors=True)
            report_path.unlink(missing_ok=True)
        raise
    return report_artifact


def _verify(path: Path, artifact: Artifact) -> None:
    digest, size = _hash(path)
    if (digest, size) != (artifact.sha256, artifact.size_bytes):
        raise FoundryError("Creature playback input changed.")


def _hash(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256(); size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024): digest.update(chunk); size += len(chunk)
    return digest.hexdigest(), size


def _environment() -> dict[str, str]:
    allowed = {"APPDATA", "HOME", "LOCALAPPDATA", "PATH", "SYSTEMDRIVE", "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE", "WINDIR"}
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


def _is_exact_target(manifest, revision: int, artifacts: list[Artifact]) -> bool:
    return manifest.revision == revision and _references(manifest, artifacts)


def _references(manifest, artifacts: list[Artifact]) -> bool:
    by_id = {item.artifact_id: item for item in manifest.artifacts}
    return all(
        by_id.get(expected.artifact_id) is not None
        and by_id[expected.artifact_id].model_dump(mode="json")
        == expected.model_dump(mode="json")
        for expected in artifacts
    )
