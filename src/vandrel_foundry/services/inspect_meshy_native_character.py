import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from pathlib import Path

from PIL import Image

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.domain.workflow_policy import invalidate_approval, transition_workflow
from vandrel_foundry.services.inspect_glb import load_glb_document
from vandrel_foundry.services.validate_godot import ProcessRunner, run_bounded_process
from vandrel_foundry.services.windows_acl_policy import apply_candidate_acl
from vandrel_foundry.storage.atomic import json_bytes
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path

PROCESSOR_NAME = "blender_meshy_native_character_inspection"
PROCESSOR_VERSION = "1"
ROOT_IDS = {
    "meshy_native_character_archive_root_001",
    "meshy_native_character_fbx_root_001",
    "meshy_native_walking_fbx_root_001",
    "meshy_native_character_texture_root_001",
}


def inspect_meshy_native_character(
    config: FoundryConfig,
    asset_id: str,
    runner: ProcessRunner | None = None,
    observed_credit_balance_before_after: str | None = None,
) -> Artifact:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.asset.lane != "humanoid" or manifest.workflow.state not in {
        WorkflowState.DOWNLOADED,
        WorkflowState.PROCESSED,
    }:
        raise FoundryError("Meshy native character inspection requires a downloaded or processed humanoid candidate.")
    roots = [item for item in manifest.artifacts if item.stage == "source" and not item.derived_from]
    if len(roots) != len(ROOT_IDS) or {item.artifact_id for item in roots} != ROOT_IDS:
        raise FoundryError("Meshy native character inspection requires the exact four-root union.")
    by_id = {item.artifact_id: item for item in roots}
    required = {
        "meshy_native_character_archive_root_001": ("meshy_native_character_archive", "zip"),
        "meshy_native_character_fbx_root_001": ("meshy_native_character_fbx", "fbx"),
        "meshy_native_walking_fbx_root_001": ("meshy_native_walking_fbx", "fbx"),
        "meshy_native_character_texture_root_001": ("meshy_native_character_texture", "png"),
    }
    if any((by_id[key].role, by_id[key].format) != expected for key, expected in required.items()):
        raise FoundryError("Meshy native character root roles or formats are invalid.")
    executable = config.tools.blender_executable
    if executable is None or not executable.is_absolute() or not executable.is_file():
        raise FoundryError("Configure tools.blender_executable as an existing absolute file.")
    asset_root = repository.asset_directory(asset_id)
    paths = {key: contained_path(asset_root, item.path) for key, item in by_id.items()}
    for key, item in by_id.items():
        _verify(paths[key], item)
    number = sum(item.role == "meshy_native_character_inspection_report" for item in manifest.artifacts) + 1
    report_relative = RelativeManifestPath(f"reports/meshy-native-character-inspection-{number:03d}.json")
    process_relative = RelativeManifestPath(f"reports/meshy-native-character-inspection-{number:03d}.process.json")
    preview_relative = RelativeManifestPath(f"preview/meshy-native-character-{number:03d}/walking.webp")
    report_path = contained_path(asset_root, report_relative)
    process_path = contained_path(asset_root, process_relative)
    preview_path = contained_path(asset_root, preview_relative)
    if report_path.exists() or process_path.exists() or preview_path.parent.exists():
        raise FoundryError("Meshy native character inspection destination already exists.")
    temporary: Path | None = None
    promoted: list[Path] = []
    rollback = True
    try:
        temporary = Path(tempfile.mkdtemp(prefix=".meshy-native-character-inspect-", dir=asset_root))
        apply_candidate_acl(config, temporary)
        adapter_report = temporary / "adapter-report.json"
        frames = temporary / "frames"
        temp_process = temporary / "process.json"
        temp_preview = temporary / "walking.webp"
        temp_report = temporary / "report.json"
        script = Path(__file__).parents[1] / "blender" / "inspect_meshy_native_character.py"
        arguments = [
            str(executable), "--background", "--factory-startup", "--disable-autoexec",
            "--python-exit-code", "1", "--python", str(script), "--",
            str(paths["meshy_native_character_fbx_root_001"]),
            str(paths["meshy_native_walking_fbx_root_001"]), str(frames), str(adapter_report),
        ]
        logical = [
            "--background", "--factory-startup", "--disable-autoexec", "--python-exit-code=1",
            "--character-artifact=meshy_native_character_fbx_root_001",
            "--walking-artifact=meshy_native_walking_fbx_root_001",
            f"--preview-role=meshy_native_character_playback_video:{preview_relative}",
            f"--report-role=meshy_native_character_inspection_report:{report_relative}",
            f"--process-log-role=meshy_native_character_process_log:{process_relative}",
        ]
        started = utc_now().isoformat()
        result = (runner or run_bounded_process)(arguments, asset_root, _safe_environment(), config.tools.blender_timeout_seconds, config.tools.maximum_output_bytes)
        ended = utc_now().isoformat()
        if result.return_code != 0 or result.timed_out or result.output_limited:
            raise FoundryError(f"Bounded Meshy native character inspection failed: {(result.stderr or result.stdout)[-2000:]}")
        for key, item in by_id.items():
            _verify(paths[key], item)
        data = json.loads(adapter_report.read_text(encoding="utf-8"))
        if data.get("schema") != "vandrel_foundry_meshy_native_character_adapter/1.0":
            raise FoundryError("Meshy native character adapter report is invalid.")
        character = data.get("character")
        walking = data.get("walking")
        if not isinstance(character, dict) or not isinstance(walking, dict):
            raise FoundryError("Meshy native character adapter report is incomplete.")
        _require_rigged(character, "character")
        _require_rigged(walking, "walking")
        duration = _require_matching_walking(character, walking)
        frame_files = data.get("frame_files")
        if not isinstance(frame_files, list) or len(frame_files) < 2:
            raise FoundryError("Meshy native character playback frames are incomplete.")
        images = []
        try:
            for item in frame_files:
                if not isinstance(item, str):
                    raise FoundryError("Meshy native character playback frame path is invalid.")
                frame = contained_path(frames, RelativeManifestPath(item))
                if frame.suffix.lower() != ".png" or not frame.is_file():
                    raise FoundryError("Meshy native character playback frame path is unsafe.")
                images.append(Image.open(frame).convert("RGB"))
            durations = _durations(duration, len(images))
            images[0].save(temp_preview, format="WEBP", save_all=True, append_images=images[1:], duration=durations, loop=0, lossless=True)
        finally:
            for image in images:
                image.close()
        preview_hash, preview_size = _hash(temp_preview)
        process = {
            "schema": "vandrel_foundry_bounded_process/1.0", "processor_name": PROCESSOR_NAME,
            "processor_version": PROCESSOR_VERSION, "tool_version": str(data.get("blender_version")),
            "logical_arguments": logical, "return_code": result.return_code, "started_at": started,
            "ended_at": ended, "duration_seconds": result.duration_seconds,
            "timeout_seconds": config.tools.blender_timeout_seconds,
            "maximum_output_bytes": config.tools.maximum_output_bytes, "timed_out": result.timed_out,
            "output_limited": result.output_limited,
            "stdout": _redact(result.stdout), "stderr": _redact(result.stderr),
        }
        _write_new(temp_process, json_bytes(process))
        process_hash, process_size = _hash(temp_process)
        compatibility = _canary_compatibility(repository, asset_root, character, walking)
        data.pop("frame_files", None)
        data["source_union"] = sorted(ROOT_IDS)
        data["provider_observation"] = {
            "observation_basis": "user_observed_provider_metadata",
            "observed_credit_balance_before_after": (
                observed_credit_balance_before_after
                if observed_credit_balance_before_after is not None
                else "not_observed_by_inspection_service"
            ),
        }
        data["compatibility_with_current_meshy_canary"] = compatibility
        data["playback"] = {
            "artifact_id": f"meshy_native_character_playback_video_{number:03d}", "path": str(preview_relative),
            "sha256": preview_hash, "size_bytes": preview_size, "format": "webp",
            "bound_duration_seconds": duration,
        }
        data["process"] = {key: value for key, value in process.items() if key not in {"stdout", "stderr"}}
        data["process_log"] = {"artifact_id": f"meshy_native_character_process_log_{number:03d}", "path": str(process_relative), "sha256": process_hash, "size_bytes": process_size}
        data["visual_acceptance"] = False
        _write_new(temp_report, json_bytes(data))
        report_hash, report_size = _hash(temp_report)
        _verify_roots(paths, by_id)
        preview_path.parent.mkdir(parents=True, exist_ok=False); promoted.append(preview_path.parent)
        _link_new(temp_preview, preview_path); promoted.append(preview_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        _link_new(temp_process, process_path); promoted.append(process_path)
        _link_new(temp_report, report_path); promoted.append(report_path)
        processor = Processor(name=PROCESSOR_NAME, version=f"{PROCESSOR_VERSION}+{data['blender_version']}")
        video = Artifact(
            artifact_id=f"meshy_native_character_playback_video_{number:03d}",
            role="meshy_native_character_playback_video",
            stage="review",
            format="webp",
            path=preview_relative,
            sha256=preview_hash,
            size_bytes=preview_size,
            derived_from=sorted(ROOT_IDS),
            processor=processor,
        )
        log = Artifact(
            artifact_id=f"meshy_native_character_process_log_{number:03d}",
            role="meshy_native_character_process_log",
            stage="processing",
            format="json",
            path=process_relative,
            sha256=process_hash,
            size_bytes=process_size,
            derived_from=sorted(ROOT_IDS),
            processor=processor,
        )
        report = Artifact(
            artifact_id=f"meshy_native_character_inspection_report_{number:03d}",
            role="meshy_native_character_inspection_report",
            stage="review",
            format="json",
            path=report_relative,
            sha256=report_hash,
            size_bytes=report_size,
            derived_from=[*sorted(ROOT_IDS), video.artifact_id, log.artifact_id],
            processor=processor,
        )
        targets = [video, log, report]
        _verify_roots(paths, by_id)
        _verify_targets(asset_root, targets)
        revision = manifest.revision
        manifest.artifacts.extend(targets)
        if manifest.workflow.state is WorkflowState.DOWNLOADED:
            transition_workflow(manifest, WorkflowState.PROCESSED)
        manifest.validation.result = "not_run"; manifest.validation.checks = []
        invalidate_approval(manifest); manifest.revision += 1; manifest.asset.updated_at = utc_now()
        try:
            rollback = False
            repository.save(manifest, "asset.meshy_native_character_inspected", expected_revision=revision)
        except BaseException:
            live = repository.load(asset_id)
            if live.revision == manifest.revision and _references(live, targets):
                diagnosis = repository.diagnose_pending_save(asset_id)
                if diagnosis.status in {"event_missing", "event_partial", "event_complete"}:
                    repository.reconcile_pending_save(asset_id)
            elif live.revision == revision and not _references(live, targets):
                rollback = True; raise
            else:
                raise
        _verify_roots(paths, by_id)
        _verify_targets(asset_root, targets)
        return report
    except BaseException:
        if rollback:
            for path in reversed(promoted):
                shutil.rmtree(path, ignore_errors=True) if path.is_dir() else path.unlink(missing_ok=True)
        raise
    finally:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)


def _canary_compatibility(repository, asset_root, character, walking):
    reference = repository.load("meshy_native_brukk_canary_001")
    models = [item for item in reference.artifacts if item.role == "processed_model"]
    model = models[-1]
    ref_path = contained_path(repository.asset_directory(reference.asset.asset_id), model.path)
    _verify(ref_path, model)
    document = load_glb_document(ref_path)
    skin = document["skins"][0]; nodes = document["nodes"]
    parents = {child: index for index, node in enumerate(nodes) if isinstance(node, dict) for child in node.get("children", [])}
    joints = skin["joints"]
    joint_names = {nodes[index]["name"] for index in joints}
    hierarchy = {
        nodes[index]["name"]: (
            nodes[parents[index]]["name"]
            if index in parents and nodes[parents[index]]["name"] in joint_names
            else None
        )
        for index in joints
    }
    names = set(hierarchy)
    character_mismatches = _hierarchy_mismatches(character["joint_hierarchy"], hierarchy)
    walking_mismatches = _hierarchy_mismatches(walking["joint_hierarchy"], hierarchy)
    return {
        "reference_asset_id": reference.asset.asset_id, "reference_model_artifact_id": model.artifact_id,
        "reference_model_sha256": model.sha256, "reference_joint_count": len(hierarchy),
        "character_joint_count": character["joint_count"], "walking_joint_count": walking["joint_count"],
        "character_exact_joint_names_match": set(character["joint_hierarchy"]) == names,
        "character_exact_hierarchy_match": not character_mismatches,
        "character_hierarchy_mismatches": character_mismatches,
        "walking_exact_joint_names_match": set(walking["joint_hierarchy"]) == names,
        "walking_exact_hierarchy_match": not walking_mismatches,
        "walking_hierarchy_mismatches": walking_mismatches,
        "walking_matches_character_joint_names": set(walking["joint_hierarchy"]) == set(character["joint_hierarchy"]),
        "walking_matches_character_hierarchy": walking["joint_hierarchy"] == character["joint_hierarchy"],
    }


def _hierarchy_mismatches(actual, expected):
    return [
        {
            "joint": key,
            "actual_parent": actual.get(key),
            "canary_parent": expected.get(key),
        }
        for key in sorted(set(actual) | set(expected))
        if actual.get(key) != expected.get(key)
    ]


def _require_rigged(value, label):
    if value.get("armature_count") != 1 or value.get("skinned_mesh_count", 0) < 1 or value.get("joint_count", 0) < 1 or value.get("unweighted_vertex_count") != 0:
        raise FoundryError(f"Meshy native {label} FBX fails armature, skin, joint, or weighting inspection.")


def _require_matching_walking(character, walking):
    if character.get("joint_hierarchy") != walking.get("joint_hierarchy"):
        raise FoundryError("Meshy native character and Walking hierarchies do not match.")
    character_bind = character.get("bind_signature")
    walking_bind = walking.get("bind_signature")
    if (
        not isinstance(character_bind, str)
        or not isinstance(walking_bind, str)
        or len(character_bind) != 64
        or len(walking_bind) != 64
        or character_bind != walking_bind
    ):
        raise FoundryError("Meshy native character and Walking bind signatures do not match.")
    actions = walking.get("actions")
    if not isinstance(actions, list) or not actions:
        raise FoundryError("Meshy native walking FBX has no animation action.")
    try:
        duration = float(actions[0]["duration_seconds"])
    except (KeyError, TypeError, ValueError) as exc:
        raise FoundryError("Meshy native Walking duration is invalid.") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise FoundryError("Meshy native Walking duration is invalid.")
    return duration


def _durations(seconds, count):
    total = round(seconds * 1000); base, remainder = divmod(total, count)
    if base < 1: raise FoundryError("Meshy native walking duration is too short.")
    return [base + (index < remainder) for index in range(count)]


def _hash(path):
    digest = hashlib.sha256(); size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024): digest.update(chunk); size += len(chunk)
    return digest.hexdigest(), size


def _verify(path, artifact):
    if not path.is_file() or _hash(path) != (artifact.sha256, artifact.size_bytes):
        raise FoundryError(f"Meshy native character input changed: {artifact.artifact_id}")


def _verify_roots(paths, by_id):
    for key, artifact in by_id.items():
        _verify(paths[key], artifact)


def _verify_targets(root, artifacts):
    for artifact in artifacts: _verify(contained_path(root, artifact.path), artifact)


def _write_new(path, value):
    with path.open("xb") as stream: stream.write(value); stream.flush(); os.fsync(stream.fileno())


def _link_new(source, destination):
    try: os.link(source, destination)
    except FileExistsError as exc: raise FoundryError(f"Meshy native character destination appeared concurrently: {destination}") from exc


def _references(manifest, artifacts):
    values = {item.artifact_id: item for item in manifest.artifacts}
    return all(values.get(item.artifact_id) is not None and values[item.artifact_id].model_dump(mode="json") == item.model_dump(mode="json") for item in artifacts)


def _redact(value):
    value = re.sub(r"(?i)[a-z]:[\\/][^\r\n]*", "<local-path>", value)
    return re.sub(r"(?i)(authorization\s*:\s*bearer|api[_-]?key|token|secret)\s*[=:]\s*\S+", r"\1=<redacted>", value)


def _safe_environment():
    allowed = {"APPDATA", "HOME", "LOCALAPPDATA", "PATH", "SYSTEMDRIVE", "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE", "WINDIR"}
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}
