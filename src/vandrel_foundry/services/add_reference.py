import os
import tempfile
from pathlib import Path

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path

MAX_REFERENCE_IMAGE_BYTES = 25 * 1024 * 1024
SUPPORTED_REFERENCE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def add_reference_image(
    config: FoundryConfig,
    asset_id: str,
    source: Path,
) -> RelativeManifestPath:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.workflow.state is not WorkflowState.DRAFT:
        raise FoundryError(f"Reference images may only be added in draft state: {asset_id}")
    if not source.is_file():
        raise FoundryError(f"Reference image does not exist: {source}")
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_REFERENCE_SUFFIXES:
        raise FoundryError("Reference image must be PNG, JPG, or JPEG.")
    size = source.stat().st_size
    if size <= 0 or size > MAX_REFERENCE_IMAGE_BYTES:
        raise FoundryError(
            f"Reference image size must be 1-{MAX_REFERENCE_IMAGE_BYTES} bytes: {size}"
        )
    try:
        with source.open("rb") as stream:
            signature = stream.read(8)
    except OSError as exc:
        raise FoundryError(f"Could not inspect reference image: {exc}") from exc
    if suffix == ".png" and signature != b"\x89PNG\r\n\x1a\n":
        raise FoundryError("Reference image extension is PNG, but its signature is invalid.")
    if suffix in {".jpg", ".jpeg"} and not signature.startswith(b"\xff\xd8\xff"):
        raise FoundryError("Reference image extension is JPEG, but its signature is invalid.")

    number = len(manifest.input.reference_images) + 1
    normalized_suffix = ".jpg" if suffix == ".jpeg" else suffix
    relative = RelativeManifestPath(f"input/references/reference_{number:03d}{normalized_suffix}")
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    destination = contained_path(asset_root, relative)
    if destination.exists():
        raise FoundryError(f"Reference destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    descriptor, raw_temporary = tempfile.mkstemp(
        prefix=f".{destination.name}-",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(raw_temporary)
    try:
        with source.open("rb") as input_stream, os.fdopen(descriptor, "wb") as output_stream:
            while chunk := input_stream.read(1024 * 1024):
                output_stream.write(chunk)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError as exc:
            raise FoundryError(f"Reference destination already exists: {destination}") from exc
    except OSError as exc:
        raise FoundryError(f"Could not copy reference image: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)

    manifest.input.kind = "image"
    manifest.input.reference_images.append(relative)
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    # Retain the copy if saving reports an error: the manifest replacement may
    # already have succeeded before a later journal write failed.
    repository.save(
        manifest,
        "input.reference_added",
        expected_revision=manifest.revision - 1,
    )
    return relative
