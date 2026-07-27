import hashlib
import json
import os
import tempfile
from pathlib import Path

from PIL import Image

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, utc_now
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path

PALETTE = {
    "skin": (255, 0, 0),
    "fur_hair": (0, 255, 0),
    "cloth": (0, 0, 255),
    "accessories": (255, 255, 255),
}
PROCESSOR_VERSION = "1"
MAXIMUM_MEAN_RGB_ERROR = 32.0
MINIMUM_CLASS_FRACTION = 0.001


def quantize_semantic_mask(config: FoundryConfig, asset_id: str) -> Artifact:
    """Convert the latest semantic base color to a strict four-color ID mask."""
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    sources = [item for item in manifest.artifacts if item.role == "semantic_mask_source"]
    if not sources:
        raise FoundryError("No downloaded semantic-mask source texture is available.")
    source = sources[-1]
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    source_path = contained_path(asset_root, source.path)
    _verify(source_path, source)

    number = sum(item.role == "semantic_id_mask" for item in manifest.artifacts) + 1
    mask_id = f"semantic_id_mask_{number:03d}"
    report_id = f"semantic_mask_report_{number:03d}"
    mask_relative = RelativeManifestPath(f"masks/{mask_id}.png")
    report_relative = RelativeManifestPath(f"reports/{report_id}.json")
    mask_path = contained_path(asset_root, mask_relative)
    report_path = contained_path(asset_root, report_relative)
    if mask_path.exists() or report_path.exists():
        raise FoundryError("Semantic mask output already exists.")
    mask_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    counts = {name: 0 for name in PALETTE}
    ambiguous = 0
    total_error = 0.0
    with Image.open(source_path) as opened:
        image = opened.convert("RGBA")
        output = Image.new("RGBA", image.size)
        output_pixels = []
        source_pixels = image.load()
        for y in range(image.height):
            for x in range(image.width):
                red, green, blue, alpha = source_pixels[x, y]
                distances = sorted(
                    (
                        (
                            (red - target[0]) ** 2
                            + (green - target[1]) ** 2
                            + (blue - target[2]) ** 2,
                            name,
                            target,
                        )
                        for name, target in PALETTE.items()
                    ),
                    key=lambda item: item[0],
                )
                distance, name, target = distances[0]
                counts[name] += 1
                total_error += distance**0.5
                if distances[1][0] - distance < 4096:
                    ambiguous += 1
                output_pixels.append((*target, alpha))
        output.putdata(output_pixels)
        _save_new_png(output, mask_path)

    pixel_count = sum(counts.values())
    mean_rgb_error = total_error / pixel_count
    class_fractions = {name: count / pixel_count for name, count in counts.items()}
    palette_fidelity_passed = mean_rgb_error <= MAXIMUM_MEAN_RGB_ERROR
    class_coverage_passed = all(
        fraction >= MINIMUM_CLASS_FRACTION for fraction in class_fractions.values()
    )
    report = {
        "schema_version": 1,
        "asset_id": asset_id,
        "source_artifact_id": source.artifact_id,
        "source_sha256": source.sha256,
        "mask_artifact_id": mask_id,
        "palette": {name: list(color) for name, color in PALETTE.items()},
        "pixel_counts": counts,
        "class_fractions": class_fractions,
        "ambiguous_pixel_fraction": ambiguous / pixel_count,
        "mean_rgb_error": mean_rgb_error,
        "maximum_mean_rgb_error": MAXIMUM_MEAN_RGB_ERROR,
        "minimum_class_fraction": MINIMUM_CLASS_FRACTION,
        "palette_fidelity_passed": palette_fidelity_passed,
        "class_coverage_passed": class_coverage_passed,
        "usable_for_material_authoring": palette_fidelity_passed and class_coverage_passed,
        "interpretation": (
            "Nearest-palette quantization only. Inspect the source and mask before using "
            "the mask for material authoring."
        ),
    }
    try:
        _write_new_json(report_path, report)
    except BaseException:
        mask_path.unlink(missing_ok=True)
        raise

    mask_artifact = _artifact(
        mask_id,
        "semantic_id_mask",
        "png",
        mask_relative,
        mask_path,
        source,
    )
    report_artifact = _artifact(
        report_id,
        "semantic_mask_report",
        "json",
        report_relative,
        report_path,
        source,
    )
    manifest.artifacts.extend([mask_artifact, report_artifact])
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    repository.save(
        manifest,
        "artifact.semantic_mask_quantized",
        expected_revision=manifest.revision - 1,
    )
    return mask_artifact


def _save_new_png(image: Image.Image, destination: Path) -> None:
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f"{destination.stem}-",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(descriptor)
    temporary = Path(raw_path)
    try:
        image.save(temporary, format="PNG", optimize=True)
        with temporary.open("rb+") as stream:
            os.fsync(stream.fileno())
        os.link(temporary, destination)
    except FileExistsError as exc:
        raise FoundryError(f"Semantic mask destination already exists: {destination}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _write_new_json(destination: Path, value: dict[str, object]) -> None:
    encoded = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        with destination.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise FoundryError(f"Semantic report destination already exists: {destination}") from exc


def _artifact(
    artifact_id: str,
    role: str,
    file_format: str,
    relative: RelativeManifestPath,
    path: Path,
    source: Artifact,
) -> Artifact:
    return Artifact(
        artifact_id=artifact_id,
        role=role,
        stage="analysis",
        format=file_format,
        path=relative,
        sha256=_sha256(path),
        size_bytes=path.stat().st_size,
        derived_from=[source.artifact_id],
        source_task_key=source.source_task_key,
        processor=Processor(name="semantic_palette_quantizer", version=PROCESSOR_VERSION),
    )


def _verify(path: Path, artifact: Artifact) -> None:
    try:
        size = path.stat().st_size
        digest = _sha256(path)
    except OSError as exc:
        raise FoundryError(
            f"Could not verify semantic source {artifact.artifact_id}: {exc}"
        ) from exc
    if size != artifact.size_bytes or digest != artifact.sha256:
        raise FoundryError(f"Semantic source no longer matches manifest: {artifact.artifact_id}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
