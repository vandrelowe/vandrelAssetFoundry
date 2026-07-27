import hashlib
import json
import os
from pathlib import Path

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.validate_godot import ProcessRunner, run_bounded_process
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path


def render_local_preview(
    config: FoundryConfig, asset_id: str, runner: ProcessRunner | None = None
) -> Artifact:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.workflow.state not in {
        WorkflowState.PROCESSED,
        WorkflowState.REVIEW,
        WorkflowState.APPROVED,
    }:
        raise FoundryError(
            f"Preview rendering requires processed, review, or approved state: {asset_id}"
        )
    executable = config.tools.blender_executable
    if executable is None or not executable.is_absolute() or not executable.is_file():
        raise FoundryError("Configure tools.blender_executable as an existing absolute file.")
    sources = [item for item in manifest.artifacts if item.role == "processed_model"]
    if not sources:
        raise FoundryError(f"No processed GLB exists for preview rendering: {asset_id}")
    source = sources[-1]
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    source_path = contained_path(asset_root, source.path)
    digest, size = _hash_file(source_path)
    if digest != source.sha256 or size != source.size_bytes:
        raise FoundryError(f"Preview input artifact changed: {source.artifact_id}")
    number = sum(item.role == "local_preview" for item in manifest.artifacts) + 1
    image_relative = RelativeManifestPath(f"preview/local-preview-{number:03d}.png")
    report_relative = RelativeManifestPath(f"reports/local-preview-{number:03d}.json")
    log_relative = RelativeManifestPath(f"reports/local-preview-{number:03d}.log")
    image_path = contained_path(asset_root, image_relative)
    report_path = contained_path(asset_root, report_relative)
    log_path = contained_path(asset_root, log_relative)
    image_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).parents[1] / "blender" / "render_preview.py"
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
        str(image_path),
        str(report_path),
    ]
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper()
        in {
            "APPDATA",
            "HOME",
            "LOCALAPPDATA",
            "PATH",
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
            environment,
            config.tools.blender_timeout_seconds,
            config.tools.maximum_output_bytes,
        )
        if result.return_code != 0 or result.timed_out or result.output_limited:
            raise FoundryError("Bounded Blender preview rendering failed.")
        if image_path.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            raise FoundryError("Blender preview output is not a PNG.")
        log_path.write_text(
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}\n",
            encoding="utf-8",
            newline="\n",
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        version = str(report["blender_version"])
        image_hash, image_size = _hash_file(image_path)
        report_hash, report_size = _hash_file(report_path)
        log_hash, log_size = _hash_file(log_path)
    except BaseException:
        image_path.unlink(missing_ok=True)
        report_path.unlink(missing_ok=True)
        log_path.unlink(missing_ok=True)
        raise
    processor = Processor(name="blender_preview", version=f"1+blender-{version}")
    image = Artifact(
        artifact_id=f"local_preview_{number:03d}",
        role="local_preview",
        stage="review",
        format="png",
        path=image_relative,
        sha256=image_hash,
        size_bytes=image_size,
        derived_from=[source.artifact_id],
        processor=processor,
    )
    evidence = Artifact(
        artifact_id=f"local_preview_report_{number:03d}",
        role="local_preview_report",
        stage="review",
        format="json",
        path=report_relative,
        sha256=report_hash,
        size_bytes=report_size,
        derived_from=[source.artifact_id, image.artifact_id],
        processor=processor,
    )
    log = Artifact(
        artifact_id=f"local_preview_log_{number:03d}",
        role="local_preview_log",
        stage="review",
        format="log",
        path=log_relative,
        sha256=log_hash,
        size_bytes=log_size,
        derived_from=[source.artifact_id, image.artifact_id],
        processor=processor,
    )
    manifest.artifacts.extend([image, evidence, log])
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    repository.save(manifest, "preview.rendered", expected_revision=manifest.revision - 1)
    return image


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size
