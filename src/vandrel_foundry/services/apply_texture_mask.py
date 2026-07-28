import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.inspect_glb import inspect_glb
from vandrel_foundry.services.validate_godot import ProcessRunner, run_bounded_process
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path

PROCESSOR_VERSION = "1"
ALLOWED_STATES = {
    WorkflowState.PROCESSED,
    WorkflowState.STAGED,
    WorkflowState.REVIEW,
    WorkflowState.APPROVED,
}
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass(frozen=True)
class TextureMaskResult:
    model: Artifact
    mask: Artifact
    report: Artifact
    log: Artifact
    coverage_fraction: float


def apply_texture_mask(
    config: FoundryConfig,
    asset_id: str,
    mask_source: Path,
    color: str,
    runner: ProcessRunner | None = None,
) -> TextureMaskResult:
    if not HEX_COLOR.fullmatch(color):
        raise FoundryError("Texture-mask color must use #RRGGBB format.")
    if mask_source.suffix.lower() != ".png" or not mask_source.is_file():
        raise FoundryError("Texture mask must be an existing PNG file.")
    try:
        with Image.open(mask_source) as image:
            image.verify()
        with Image.open(mask_source) as image:
            grayscale = image.convert("L")
            extrema = grayscale.getextrema()
            if extrema is None or extrema[1] == 0 or extrema[0] == 255:
                raise FoundryError("Texture mask must select a nonempty, bounded region.")
    except OSError as exc:
        raise FoundryError(f"Texture mask is not a valid PNG: {exc}") from exc

    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.workflow.state not in ALLOWED_STATES:
        raise FoundryError(f"Texture-mask processing requires a processed asset: {asset_id}")
    executable = config.tools.blender_executable
    if executable is None or not executable.is_absolute() or not executable.is_file():
        raise FoundryError("Configure tools.blender_executable as an existing absolute file.")
    candidates = [
        item
        for item in manifest.artifacts
        if item.role == "processed_model" and item.format == "glb"
    ]
    if not candidates:
        raise FoundryError(f"Texture-mask processing requires a processed GLB: {asset_id}")
    source = candidates[-1]
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    source_path = contained_path(asset_root, source.path)
    _verify_artifact(source_path, source)
    source_inspection = inspect_glb(source_path)

    number = len(candidates) + 1
    model_id = f"processed_glb_{number:03d}"
    mask_id = f"texture_region_mask_{number:03d}"
    model_relative = RelativeManifestPath(f"processed/texture_mask/{model_id}.glb")
    mask_relative = RelativeManifestPath(f"processed/texture_mask/{mask_id}.png")
    report_relative = RelativeManifestPath(f"reports/texture-mask-processing-{number:03d}.json")
    log_relative = RelativeManifestPath(f"reports/texture-mask-processing-{number:03d}.log")
    model_path = contained_path(asset_root, model_relative)
    mask_path = contained_path(asset_root, mask_relative)
    report_path = contained_path(asset_root, report_relative)
    log_path = contained_path(asset_root, log_relative)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    outputs = [model_path, mask_path, report_path, log_path]
    if any(path.exists() for path in outputs):
        raise FoundryError("Texture-mask output or evidence destination already exists.")

    script = Path(__file__).parents[1] / "blender" / "apply_texture_mask.py"
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
        str(mask_path),
        str(model_path),
        str(report_path),
        color.lower(),
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
        _write_new_bytes(mask_path, mask_source.read_bytes())
        result = (runner or run_bounded_process)(
            arguments,
            asset_root,
            safe_environment,
            config.tools.blender_timeout_seconds,
            config.tools.maximum_output_bytes,
        )
        if result.return_code != 0 or result.timed_out or result.output_limited:
            raise FoundryError("Bounded Blender texture-mask processing failed.")
        if not model_path.is_file() or not report_path.is_file():
            raise FoundryError("Blender did not create texture-mask model and report outputs.")
        output_inspection = inspect_glb(model_path)
        if output_inspection.animation_count != source_inspection.animation_count:
            raise FoundryError("Texture-mask processing did not preserve animations.")
        report_data = json.loads(report_path.read_text(encoding="utf-8"))
        coverage = float(report_data["coverage_fraction"])
        if not 0 < coverage < 1:
            raise FoundryError("Texture-mask report contains invalid coverage.")
        model_hash, model_size = _hash_file(model_path)
        mask_hash, mask_size = _hash_file(mask_path)
        report_data.update(
            {
                "asset_id": asset_id,
                "input": _artifact_binding(source),
                "mask": {
                    "artifact_id": mask_id,
                    "sha256": mask_hash,
                    "size_bytes": mask_size,
                },
                "output": {
                    "artifact_id": model_id,
                    "sha256": model_hash,
                    "size_bytes": model_size,
                },
                "checks": {
                    "input_hash_verified": True,
                    "mask_is_bounded": True,
                    "output_glb_structure_valid": True,
                    "animations_preserved": True,
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
                    f"asset_id={asset_id}",
                    f"input_artifact_id={source.artifact_id}",
                    f"mask_artifact_id={mask_id}",
                    f"output_artifact_id={model_id}",
                    "result=success",
                ]
            )
            + "\n",
        )
        report_hash, report_size = _hash_file(report_path)
        log_hash, log_size = _hash_file(log_path)
    except BaseException:
        for path in outputs:
            path.unlink(missing_ok=True)
        try:
            model_path.parent.rmdir()
        except OSError:
            pass
        raise

    processor = Processor(
        name="blender_texture_mask_recolor",
        version=f"{PROCESSOR_VERSION}+blender-{report_data['blender_version']}",
    )
    mask_artifact = Artifact(
        artifact_id=mask_id,
        role="texture_region_mask",
        stage="processing",
        format="png",
        path=mask_relative,
        sha256=mask_hash,
        size_bytes=mask_size,
        derived_from=[source.artifact_id],
        processor=processor,
    )
    model = Artifact(
        artifact_id=model_id,
        role="processed_model",
        stage="processed",
        format="glb",
        path=model_relative,
        sha256=model_hash,
        size_bytes=model_size,
        derived_from=[source.artifact_id, mask_id],
        source_task_key=source.source_task_key,
        processor=processor,
    )
    report = Artifact(
        artifact_id=f"texture_mask_processing_report_{number:03d}",
        role="texture_mask_processing_report",
        stage="processing",
        format="json",
        path=report_relative,
        sha256=report_hash,
        size_bytes=report_size,
        derived_from=[source.artifact_id, mask_id, model_id],
        processor=processor,
    )
    log = Artifact(
        artifact_id=f"texture_mask_processing_log_{number:03d}",
        role="texture_mask_processing_log",
        stage="processing",
        format="log",
        path=log_relative,
        sha256=log_hash,
        size_bytes=log_size,
        derived_from=[source.artifact_id, mask_id, model_id],
        processor=processor,
    )
    manifest.artifacts.extend([mask_artifact, model, report, log])
    manifest.workflow.state = WorkflowState.PROCESSED
    manifest.validation.result = "not_run"
    manifest.validation.checks = []
    manifest.approval.approved = False
    manifest.approval.approved_at = None
    manifest.approval.approved_artifact_hashes = {}
    manifest.approval.custody_assertion_sha256 = None
    manifest.approval.custody_source_inputs = []
    manifest.approval.reviewer = None
    manifest.approval.notes = ""
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    repository.save(
        manifest,
        "asset.texture_mask_applied",
        expected_revision=manifest.revision - 1,
    )
    return TextureMaskResult(
        model=model,
        mask=mask_artifact,
        report=report,
        log=log,
        coverage_fraction=coverage,
    )


def _artifact_binding(artifact: Artifact) -> dict[str, object]:
    return {
        "artifact_id": artifact.artifact_id,
        "sha256": artifact.sha256,
        "size_bytes": artifact.size_bytes,
    }


def _verify_artifact(path: Path, artifact: Artifact) -> None:
    digest, size = _hash_file(path)
    if digest != artifact.sha256 or size != artifact.size_bytes:
        raise FoundryError(f"Texture-mask input changed: {artifact.artifact_id}")


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _write_new_bytes(path: Path, value: bytes) -> None:
    try:
        with path.open("xb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise FoundryError(f"Could not record texture mask: {exc}") from exc


def _write_new_text(path: Path, value: str) -> None:
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise FoundryError(f"Could not write texture-mask log: {exc}") from exc
