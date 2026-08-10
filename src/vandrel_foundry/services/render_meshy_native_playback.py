import hashlib
import json
import os
import re
import shutil
import struct
import tempfile
from pathlib import Path

from PIL import Image

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.normalize_meshy_native_animations import PROCESSOR_NAME
from vandrel_foundry.services.validate_godot import ProcessRunner, run_bounded_process
from vandrel_foundry.services.windows_acl_policy import apply_candidate_acl
from vandrel_foundry.storage.atomic import json_bytes
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path

PLAYBACK_PROCESSOR = "blender_meshy_native_playback"
PLAYBACK_VERSION = "2"
DURATION_TOLERANCE_SECONDS = 0.002


def render_meshy_native_playback(
    config: FoundryConfig,
    asset_id: str,
    runner: ProcessRunner | None = None,
) -> Artifact:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.asset.lane != "humanoid" or manifest.workflow.state is not WorkflowState.PROCESSED:
        raise FoundryError("Meshy native playback requires a processed humanoid canary.")
    models = [item for item in manifest.artifacts if item.role == "processed_model"]
    if not models or models[-1].processor is None or models[-1].processor.name != PROCESSOR_NAME:
        raise FoundryError("Meshy native playback requires the current native-normalization model.")
    model = models[-1]
    reports = [
        item
        for item in manifest.artifacts
        if item.role == "meshy_native_canary_report" and model.artifact_id in item.derived_from
    ]
    if not reports:
        raise FoundryError("Meshy native playback requires the hash-bound normalization report.")
    normalization_report = reports[-1]
    asset_root = repository.asset_directory(asset_id)
    model_path = contained_path(asset_root, model.path)
    normalization_path = contained_path(asset_root, normalization_report.path)
    _verify(model_path, model)
    _verify(normalization_path, normalization_report)
    normalized = json.loads(normalization_path.read_text(encoding="utf-8"))
    normalized_clips = normalized.get("clips")
    if not isinstance(normalized_clips, list) or len(normalized_clips) != 10:
        raise FoundryError("Meshy native normalization report has an invalid action set.")
    expected_durations: dict[str, float] = {}
    for item in normalized_clips:
        if not isinstance(item, dict):
            raise FoundryError("Meshy native normalization clip is invalid.")
        name = item.get("exact_name")
        duration = item.get("duration_seconds")
        if (
            not isinstance(name, str)
            or not name
            or isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or float(duration) <= 0
            or name in expected_durations
        ):
            raise FoundryError("Meshy native normalization clip duration is invalid.")
        expected_durations[name] = float(duration)
    expected_names = list(expected_durations)

    executable = config.tools.blender_executable
    if executable is None or not executable.is_absolute() or not executable.is_file():
        raise FoundryError("Configure tools.blender_executable as an existing absolute file.")
    number = sum(item.role == "meshy_native_playback_report" for item in manifest.artifacts) + 1
    directory_relative = RelativeManifestPath(f"preview/meshy-native-playback-{number:03d}")
    report_relative = RelativeManifestPath(f"reports/meshy-native-playback-{number:03d}.json")
    process_relative = RelativeManifestPath(
        f"reports/meshy-native-playback-{number:03d}.process.json"
    )
    directory = contained_path(asset_root, directory_relative)
    report_path = contained_path(asset_root, report_relative)
    process_path = contained_path(asset_root, process_relative)
    if directory.exists() or report_path.exists() or process_path.exists():
        raise FoundryError("Meshy native playback destination already exists.")

    temporary_root: Path | None = None
    promoted: list[Path] = []
    rollback_promoted = True
    try:
        temporary_root = Path(tempfile.mkdtemp(prefix=".meshy-native-playback-", dir=asset_root))
        apply_candidate_acl(config, temporary_root)
        temporary_frames = temporary_root / "frames"
        adapter_report = temporary_root / "adapter-report.json"
        expected_path = temporary_root / "expected-durations.json"
        temporary_videos = temporary_root / "videos"
        temporary_videos.mkdir()
        temporary_process = temporary_root / "process.json"
        temporary_report = temporary_root / "report.json"
        _write_new(expected_path, json_bytes(expected_durations))
        script = Path(__file__).parents[1] / "blender" / "render_meshy_native_playback.py"
        arguments = [
            str(executable),
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "--python-exit-code",
            "1",
            "--python",
            str(script),
            "--",
            str(model_path),
            str(temporary_frames),
            str(adapter_report),
            str(expected_path),
        ]
        logical_arguments = [
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "--python-exit-code=1",
            f"--model-artifact={model.artifact_id}",
            f"--normalization-report-artifact={normalization_report.artifact_id}",
            f"--output-role=meshy_native_playback_video:{directory_relative}",
            f"--report-role=meshy_native_playback_report:{report_relative}",
            f"--process-log-role=meshy_native_playback_process_log:{process_relative}",
        ]
        started_at = utc_now().isoformat()
        result = (runner or run_bounded_process)(
            arguments,
            asset_root,
            _safe_environment(),
            config.tools.blender_timeout_seconds,
            config.tools.maximum_output_bytes,
        )
        ended_at = utc_now().isoformat()
        if result.return_code != 0 or result.timed_out or result.output_limited:
            detail = (result.stderr or result.stdout or "no tool diagnostic").strip()[-2000:]
            raise FoundryError(f"Bounded Meshy native playback failed: {detail}")
        _verify(model_path, model)
        _verify(normalization_path, normalization_report)
        if not adapter_report.is_file() or not temporary_frames.is_dir():
            raise FoundryError("Meshy native playback adapter did not create its required outputs.")
        data = json.loads(adapter_report.read_text(encoding="utf-8"))
        clips = data.get("clips")
        if (
            data.get("schema") != "vandrel_foundry_meshy_native_playback/1.0"
            or data.get("continuous_temporal_output") is not True
            or not isinstance(clips, list)
            or len(clips) != 10
            or [item.get("exact_name") for item in clips if isinstance(item, dict)]
            != expected_names
        ):
            raise FoundryError("Meshy native playback report does not match all exact actions.")

        process_value = {
            "schema": "vandrel_foundry_bounded_process/1.0",
            "processor_name": PLAYBACK_PROCESSOR,
            "processor_version": PLAYBACK_VERSION,
            "tool_version": str(data.get("blender_version")),
            "logical_arguments": logical_arguments,
            "return_code": result.return_code,
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_seconds": result.duration_seconds,
            "timeout_seconds": config.tools.blender_timeout_seconds,
            "maximum_output_bytes": config.tools.maximum_output_bytes,
            "timed_out": result.timed_out,
            "output_limited": result.output_limited,
            "stdout": _portable_process_text(
                result.stdout, executable, script, asset_root, temporary_root
            ),
            "stderr": _portable_process_text(
                result.stderr, executable, script, asset_root, temporary_root
            ),
        }
        _write_new(temporary_process, json_bytes(process_value))
        process_hash, process_size = _hash_file(temporary_process)
        processor = Processor(name=PLAYBACK_PROCESSOR, version=PLAYBACK_VERSION)
        video_artifacts: list[Artifact] = []
        video_bindings: list[tuple[Path, Path]] = []
        for index, clip in enumerate(clips, start=1):
            if not isinstance(clip, dict):
                raise FoundryError("Meshy native playback clip evidence is invalid.")
            name = clip.get("exact_name")
            frames = clip.get("frame_files")
            if not isinstance(name, str) or not isinstance(frames, list) or len(frames) < 2:
                raise FoundryError("Meshy native playback clip evidence is incomplete.")
            bound_duration = expected_durations[name]
            adapter_duration = clip.get("source_duration_seconds")
            bound_adapter_duration = clip.get("bound_normalization_duration_seconds")
            if (
                isinstance(adapter_duration, bool)
                or not isinstance(adapter_duration, (int, float))
                or isinstance(bound_adapter_duration, bool)
                or not isinstance(bound_adapter_duration, (int, float))
                or abs(float(adapter_duration) - bound_duration) > DURATION_TOLERANCE_SECONDS
                or abs(float(bound_adapter_duration) - bound_duration)
                > DURATION_TOLERANCE_SECONDS
            ):
                raise FoundryError(f"Meshy native playback duration changed: {name}")
            frame_paths = []
            for value in frames:
                if not isinstance(value, str):
                    raise FoundryError("Meshy native playback frame path is invalid.")
                relative = RelativeManifestPath(value)
                path = contained_path(temporary_frames, relative)
                if path.suffix.lower() != ".png" or not path.is_file():
                    raise FoundryError("Meshy native playback frame path is unsafe.")
                frame_paths.append(path)
            images = [Image.open(path).convert("RGB") for path in frame_paths]
            filename = f"{index:02d}-{_slug(name)}.webp"
            temporary_video = temporary_videos / filename
            durations_ms = _distributed_durations_ms(bound_duration, len(images))
            try:
                images[0].save(
                    temporary_video,
                    format="WEBP",
                    save_all=True,
                    append_images=images[1:],
                    duration=durations_ms,
                    loop=0,
                    lossless=True,
                    quality=82,
                )
            finally:
                for image in images:
                    image.close()
            encoded_duration = _webp_duration_seconds(temporary_video)
            if abs(encoded_duration - bound_duration) > DURATION_TOLERANCE_SECONDS:
                raise FoundryError(f"Encoded Meshy native playback duration changed: {name}")
            digest, size = _hash_file(temporary_video)
            artifact = Artifact(
                artifact_id=f"meshy_native_playback_video_{number:03d}_{index:03d}",
                role="meshy_native_playback_video",
                stage="review",
                format="webp",
                path=RelativeManifestPath(f"{directory_relative}/{filename}"),
                sha256=digest,
                size_bytes=size,
                derived_from=[model.artifact_id, normalization_report.artifact_id],
                processor=processor,
            )
            video_artifacts.append(artifact)
            video_bindings.append((temporary_video, contained_path(asset_root, artifact.path)))
            clip.pop("frame_files", None)
            clip.pop("video", None)
            clip.pop("frame_duration_ms", None)
            clip["bound_normalization_duration_seconds"] = bound_duration
            clip["encoded_playback_duration_seconds"] = encoded_duration
            clip["duration_tolerance_seconds"] = DURATION_TOLERANCE_SECONDS
            clip["evidence_file"] = {
                "artifact_id": artifact.artifact_id,
                "path": str(artifact.path),
                "sha256": artifact.sha256,
                "size_bytes": artifact.size_bytes,
                "format": "webp",
            }

        data["processed_model_sha256"] = model.sha256
        data["normalization_report_sha256"] = normalization_report.sha256
        data["process"] = {
            key: value for key, value in process_value.items() if key not in {"stdout", "stderr"}
        }
        data["process_log"] = {
            "artifact_id": f"meshy_native_playback_process_log_{number:03d}",
            "path": str(process_relative),
            "sha256": process_hash,
            "size_bytes": process_size,
        }
        data["visual_acceptance"] = False
        data["semantic_decision"] = {
            "eating": (
                "No provider-resolved eating or chewing action is established by this package; "
                "the exact UUID action names remain unresolved."
            ),
            "butchery": (
                "No provider-resolved kneeling cutting or dressing action is established by "
                "this package; the exact UUID action names remain unresolved."
            ),
            "locomotion": "Running and Walking retain their normalized durations and loop closure.",
            "adoption": (
                "This carrier proves only the Meshy-native processing corridor. A real Brukk or "
                "Takka adoption should use the original account task and its provider-native "
                "auto-rig outputs while retaining the Meshy skeleton and materials."
            ),
        }
        if _contains_key(data, "frame_files"):
            raise FoundryError("Meshy native playback report contains dangling frame references.")
        _write_new(temporary_report, json_bytes(data))
        report_hash, report_size = _hash_file(temporary_report)

        directory.parent.mkdir(parents=True, exist_ok=True)
        directory.mkdir(exist_ok=False)
        promoted.append(directory)
        for source, destination in video_bindings:
            _promote_new(source, destination)
            promoted.append(destination)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        _promote_new(temporary_process, process_path)
        promoted.append(process_path)
        _promote_new(temporary_report, report_path)
        promoted.append(report_path)

        process_artifact = Artifact(
            artifact_id=f"meshy_native_playback_process_log_{number:03d}",
            role="meshy_native_playback_process_log",
            stage="review",
            format="json",
            path=process_relative,
            sha256=process_hash,
            size_bytes=process_size,
            derived_from=[model.artifact_id, normalization_report.artifact_id],
            processor=processor,
        )
        report_artifact = Artifact(
            artifact_id=f"meshy_native_playback_report_{number:03d}",
            role="meshy_native_playback_report",
            stage="review",
            format="json",
            path=report_relative,
            sha256=report_hash,
            size_bytes=report_size,
            derived_from=[
                model.artifact_id,
                normalization_report.artifact_id,
                *(item.artifact_id for item in video_artifacts),
                process_artifact.artifact_id,
            ],
            processor=processor,
        )
        target_artifacts = [*video_artifacts, process_artifact, report_artifact]
        _verify_promoted(asset_root, target_artifacts)
        _verify(model_path, model)
        _verify(normalization_path, normalization_report)
        source_revision = manifest.revision
        manifest.artifacts.extend(target_artifacts)
        manifest.validation.checks = [
            item
            for item in manifest.validation.checks
            if item.get("name") != "meshy_native_continuous_playback"
        ]
        manifest.validation.checks.append(
            {
                "name": "meshy_native_continuous_playback",
                "passed": True,
                "processed_model_sha256": model.sha256,
                "normalization_report_sha256": normalization_report.sha256,
                "report": str(report_relative),
                "clip_count": 10,
                "duration_tolerance_seconds": DURATION_TOLERANCE_SECONDS,
                "visual_acceptance": False,
            }
        )
        manifest.revision += 1
        manifest.asset.updated_at = utc_now()
        try:
            rollback_promoted = False
            repository.save(
                manifest,
                "preview.meshy_native_playback_rendered",
                expected_revision=source_revision,
            )
        except BaseException:
            live = repository.load(asset_id)
            if _is_exact_target(live, manifest.revision, target_artifacts):
                diagnosis = repository.diagnose_pending_save(asset_id)
                if diagnosis.status in {"event_missing", "event_partial", "event_complete"}:
                    repository.reconcile_pending_save(asset_id)
                _verify_promoted(asset_root, target_artifacts)
            elif live.revision == source_revision and not _references(live, target_artifacts):
                rollback_promoted = True
                raise
            else:
                raise
        _verify_promoted(asset_root, target_artifacts)
        return report_artifact
    except BaseException:
        if rollback_promoted:
            for path in reversed(promoted):
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)
        raise
    finally:
        if temporary_root is not None:
            shutil.rmtree(temporary_root, ignore_errors=True)


def _distributed_durations_ms(duration_seconds: float, frame_count: int) -> list[int]:
    total = round(duration_seconds * 1000)
    if total < frame_count:
        raise FoundryError("Meshy native playback duration is too short for its frame count.")
    base, remainder = divmod(total, frame_count)
    return [base + (1 if index < remainder else 0) for index in range(frame_count)]


def _webp_duration_seconds(path: Path) -> float:
    value = path.read_bytes()
    if len(value) < 12 or value[:4] != b"RIFF" or value[8:12] != b"WEBP":
        raise FoundryError("Meshy native playback output is not a WebP container.")
    declared_size = struct.unpack_from("<I", value, 4)[0] + 8
    if declared_size != len(value):
        raise FoundryError("Meshy native WebP has an invalid declared size.")
    total = 0
    frame_count = 0
    offset = 12
    while offset < len(value):
        if offset + 8 > len(value):
            raise FoundryError("Meshy native WebP has a truncated chunk header.")
        chunk_type = value[offset : offset + 4]
        chunk_size = struct.unpack_from("<I", value, offset + 4)[0]
        payload_start = offset + 8
        payload_end = payload_start + chunk_size
        if payload_end > len(value):
            raise FoundryError("Meshy native WebP has a truncated chunk.")
        if chunk_type == b"ANMF":
            if chunk_size < 16:
                raise FoundryError("Meshy native WebP animation frame is truncated.")
            total += int.from_bytes(value[payload_start + 12 : payload_start + 15], "little")
            frame_count += 1
        offset = payload_end + (chunk_size & 1)
    if frame_count < 2 or total <= 0:
        raise FoundryError("Meshy native WebP has no bounded animated duration.")
    return total / 1000.0


def _contains_key(value: object, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_contains_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False


def _verify(path: Path, artifact: Artifact) -> None:
    if not path.is_file() or _hash_file(path) != (artifact.sha256, artifact.size_bytes):
        raise FoundryError(f"Meshy native playback input changed: {artifact.artifact_id}")


def _verify_promoted(asset_root: Path, artifacts: list[Artifact]) -> None:
    for artifact in artifacts:
        path = contained_path(asset_root, artifact.path)
        if not path.is_file() or _hash_file(path) != (
            artifact.sha256,
            artifact.size_bytes,
        ):
            raise FoundryError(
                f"Promoted Meshy native playback bytes changed: {artifact.artifact_id}"
            )


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _write_new(path: Path, value: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def _promote_new(source: Path, destination: Path) -> None:
    try:
        os.link(source, destination)
    except FileExistsError as exc:
        raise FoundryError(f"Meshy native destination appeared concurrently: {destination}") from exc
    except OSError as exc:
        raise FoundryError(f"Could not promote Meshy native playback output: {exc}") from exc


def _portable_process_text(value: str, *private_paths: Path) -> str:
    redacted = value
    for path in sorted((str(item) for item in private_paths), key=len, reverse=True):
        redacted = redacted.replace(path, "<local-path>")
        redacted = redacted.replace(path.replace("\\", "/"), "<local-path>")
    redacted = re.sub(r"(?i)[a-z]:[\\/][^\r\n]*", "<local-path>", redacted)
    redacted = re.sub(
        r"(?i)(authorization\s*:\s*bearer|api[_-]?key|token|secret)\s*[=:]\s*\S+",
        r"\1=<redacted>",
        redacted,
    )
    return redacted


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _safe_environment() -> dict[str, str]:
    allowed = {
        "APPDATA",
        "HOME",
        "LOCALAPPDATA",
        "PATH",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    }
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
