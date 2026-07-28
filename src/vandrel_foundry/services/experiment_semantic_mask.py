from __future__ import annotations

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
from vandrel_foundry.services.quantize_semantic_mask import PALETTE
from vandrel_foundry.services.validate_godot import ProcessRunner, run_bounded_process
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path
from vandrel_foundry.storage.provider_evidence import write_new_json_evidence

PROCESSOR_VERSION = "1"
VARIANTS = ("baseline", "skin", "fur_hair", "cloth", "accessories")
SAFE_ENVIRONMENT_KEYS = {
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


def experiment_semantic_mask(
    config: FoundryConfig,
    asset_id: str,
    candidate_mask: Path,
    runner: ProcessRunner | None = None,
) -> Artifact:
    """Record and render an immutable, offline semantic-mask candidate."""
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.workflow.state not in {
        WorkflowState.PROCESSED,
        WorkflowState.REVIEW,
        WorkflowState.APPROVED,
    }:
        raise FoundryError(
            f"Semantic-mask experiments require processed, review, or approved state: {asset_id}"
        )
    executable = config.tools.blender_executable
    if executable is None or not executable.is_absolute() or not executable.is_file():
        raise FoundryError("Configure tools.blender_executable as an existing absolute file.")
    sources = [item for item in manifest.artifacts if item.role == "processed_model"]
    if not sources:
        raise FoundryError(f"No processed GLB exists for semantic-mask experiments: {asset_id}")
    source = sources[-1]
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    source_path = contained_path(asset_root, source.path)
    _verify(source_path, source)
    mask_facts = _inspect_mask(candidate_mask)

    number = sum(item.role == "semantic_mask_experiment_report" for item in manifest.artifacts) + 1
    experiment_name = f"semantic-mask-experiment-{number:03d}"
    mask_relative = RelativeManifestPath(f"masks/{experiment_name}.png")
    mask_path = contained_path(asset_root, mask_relative)
    preview_relative = RelativeManifestPath(f"preview/{experiment_name}")
    preview_root = contained_path(asset_root, preview_relative)
    report_relative = RelativeManifestPath(f"reports/{experiment_name}.json")
    log_relative = RelativeManifestPath(f"reports/{experiment_name}.log")
    report_path = contained_path(asset_root, report_relative)
    log_path = contained_path(asset_root, log_relative)
    measurements_path = preview_root / ".measurements.json"
    if any(path.exists() for path in (mask_path, preview_root, report_path, log_path)):
        raise FoundryError(f"Semantic-mask experiment output already exists: {experiment_name}")
    preview_root.mkdir(parents=True)
    mask_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _copy_new(candidate_mask, mask_path)
        script = Path(__file__).parents[1] / "blender" / "experiment_semantic_mask.py"
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
            str(preview_root),
            str(measurements_path),
        ]
        safe_environment = {
            key: value for key, value in os.environ.items() if key.upper() in SAFE_ENVIRONMENT_KEYS
        }
        result = (runner or run_bounded_process)(
            arguments,
            asset_root,
            safe_environment,
            config.tools.blender_timeout_seconds,
            config.tools.maximum_output_bytes,
        )
        if result.return_code != 0 or result.timed_out or result.output_limited:
            raise FoundryError("Bounded Blender semantic-mask experiment failed.")
        measurements = json.loads(measurements_path.read_text(encoding="utf-8"))
        measurements_path.unlink()
        if measurements.get("variants") != list(VARIANTS):
            raise FoundryError("Blender semantic-mask experiment reported unexpected variants.")
        variant_paths = [preview_root / f"{name}.png" for name in VARIANTS]
        for path in variant_paths:
            _require_png(path)
        contact_sheet_path = preview_root / "contact-sheet.png"
        _write_contact_sheet(variant_paths, contact_sheet_path)
        _verify(source_path, source)
        report = {
            "schema_version": 1,
            "asset_id": asset_id,
            "source_artifact_id": source.artifact_id,
            "source_sha256": source.sha256,
            "candidate_mask_sha256": _hash_file(mask_path)[0],
            "processor": "blender_semantic_mask_experiment",
            "processor_version": PROCESSOR_VERSION,
            "variants": list(VARIANTS),
            "mask_facts": mask_facts,
            "blender_version": measurements["blender_version"],
            "resolution": measurements["resolution"],
            "mask_sampling": measurements["mask_sampling"],
            "usable_for_material_authoring": False,
            "interpretation": (
                "The strict palette and coverage checks validate file mechanics only. "
                "The isolation previews must be reviewed for semantic crossing before "
                "the mask can be accepted for material authoring."
            ),
        }
        write_new_json_evidence(report_path, report)
        _write_new_log(log_path, result.stdout, result.stderr)
    except BaseException:
        mask_path.unlink(missing_ok=True)
        shutil.rmtree(preview_root, ignore_errors=True)
        report_path.unlink(missing_ok=True)
        log_path.unlink(missing_ok=True)
        raise

    processor = Processor(
        name="blender_semantic_mask_experiment",
        version=f"{PROCESSOR_VERSION}+blender-{measurements['blender_version']}",
    )
    artifacts = [
        _artifact(
            f"semantic_mask_candidate_{number:03d}",
            "semantic_mask_candidate",
            "png",
            mask_relative,
            mask_path,
            source,
            processor,
        )
    ]
    for name, path in zip(VARIANTS, variant_paths, strict=True):
        artifacts.append(
            _artifact(
                f"semantic_mask_variant_{name}_{number:03d}",
                "semantic_mask_variant_preview",
                "png",
                RelativeManifestPath(f"{preview_relative}/{name}.png"),
                path,
                source,
                processor,
            )
        )
    artifacts.extend(
        [
            _artifact(
                f"semantic_mask_contact_sheet_{number:03d}",
                "semantic_mask_experiment_contact_sheet",
                "png",
                RelativeManifestPath(f"{preview_relative}/contact-sheet.png"),
                contact_sheet_path,
                source,
                processor,
            ),
            _artifact(
                f"semantic_mask_experiment_report_{number:03d}",
                "semantic_mask_experiment_report",
                "json",
                report_relative,
                report_path,
                source,
                processor,
            ),
            _artifact(
                f"semantic_mask_experiment_log_{number:03d}",
                "semantic_mask_experiment_log",
                "log",
                log_relative,
                log_path,
                source,
                processor,
            ),
        ]
    )
    manifest.artifacts.extend(artifacts)
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    repository.save(
        manifest,
        "semantic_mask.experiment_completed",
        expected_revision=manifest.revision - 1,
    )
    return artifacts[-3]


def _inspect_mask(path: Path) -> dict[str, object]:
    try:
        with Image.open(path) as opened:
            image = opened.convert("RGB")
            counts = {name: 0 for name in PALETTE}
            invalid = 0
            reverse = {color: name for name, color in PALETTE.items()}
            raw_pixels = image.tobytes()
            for offset in range(0, len(raw_pixels), 3):
                pixel = tuple(raw_pixels[offset : offset + 3])
                name = reverse.get(pixel)
                if name is None:
                    invalid += 1
                else:
                    counts[name] += 1
            width, height = image.size
    except (OSError, ValueError) as exc:
        raise FoundryError(f"Could not read semantic-mask candidate: {exc}") from exc
    if invalid:
        raise FoundryError(
            f"Semantic-mask candidate contains {invalid} pixels outside the strict palette."
        )
    pixel_count = width * height
    fractions = {name: count / pixel_count for name, count in counts.items()}
    if any(count == 0 for count in counts.values()):
        raise FoundryError("Semantic-mask candidate must contain all four palette classes.")
    return {
        "width": width,
        "height": height,
        "palette": {name: list(color) for name, color in PALETTE.items()},
        "pixel_counts": counts,
        "class_fractions": fractions,
        "strict_palette_passed": True,
    }


def _copy_new(source: Path, destination: Path) -> None:
    try:
        with source.open("rb") as input_stream, destination.open("xb") as output_stream:
            shutil.copyfileobj(input_stream, output_stream)
            output_stream.flush()
            os.fsync(output_stream.fileno())
    except FileExistsError as exc:
        raise FoundryError(f"Semantic-mask destination already exists: {destination}") from exc
    except OSError as exc:
        raise FoundryError(f"Could not copy semantic-mask candidate: {exc}") from exc


def _write_contact_sheet(paths: list[Path], destination: Path) -> None:
    images = []
    for path in paths:
        with Image.open(path) as opened:
            images.append(opened.convert("RGBA"))
    width = max(image.width for image in images)
    height = max(image.height for image in images)
    label_height = 32
    sheet = Image.new("RGBA", (width * 3, (height + label_height) * 2), (28, 28, 28, 255))
    draw = ImageDraw.Draw(sheet)
    for index, (name, image) in enumerate(zip(VARIANTS, images, strict=True)):
        left = (index % 3) * width
        top = (index // 3) * (height + label_height)
        sheet.paste(image, (left, top), image)
        draw.text((left + 10, top + height + 8), name.replace("_", " "), fill="white")
    try:
        with destination.open("xb") as stream:
            sheet.convert("RGB").save(stream, format="PNG", optimize=True)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise FoundryError(f"Semantic-mask contact sheet already exists: {destination}") from exc


def _write_new_log(path: Path, stdout: str, stderr: str) -> None:
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(f"--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}\n")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise FoundryError(f"Semantic-mask log already exists: {path}") from exc


def _require_png(path: Path) -> None:
    try:
        if path.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            raise FoundryError(f"Semantic-mask experiment output is not a PNG: {path.name}")
    except OSError as exc:
        raise FoundryError(f"Could not read semantic-mask output {path.name}: {exc}") from exc


def _artifact(
    artifact_id: str,
    role: str,
    file_format: str,
    relative: RelativeManifestPath,
    path: Path,
    source: Artifact,
    processor: Processor,
) -> Artifact:
    digest, size = _hash_file(path)
    return Artifact(
        artifact_id=artifact_id,
        role=role,
        stage="analysis",
        format=file_format,
        path=relative,
        sha256=digest,
        size_bytes=size,
        derived_from=[source.artifact_id],
        source_task_key=source.source_task_key,
        processor=processor,
    )


def _verify(path: Path, artifact: Artifact) -> None:
    digest, size = _hash_file(path)
    if digest != artifact.sha256 or size != artifact.size_bytes:
        raise FoundryError(f"Semantic-mask experiment input changed: {artifact.artifact_id}")


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise FoundryError(f"Could not hash semantic-mask file: {exc}") from exc
    return digest.hexdigest(), size
