import hashlib
import os
import tempfile
from pathlib import Path

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.inspect_glb import inspect_glb
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path

MAX_EXTERNAL_GLB_BYTES = 4_000_000_000
IMPORTER_VERSION = "1"


def add_external_glb(
    config: FoundryConfig,
    asset_id: str,
    source: Path,
) -> Artifact:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.workflow.state is not WorkflowState.DRAFT:
        raise FoundryError(f"External sources may only be added in draft state: {asset_id}")
    if not source.is_file() or source.suffix.lower() != ".glb":
        raise FoundryError("External source must be an existing .glb file.")
    size = source.stat().st_size
    if size <= 0 or size > MAX_EXTERNAL_GLB_BYTES:
        raise FoundryError(f"External GLB size must be 1-{MAX_EXTERNAL_GLB_BYTES} bytes: {size}")
    inspect_glb(source)

    number = sum(item.role == "source_model" for item in manifest.artifacts) + 1
    artifact_id = f"source_glb_{number:03d}"
    relative = RelativeManifestPath(f"source/external/{artifact_id}.glb")
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    destination = contained_path(asset_root, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_value = tempfile.mkstemp(
        prefix=f".{artifact_id}-",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_value)
    try:
        digest = hashlib.sha256()
        copied_size = 0
        with os.fdopen(descriptor, "wb") as output_stream, source.open("rb") as input_stream:
            while chunk := input_stream.read(1024 * 1024):
                output_stream.write(chunk)
                digest.update(chunk)
                copied_size += len(chunk)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError as exc:
            raise FoundryError(f"External source destination exists: {relative}") from exc
    except OSError as exc:
        raise FoundryError(f"Could not copy external GLB: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)
    if copied_size != size:
        destination.unlink(missing_ok=True)
        raise FoundryError("External GLB changed while it was being copied.")
    copied_digest, verified_size = _hash_file(destination)
    if copied_digest != digest.hexdigest() or verified_size != copied_size:
        destination.unlink(missing_ok=True)
        raise FoundryError("Copied external GLB failed verification.")

    artifact = Artifact(
        artifact_id=artifact_id,
        role="source_model",
        stage="source",
        format="glb",
        path=relative,
        sha256=copied_digest,
        size_bytes=verified_size,
        derived_from=[],
        processor=Processor(name="external_glb_import", version=IMPORTER_VERSION),
    )
    manifest.artifacts.append(artifact)
    manifest.input.kind = "external"
    manifest.workflow.state = WorkflowState.DOWNLOADED
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    repository.save(
        manifest,
        "source.external_added",
        expected_revision=manifest.revision - 1,
    )
    return artifact


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size
