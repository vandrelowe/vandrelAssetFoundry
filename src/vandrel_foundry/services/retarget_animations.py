import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.inspect_glb import inspect_glb
from vandrel_foundry.services.validate_godot import ProcessRunner, run_bounded_process
from vandrel_foundry.services.validate_humanoid_retarget import (
    extract_skeleton_facts,
    load_glb_document,
)
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path

RETARGETER_VERSION = "1"
ALLOWED_STATES = {
    WorkflowState.PROCESSED,
    WorkflowState.STAGED,
    WorkflowState.REVIEW,
    WorkflowState.APPROVED,
}


@dataclass(frozen=True)
class AnimationRetargetResult:
    model: Artifact
    report: Artifact
    log: Artifact
    animation_count: int
    animation_names: tuple[str, ...]


def retarget_animations(
    config: FoundryConfig,
    asset_id: str,
    animation_donor_asset_id: str,
    runner: ProcessRunner | None = None,
) -> AnimationRetargetResult:
    if asset_id == animation_donor_asset_id:
        raise FoundryError("Animation retargeting requires a distinct donor asset.")
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    donor_manifest = repository.load(animation_donor_asset_id)
    if manifest.asset.lane != "humanoid":
        raise FoundryError("Animation retargeting requires the humanoid lane.")
    if manifest.workflow.state not in ALLOWED_STATES:
        raise FoundryError(f"Animation retargeting requires a processed target: {asset_id}")
    if donor_manifest.workflow.state not in ALLOWED_STATES:
        raise FoundryError(
            f"Animation retargeting requires a processed donor: {animation_donor_asset_id}"
        )
    executable = config.tools.blender_executable
    if executable is None or not executable.is_absolute() or not executable.is_file():
        raise FoundryError("Configure tools.blender_executable as an existing absolute file.")

    target = _latest_processed(manifest.artifacts, asset_id)
    donor = _latest_processed(donor_manifest.artifacts, animation_donor_asset_id)
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    donor_root = config.foundry.workspace_root / "assets" / animation_donor_asset_id
    target_path = contained_path(asset_root, target.path)
    donor_path = contained_path(donor_root, donor.path)
    _verify_artifact(target_path, target)
    _verify_artifact(donor_path, donor)
    target_facts = extract_skeleton_facts(load_glb_document(target_path))
    donor_facts = extract_skeleton_facts(load_glb_document(donor_path))
    if (
        target_facts.joint_names != donor_facts.joint_names
        or target_facts.parent_by_joint != donor_facts.parent_by_joint
    ):
        raise FoundryError(
            "Animation retargeting requires exact joint names and hierarchy for this corridor."
        )
    if not donor_facts.animation_names:
        raise FoundryError("Animation retargeting donor contains no animations.")

    number = sum(item.role == "processed_model" for item in manifest.artifacts) + 1
    model_id = f"processed_glb_{number:03d}"
    model_relative = RelativeManifestPath(f"processed/animation_retarget/{model_id}.glb")
    report_relative = RelativeManifestPath(f"reports/animation-retarget-{number:03d}.json")
    log_relative = RelativeManifestPath(f"reports/animation-retarget-{number:03d}.log")
    model_path = contained_path(asset_root, model_relative)
    report_path = contained_path(asset_root, report_relative)
    log_path = contained_path(asset_root, log_relative)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if model_path.exists() or report_path.exists() or log_path.exists():
        raise FoundryError("Animation retarget output or evidence destination already exists.")

    script = Path(__file__).parents[1] / "blender" / "retarget_animations.py"
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
        str(target_path),
        str(donor_path),
        str(model_path),
        str(report_path),
    ]
    safe_environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper()
        in {
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
    }
    try:
        result = (runner or run_bounded_process)(
            arguments,
            asset_root,
            safe_environment,
            config.tools.blender_timeout_seconds,
            config.tools.maximum_output_bytes,
        )
        if result.return_code != 0 or result.timed_out or result.output_limited:
            raise FoundryError("Bounded Blender animation retargeting failed.")
        if not model_path.is_file() or not report_path.is_file():
            raise FoundryError("Blender did not create retargeted model and report outputs.")
        report_data = json.loads(report_path.read_text(encoding="utf-8"))
        inspection = inspect_glb(model_path)
        animation_names = tuple(str(item["name"]) for item in report_data.get("animations", []))
        if inspection.animation_count != len(animation_names):
            raise FoundryError("Retargeted GLB animation count does not match its report.")
        if animation_names != donor_facts.animation_names:
            raise FoundryError("Retargeted GLB report does not preserve donor animation names.")
        if report_data.get("output_animation_count") != len(animation_names):
            raise FoundryError("Retarget report animation count is inconsistent.")
        model_hash, model_size = _hash_file(model_path)
        report_data.update(
            {
                "asset_id": asset_id,
                "target": _artifact_binding(asset_id, target),
                "animation_donor": _artifact_binding(animation_donor_asset_id, donor),
                "output": {
                    "artifact_id": model_id,
                    "sha256": model_hash,
                    "size_bytes": model_size,
                },
                "checks": {
                    "exact_joint_names_and_hierarchy": True,
                    "donor_animations_baked": True,
                    "output_glb_structure_valid": True,
                    "output_animation_count_matches": True,
                },
            }
        )
        report_path.write_text(
            json.dumps(report_data, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        _write_new_text(
            log_path,
            "\n".join(
                [
                    "--- stdout ---",
                    result.stdout,
                    "--- stderr ---",
                    result.stderr,
                    f"target_asset_id={asset_id}",
                    f"target_artifact_id={target.artifact_id}",
                    f"donor_asset_id={animation_donor_asset_id}",
                    f"donor_artifact_id={donor.artifact_id}",
                    f"output_animation_count={len(animation_names)}",
                    "result=success",
                ]
            )
            + "\n",
        )
        report_hash, report_size = _hash_file(report_path)
        log_hash, log_size = _hash_file(log_path)
    except BaseException:
        model_path.unlink(missing_ok=True)
        report_path.unlink(missing_ok=True)
        log_path.unlink(missing_ok=True)
        raise

    processor = Processor(
        name="blender_rest_pose_retarget",
        version=f"{RETARGETER_VERSION}+blender-{report_data['blender_version']}",
    )
    model = Artifact(
        artifact_id=model_id,
        role="processed_model",
        stage="processed",
        format="glb",
        path=model_relative,
        sha256=model_hash,
        size_bytes=model_size,
        derived_from=[target.artifact_id],
        source_task_key=target.source_task_key,
        processor=processor,
    )
    report = Artifact(
        artifact_id=f"animation_retarget_report_{number:03d}",
        role="animation_retarget_report",
        stage="processing",
        format="json",
        path=report_relative,
        sha256=report_hash,
        size_bytes=report_size,
        derived_from=[target.artifact_id, model.artifact_id],
        processor=processor,
    )
    log = Artifact(
        artifact_id=f"animation_retarget_log_{number:03d}",
        role="animation_retarget_log",
        stage="processing",
        format="log",
        path=log_relative,
        sha256=log_hash,
        size_bytes=log_size,
        derived_from=[target.artifact_id, model.artifact_id],
        processor=processor,
    )
    manifest.artifacts.extend([model, report, log])
    manifest.workflow.state = WorkflowState.PROCESSED
    manifest.validation.result = "not_run"
    manifest.validation.checks = []
    manifest.approval.approved = False
    manifest.approval.approved_at = None
    manifest.approval.approved_artifact_hashes = {}
    manifest.approval.reviewer = None
    manifest.approval.notes = ""
    manifest.quality.observed["animation_count"] = len(animation_names)
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    repository.save(
        manifest,
        "asset.animations_retargeted",
        expected_revision=manifest.revision - 1,
    )
    return AnimationRetargetResult(
        model=model,
        report=report,
        log=log,
        animation_count=len(animation_names),
        animation_names=animation_names,
    )


def _latest_processed(artifacts: list[Artifact], asset_id: str) -> Artifact:
    candidates = [
        item for item in artifacts if item.role == "processed_model" and item.format == "glb"
    ]
    if not candidates:
        raise FoundryError(f"Animation retargeting requires a processed GLB: {asset_id}")
    return candidates[-1]


def _verify_artifact(path: Path, artifact: Artifact) -> None:
    digest, size = _hash_file(path)
    if digest != artifact.sha256 or size != artifact.size_bytes:
        raise FoundryError(f"Animation retarget input changed: {artifact.artifact_id}")


def _artifact_binding(asset_id: str, artifact: Artifact) -> dict[str, object]:
    return {
        "asset_id": asset_id,
        "artifact_id": artifact.artifact_id,
        "sha256": artifact.sha256,
        "size_bytes": artifact.size_bytes,
    }


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _write_new_text(path: Path, value: str) -> None:
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise FoundryError(f"Could not write animation retarget log: {exc}") from exc
