import hashlib
import os
from pathlib import Path

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path

PASSTHROUGH_VERSION = "1"


def process_passthrough(config: FoundryConfig, asset_id: str) -> Artifact:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.workflow.state is not WorkflowState.DOWNLOADED:
        raise FoundryError(f"Pass-through processing requires downloaded state: {asset_id}")
    selected = manifest.generation.selected_task_key
    candidates = [
        artifact
        for artifact in manifest.artifacts
        if artifact.role == "source_model"
        and (selected is None or artifact.source_task_key == selected)
    ]
    if not candidates:
        raise FoundryError("No downloaded source model matches the selected output.")
    source = candidates[-1]
    if selected is None:
        selected = source.source_task_key
        manifest.generation.selected_task_key = selected

    asset_root = config.foundry.workspace_root / "assets" / asset_id
    source_path = contained_path(asset_root, source.path)
    if not source_path.is_file():
        raise FoundryError(f"Source artifact is missing: {source.path}")
    digest, size = _hash_file(source_path)
    if digest != source.sha256 or size != source.size_bytes:
        raise FoundryError(f"Source artifact hash or size changed: {source.artifact_id}")

    number = sum(item.role == "processed_model" for item in manifest.artifacts) + 1
    artifact_id = f"processed_glb_{number:03d}"
    relative = RelativeManifestPath(f"processed/passthrough/{artifact_id}.glb")
    destination = contained_path(asset_root, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        with source_path.open("rb") as source_stream, destination.open("xb") as output_stream:
            created = True
            while chunk := source_stream.read(1024 * 1024):
                output_stream.write(chunk)
            output_stream.flush()
            os.fsync(output_stream.fileno())
    except FileExistsError as exc:
        raise FoundryError(f"Processed artifact already exists: {relative}") from exc
    except OSError as exc:
        if created:
            destination.unlink(missing_ok=True)
        raise FoundryError(f"Could not promote pass-through artifact: {exc}") from exc
    promoted_digest, promoted_size = _hash_file(destination)
    if promoted_digest != digest or promoted_size != size:
        destination.unlink(missing_ok=True)
        raise FoundryError("Pass-through copy changed while it was being created.")

    artifact = Artifact(
        artifact_id=artifact_id,
        role="processed_model",
        stage="processed",
        format="glb",
        path=relative,
        sha256=digest,
        size_bytes=size,
        derived_from=[source.artifact_id],
        source_task_key=selected,
        processor=Processor(name="passthrough", version=PASSTHROUGH_VERSION),
    )
    manifest.artifacts.append(artifact)
    manifest.workflow.state = WorkflowState.PROCESSED
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    # Keep the immutable output if persistence reports an error because the
    # manifest replacement may already have committed before event journaling.
    repository.save(
        manifest,
        "asset.processed",
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
