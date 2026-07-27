import hashlib
import json
import os
from pathlib import Path

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.inspect_glb import inspect_glb
from vandrel_foundry.services.validate_godot import ProcessRunner, run_bounded_process
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path

ADAPTER_VERSION = "1"


def process_with_blender(
    config: FoundryConfig,
    asset_id: str,
    runner: ProcessRunner | None = None,
) -> Artifact:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.workflow.state not in {WorkflowState.DOWNLOADED, WorkflowState.PROCESSED}:
        raise FoundryError(f"Blender processing requires downloaded or processed state: {asset_id}")
    executable = config.tools.blender_executable
    if executable is None or not executable.is_absolute() or not executable.is_file():
        raise FoundryError("Configure tools.blender_executable as an existing absolute file.")
    candidates = [
        item
        for item in manifest.artifacts
        if item.role in {"source_model", "processed_model"} and item.format == "glb"
    ]
    if not candidates:
        raise FoundryError(f"No GLB input exists for Blender processing: {asset_id}")
    source = candidates[-1]
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    source_path = contained_path(asset_root, source.path)
    _verify_artifact(source_path, source)

    number = sum(item.role == "processed_model" for item in manifest.artifacts) + 1
    artifact_id = f"processed_glb_{number:03d}"
    output_relative = RelativeManifestPath(f"processed/blender/{artifact_id}.glb")
    report_relative = RelativeManifestPath(f"reports/blender-processing-{number:03d}.json")
    output_path = contained_path(asset_root, output_relative)
    report_path = contained_path(asset_root, report_relative)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() or report_path.exists():
        raise FoundryError("Blender output or report destination already exists.")
    script = Path(__file__).parents[1] / "blender" / "process_glb.py"
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
        str(source_path),
        str(output_path),
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
            raise FoundryError("Bounded Blender processing failed.")
        if not output_path.is_file() or not report_path.is_file():
            raise FoundryError("Blender did not create its required output and report.")
        inspect_glb(output_path)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        version = str(report["blender_version"])
        digest, size = _hash_file(output_path)
        report_digest, report_size = _hash_file(report_path)
    except BaseException:
        output_path.unlink(missing_ok=True)
        report_path.unlink(missing_ok=True)
        raise
    processor = Processor(
        name="blender_cleanup",
        version=f"{ADAPTER_VERSION}+blender-{version}",
    )
    artifact = Artifact(
        artifact_id=artifact_id,
        role="processed_model",
        stage="processed",
        format="glb",
        path=output_relative,
        sha256=digest,
        size_bytes=size,
        derived_from=[source.artifact_id],
        source_task_key=source.source_task_key,
        processor=processor,
    )
    report_artifact = Artifact(
        artifact_id=f"blender_processing_report_{number:03d}",
        role="blender_processing_report",
        stage="processing",
        format="json",
        path=report_relative,
        sha256=report_digest,
        size_bytes=report_size,
        derived_from=[source.artifact_id, artifact.artifact_id],
        source_task_key=source.source_task_key,
        processor=processor,
    )
    manifest.artifacts.extend([artifact, report_artifact])
    manifest.workflow.state = WorkflowState.PROCESSED
    manifest.validation.result = "not_run"
    manifest.validation.checks = []
    manifest.approval.approved = False
    manifest.approval.approved_at = None
    manifest.approval.approved_artifact_hashes = {}
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    repository.save(
        manifest,
        "asset.blender_processed",
        expected_revision=manifest.revision - 1,
    )
    return artifact


def _verify_artifact(path: Path, artifact: Artifact) -> None:
    digest, size = _hash_file(path)
    if digest != artifact.sha256 or size != artifact.size_bytes:
        raise FoundryError(f"Blender input artifact changed: {artifact.artifact_id}")


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size
