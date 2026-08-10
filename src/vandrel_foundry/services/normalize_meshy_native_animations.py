import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, ScaleCalibration, utc_now
from vandrel_foundry.domain.meshy_native_canary import (
    EXPECTED_ACTION_COUNT,
    EXPECTED_JOINT_COUNT,
    MeshyNativeCanaryReport,
    MeshyNativeClip,
    MeshyNativeOutput,
    MeshyNativeSource,
)
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.domain.workflow_policy import invalidate_approval, transition_workflow
from vandrel_foundry.services.add_meshy_native_animation_package import ARCHIVE_ID, FBX_ID
from vandrel_foundry.services.inspect_glb import inspect_glb, load_glb_document
from vandrel_foundry.services.validate_godot import ProcessRunner, run_bounded_process
from vandrel_foundry.services.windows_acl_policy import apply_candidate_acl
from vandrel_foundry.storage.atomic import json_bytes
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path

PROCESSOR_NAME = "blender_meshy_native_normalization"
PROCESSOR_VERSION = "1"


@dataclass(frozen=True)
class MeshyNativeNormalizationResult:
    model: Artifact
    clips: tuple[Artifact, ...]
    report: Artifact


def normalize_meshy_native_animations(
    config: FoundryConfig,
    asset_id: str,
    runner: ProcessRunner | None = None,
) -> MeshyNativeNormalizationResult:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.asset.lane != "humanoid" or manifest.workflow.state not in {
        WorkflowState.DOWNLOADED,
        WorkflowState.PROCESSED,
    }:
        raise FoundryError("Meshy native normalization requires a downloaded humanoid candidate.")
    roots = [item for item in manifest.artifacts if item.stage == "source" and not item.derived_from]
    if {item.artifact_id for item in roots} != {ARCHIVE_ID, FBX_ID} or len(roots) != 2:
        raise FoundryError("Meshy native normalization requires the exact archive and FBX root union.")
    by_id = {item.artifact_id: item for item in roots}
    archive = by_id[ARCHIVE_ID]
    fbx = by_id[FBX_ID]
    if (archive.role, archive.format, fbx.role, fbx.format) != (
        "meshy_native_archive",
        "zip",
        "meshy_native_animation_fbx",
        "fbx",
    ):
        raise FoundryError("Meshy native source roles or formats are invalid.")
    executable = config.tools.blender_executable
    if executable is None or not executable.is_absolute() or not executable.is_file():
        raise FoundryError("Configure tools.blender_executable as an existing absolute file.")
    asset_root = repository.asset_directory(asset_id)
    source_paths = {item.artifact_id: contained_path(asset_root, item.path) for item in roots}
    for item in roots:
        _verify(source_paths[item.artifact_id], item)

    number = (
        sum(
            item.role == "processed_model"
            and item.processor is not None
            and item.processor.name == PROCESSOR_NAME
            for item in manifest.artifacts
        )
        + 1
    )
    model_id = f"meshy_native_canary_model_{number:03d}"
    model_relative = RelativeManifestPath(f"processed/meshy_native/{model_id}.glb")
    clips_relative = RelativeManifestPath(f"processed/meshy_native/clips_{number:03d}")
    report_relative = RelativeManifestPath(f"reports/meshy-native-canary-{number:03d}.json")
    process_relative = RelativeManifestPath(
        f"reports/meshy-native-canary-{number:03d}.process.json"
    )
    model_path = contained_path(asset_root, model_relative)
    clips_directory = contained_path(asset_root, clips_relative)
    report_path = contained_path(asset_root, report_relative)
    process_path = contained_path(asset_root, process_relative)
    if (
        model_path.exists()
        or clips_directory.exists()
        or report_path.exists()
        or process_path.exists()
    ):
        raise FoundryError("Meshy native normalization destination already exists.")

    temporary_root: Path | None = None
    promoted: list[Path] = []
    rollback_promoted = True
    try:
        temporary_root = Path(tempfile.mkdtemp(prefix=".meshy-native-", dir=asset_root))
        apply_candidate_acl(config, temporary_root)
        temporary_model = temporary_root / "combined.glb"
        temporary_clips = temporary_root / "clips"
        adapter_report = temporary_root / "adapter-report.json"
        temporary_process = temporary_root / "process.json"
        script = Path(__file__).parents[1] / "blender" / "normalize_meshy_native_animations.py"
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
            str(source_paths[FBX_ID]),
            str(temporary_model),
            str(temporary_clips),
            str(adapter_report),
        ]
        logical_arguments = [
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "--python-exit-code=1",
            f"--source-artifact={FBX_ID}",
            f"--archive-artifact={ARCHIVE_ID}",
            f"--output-role=processed_model:{model_relative}",
            f"--split-output-role=meshy_native_clip_model:{clips_relative}",
            f"--report-role=meshy_native_canary_report:{report_relative}",
            f"--process-log-role=meshy_native_normalization_process_log:{process_relative}",
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
            raise FoundryError(f"Bounded Meshy native normalization failed: {detail}")
        if not temporary_model.is_file() or not adapter_report.is_file() or not temporary_clips.is_dir():
            raise FoundryError("Meshy native adapter did not create its required outputs.")
        adapter = json.loads(adapter_report.read_text(encoding="utf-8"))
        if adapter.get("schema") != "vandrel_foundry_meshy_native_blender_adapter/1.0":
            raise FoundryError("Meshy native adapter report schema is invalid.")
        facts = adapter.get("transformation_facts")
        raw_clips = adapter.get("clips")
        split_outputs = adapter.get("split_outputs")
        if not isinstance(facts, dict) or not isinstance(raw_clips, list) or not isinstance(
            split_outputs, list
        ):
            raise FoundryError("Meshy native adapter report is incomplete.")
        expected_facts = {
            "source_armatures_retained": 1,
            "source_joint_count": EXPECTED_JOINT_COUNT,
            "source_action_count": EXPECTED_ACTION_COUNT,
            "output_action_count": EXPECTED_ACTION_COUNT,
            "unweighted_exported_vertex_count": 0,
            "bind_preserved": True,
            "global_normalization": "world_positive_90_degrees_x_y_up_to_z_up",
            "normalization_root_strategy": "parent_space_exported_on_armature_root",
            "rest_axis_policy": "preserve_native_bone_rest_matrices",
            "root_motion_policy": (
                "subtract_per_clip_hips_frame_start_and_raise_clip_minimum_ground_to_z_zero"
            ),
        }
        if any(facts.get(key) != value for key, value in expected_facts.items()):
            raise FoundryError("Meshy native adapter facts do not match the bounded contract.")
        clips = [MeshyNativeClip.model_validate(item) for item in raw_clips]
        if len(clips) != EXPECTED_ACTION_COUNT or len(split_outputs) != EXPECTED_ACTION_COUNT:
            raise FoundryError("Meshy native adapter did not split all ten actions.")
        names = [item.exact_name for item in clips]
        if [item.get("name") for item in split_outputs] != names:
            raise FoundryError("Meshy native split outputs do not preserve exact action order.")
        for item in roots:
            _verify(source_paths[item.artifact_id], item)

        process_value = {
            "schema": "vandrel_foundry_bounded_process/1.0",
            "processor_name": PROCESSOR_NAME,
            "processor_version": PROCESSOR_VERSION,
            "tool_version": str(adapter.get("tool_version")),
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

        combined_inspection = inspect_glb(temporary_model)
        _require_normalized_axis_root(temporary_model)
        if (
            combined_inspection.mesh_count < 1
            or combined_inspection.material_count < 1
            or combined_inspection.skin_count != 1
            or combined_inspection.joint_count != EXPECTED_JOINT_COUNT
            or combined_inspection.animation_count != EXPECTED_ACTION_COUNT
            or _animation_names(temporary_model) != names
        ):
            raise FoundryError("Combined Meshy native GLB failed independent structure inspection.")
        split_bindings: list[tuple[str, Path, str, int]] = []
        for index, (clip, item) in enumerate(zip(clips, split_outputs, strict=True), start=1):
            filename = item.get("file")
            if not isinstance(filename, str) or Path(filename).name != filename:
                raise FoundryError("Meshy native adapter emitted an unsafe split filename.")
            path = temporary_clips / filename
            inspection = inspect_glb(path)
            _require_normalized_axis_root(path)
            if (
                inspection.mesh_count < 1
                or inspection.material_count < 1
                or inspection.skin_count != 1
                or inspection.joint_count != EXPECTED_JOINT_COUNT
                or inspection.animation_count != 1
                or _animation_names(path) != [clip.exact_name]
            ):
                raise FoundryError(f"Split Meshy native GLB failed inspection: {clip.exact_name}")
            digest, size = _hash_file(path)
            split_bindings.append((filename, path, digest, size))

        model_hash, model_size = _hash_file(temporary_model)
        split_descriptors = [
            MeshyNativeOutput(
                artifact_id=f"meshy_native_clip_{number:03d}_{index:03d}",
                path=RelativeManifestPath(f"{clips_relative}/{filename}"),
                sha256=digest,
                size_bytes=size,
            )
            for index, (filename, _, digest, size) in enumerate(split_bindings, start=1)
        ]
        report = MeshyNativeCanaryReport(
            schema="vandrel_foundry_meshy_native_canary/1.0",
            processor_name=PROCESSOR_NAME,
            processor_version=PROCESSOR_VERSION,
            tool_version=str(adapter.get("tool_version")),
            arguments=logical_arguments,
            process={
                key: value
                for key, value in process_value.items()
                if key not in {"stdout", "stderr"}
            },
            process_log=MeshyNativeOutput(
                artifact_id=f"meshy_native_normalization_process_log_{number:03d}",
                path=process_relative,
                sha256=process_hash,
                size_bytes=process_size,
            ),
            sources=[
                MeshyNativeSource(
                    artifact_id=item.artifact_id,
                    role=item.role,
                    path=item.path,
                    sha256=item.sha256,
                    size_bytes=item.size_bytes,
                )
                for item in roots
            ],
            source_union=sorted(item.artifact_id for item in roots),
            transformation_facts={
                **facts,
                "combined_independent_glb_inspection": combined_inspection.__dict__,
                "split_independent_glb_inspection": {
                    "count": len(split_bindings),
                    "each_animation_count": 1,
                    "each_joint_count": EXPECTED_JOINT_COUNT,
                },
                "canary_scope": (
                    "Meshy-native carrier and motion corridor for Brukk adoption; the current "
                    "Brukk raw mesh is unrigged and is not substituted into this output."
                ),
            },
            clips=clips,
            combined_output=MeshyNativeOutput(
                artifact_id=model_id,
                path=model_relative,
                sha256=model_hash,
                size_bytes=model_size,
            ),
            split_outputs=split_descriptors,
        )
        temporary_report = temporary_root / "report.json"
        _write_new(temporary_report, json_bytes(report.model_dump(mode="json", by_alias=True)))
        report_hash, report_size = _hash_file(temporary_report)

        model_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        clips_directory.mkdir(parents=True, exist_ok=False)
        promoted.append(clips_directory)
        _promote_new(temporary_model, model_path)
        promoted.append(model_path)
        for descriptor, (_, path, _, _) in zip(split_descriptors, split_bindings, strict=True):
            destination = contained_path(asset_root, descriptor.path)
            _promote_new(path, destination)
            promoted.append(destination)
        _promote_new(temporary_report, report_path)
        promoted.append(report_path)
        _promote_new(temporary_process, process_path)
        promoted.append(process_path)

        processor = Processor(
            name=PROCESSOR_NAME,
            version=f"{PROCESSOR_VERSION}+{adapter['tool_version']}",
        )
        model = Artifact(
            artifact_id=model_id,
            role="processed_model",
            stage="processed",
            format="glb",
            path=model_relative,
            sha256=model_hash,
            size_bytes=model_size,
            derived_from=[ARCHIVE_ID, FBX_ID],
            processor=processor,
        )
        clip_artifacts = tuple(
            Artifact(
                artifact_id=descriptor.artifact_id,
                role="meshy_native_clip_model",
                stage="processed",
                format="glb",
                path=descriptor.path,
                sha256=descriptor.sha256,
                size_bytes=descriptor.size_bytes,
                derived_from=[ARCHIVE_ID, FBX_ID, model_id],
                processor=processor,
            )
            for descriptor in split_descriptors
        )
        process_artifact = Artifact(
            artifact_id=f"meshy_native_normalization_process_log_{number:03d}",
            role="meshy_native_normalization_process_log",
            stage="processing",
            format="json",
            path=process_relative,
            sha256=process_hash,
            size_bytes=process_size,
            derived_from=[ARCHIVE_ID, FBX_ID, model_id],
            processor=processor,
        )
        report_artifact = Artifact(
            artifact_id=f"meshy_native_canary_report_{number:03d}",
            role="meshy_native_canary_report",
            stage="processing",
            format="json",
            path=report_relative,
            sha256=report_hash,
            size_bytes=report_size,
            derived_from=[
                ARCHIVE_ID,
                FBX_ID,
                model_id,
                *(item.artifact_id for item in clip_artifacts),
                process_artifact.artifact_id,
            ],
            processor=processor,
        )
        target_artifacts = [model, *clip_artifacts, process_artifact, report_artifact]
        _verify_promoted(asset_root, target_artifacts)
        source_revision = manifest.revision
        manifest.artifacts.extend(target_artifacts)
        transition_workflow(manifest, WorkflowState.PROCESSED)
        manifest.validation.result = "not_run"
        manifest.validation.checks = []
        manifest.scale_calibration = ScaleCalibration()
        manifest.quality.observed = {}
        invalidate_approval(manifest)
        manifest.revision += 1
        manifest.asset.updated_at = utc_now()
        try:
            rollback_promoted = False
            repository.save(
                manifest,
                "asset.meshy_native_animations_normalized",
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
        return MeshyNativeNormalizationResult(model, clip_artifacts, report_artifact)
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


def _animation_names(path: Path) -> list[str]:
    value = load_glb_document(path).get("animations", [])
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise FoundryError("GLB animation array is invalid.")
    names = [item.get("name") for item in value]
    if any(not isinstance(name, str) or not name for name in names):
        raise FoundryError("GLB contains an unnamed animation.")
    return names


def _require_normalized_axis_root(path: Path) -> None:
    document = load_glb_document(path)
    skins = document.get("skins", [])
    nodes = document.get("nodes", [])
    if not isinstance(skins, list) or len(skins) != 1 or not isinstance(nodes, list):
        raise FoundryError("Meshy native GLB has an invalid skin/root structure.")
    skin_name = skins[0].get("name") if isinstance(skins[0], dict) else None
    matches = [item for item in nodes if isinstance(item, dict) and item.get("name") == skin_name]
    if len(matches) != 1:
        raise FoundryError("Meshy native GLB has no unique armature root node.")
    rotation = matches[0].get("rotation")
    expected = 2**-0.5
    if (
        not isinstance(rotation, list)
        or len(rotation) != 4
        or abs(abs(float(rotation[0])) - expected) > 1e-5
        or abs(float(rotation[1])) > 1e-5
        or abs(float(rotation[2])) > 1e-5
        or abs(abs(float(rotation[3])) - expected) > 1e-5
        or float(rotation[0]) * float(rotation[3]) <= 0
    ):
        raise FoundryError("Meshy native GLB did not retain the +90-degree X axis root.")


def _verify(path: Path, artifact: Artifact) -> None:
    if not path.is_file() or _hash_file(path) != (artifact.sha256, artifact.size_bytes):
        raise FoundryError(f"Meshy native source changed: {artifact.artifact_id}")


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


def _verify_promoted(asset_root: Path, artifacts: list[Artifact]) -> None:
    for artifact in artifacts:
        path = contained_path(asset_root, artifact.path)
        if not path.is_file() or _hash_file(path) != (
            artifact.sha256,
            artifact.size_bytes,
        ):
            raise FoundryError(
                f"Promoted Meshy native normalization bytes changed: {artifact.artifact_id}"
            )


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


def _promote_new(source: Path, destination: Path) -> None:
    try:
        os.link(source, destination)
    except FileExistsError as exc:
        raise FoundryError(f"Meshy native destination appeared concurrently: {destination}") from exc
    except OSError as exc:
        raise FoundryError(f"Could not promote Meshy native output: {exc}") from exc


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
