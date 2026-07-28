import hashlib
import json
import os
import shutil
from pathlib import Path

from PIL import Image, ImageDraw

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.validate_godot import ProcessRunner, run_bounded_process
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path

ALLOWED_STATES = {
    WorkflowState.PROCESSED,
    WorkflowState.REVIEW,
    WorkflowState.APPROVED,
}


def render_animation_samples(
    config: FoundryConfig,
    asset_id: str,
    runner: ProcessRunner | None = None,
) -> Artifact:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.workflow.state not in ALLOWED_STATES:
        raise FoundryError(f"Animation sample rendering requires a processed asset: {asset_id}")
    executable = config.tools.blender_executable
    if executable is None or not executable.is_absolute() or not executable.is_file():
        raise FoundryError("Configure tools.blender_executable as an existing absolute file.")
    sources = [
        item
        for item in manifest.artifacts
        if item.role == "processed_model" and item.format == "glb"
    ]
    if not sources:
        raise FoundryError(f"No processed GLB exists for animation samples: {asset_id}")
    source = sources[-1]
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    source_path = contained_path(asset_root, source.path)
    _verify_artifact(source_path, source)

    number = sum(item.role == "animation_sample_contact_sheet" for item in manifest.artifacts) + 1
    directory_relative = RelativeManifestPath(f"preview/animation-samples-{number:03d}")
    report_relative = RelativeManifestPath(f"reports/animation-samples-{number:03d}.json")
    log_relative = RelativeManifestPath(f"reports/animation-samples-{number:03d}.log")
    directory = contained_path(asset_root, directory_relative)
    report_path = contained_path(asset_root, report_relative)
    log_path = contained_path(asset_root, log_relative)
    if directory.exists() or report_path.exists() or log_path.exists():
        raise FoundryError("Animation sample output or evidence destination already exists.")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).parents[1] / "blender" / "render_animation_samples.py"
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
        str(directory),
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
            raise FoundryError("Bounded Blender animation sample rendering failed.")
        report_data = json.loads(report_path.read_text(encoding="utf-8"))
        samples = report_data.get("samples")
        if not isinstance(samples, list) or not samples:
            raise FoundryError("Animation sample report contains no samples.")
        sample_paths = []
        for sample in samples:
            image_name = sample.get("image") if isinstance(sample, dict) else None
            if not isinstance(image_name, str) or Path(image_name).name != image_name:
                raise FoundryError("Animation sample report contains an unsafe image path.")
            path = directory / image_name
            if path.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
                raise FoundryError("Animation sample output is not a PNG.")
            sample_paths.append(path)
        contact_sheet = directory / "contact-sheet.png"
        _build_contact_sheet(sample_paths, samples, contact_sheet)
        report_data["contact_sheet"] = contact_sheet.name
        report_data["visual_acceptance"] = False
        report_data["visual_acceptance_note"] = (
            "Samples are evidence only until explicitly reviewed."
        )
        _write_json(report_path, report_data)
        _write_new_text(
            log_path,
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}\n",
        )
    except BaseException:
        if directory.exists():
            shutil.rmtree(directory)
        report_path.unlink(missing_ok=True)
        log_path.unlink(missing_ok=True)
        raise

    version = str(report_data["blender_version"])
    processor = Processor(name="blender_animation_samples", version=f"1+blender-{version}")
    artifacts = []
    for index, (sample, path) in enumerate(zip(samples, sample_paths), start=1):
        digest, size = _hash_file(path)
        artifacts.append(
            Artifact(
                artifact_id=f"animation_sample_{number:03d}_{index:03d}",
                role="animation_sample_preview",
                stage="review",
                format="png",
                path=RelativeManifestPath(f"{directory_relative}/{path.name}"),
                sha256=digest,
                size_bytes=size,
                derived_from=[source.artifact_id],
                processor=processor,
            )
        )
    contact_hash, contact_size = _hash_file(contact_sheet)
    contact_artifact = Artifact(
        artifact_id=f"animation_sample_contact_sheet_{number:03d}",
        role="animation_sample_contact_sheet",
        stage="review",
        format="png",
        path=RelativeManifestPath(f"{directory_relative}/{contact_sheet.name}"),
        sha256=contact_hash,
        size_bytes=contact_size,
        derived_from=[source.artifact_id, *(item.artifact_id for item in artifacts)],
        processor=processor,
    )
    report_hash, report_size = _hash_file(report_path)
    report_artifact = Artifact(
        artifact_id=f"animation_sample_report_{number:03d}",
        role="animation_sample_report",
        stage="review",
        format="json",
        path=report_relative,
        sha256=report_hash,
        size_bytes=report_size,
        derived_from=[source.artifact_id, contact_artifact.artifact_id],
        processor=processor,
    )
    log_hash, log_size = _hash_file(log_path)
    log_artifact = Artifact(
        artifact_id=f"animation_sample_log_{number:03d}",
        role="animation_sample_log",
        stage="review",
        format="log",
        path=log_relative,
        sha256=log_hash,
        size_bytes=log_size,
        derived_from=[source.artifact_id, contact_artifact.artifact_id],
        processor=processor,
    )
    manifest.artifacts.extend([*artifacts, contact_artifact, report_artifact, log_artifact])
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    repository.save(
        manifest,
        "preview.animation_samples_rendered",
        expected_revision=manifest.revision - 1,
    )
    return contact_artifact


def _build_contact_sheet(paths: list[Path], samples: list[dict], destination: Path) -> None:
    columns = 3
    tile_width = 384
    tile_height = 416
    rows = (len(paths) + columns - 1) // columns
    sheet = Image.new("RGBA", (columns * tile_width, rows * tile_height), (20, 20, 20, 255))
    draw = ImageDraw.Draw(sheet)
    for index, (path, sample) in enumerate(zip(paths, samples)):
        with Image.open(path) as value:
            image = value.convert("RGBA")
            x = index % columns * tile_width
            y = index // columns * tile_height
            sheet.alpha_composite(image, (x, y))
        label = f"{sample['animation']}  frame {sample['frame']}"
        draw.text((x + 8, y + 390), label, fill=(240, 240, 240, 255))
    sheet.save(destination, format="PNG")


def _verify_artifact(path: Path, artifact: Artifact) -> None:
    digest, size = _hash_file(path)
    if digest != artifact.sha256 or size != artifact.size_bytes:
        raise FoundryError(f"Animation sample input changed: {artifact.artifact_id}")


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")


def _write_new_text(path: Path, value: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
