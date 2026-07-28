import hashlib
import json
import shutil
from pathlib import Path

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath


def record_cross_render_evidence(
    config: FoundryConfig,
    asset_id: str,
    evidence_files: list[Path],
) -> list[Artifact]:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.workflow.state not in {WorkflowState.BLOCKED, WorkflowState.REVIEW}:
        raise FoundryError("Cross-render evidence requires a blocked or review candidate.")
    processed = [item for item in manifest.artifacts if item.role == "processed_model"]
    if not processed:
        raise FoundryError("Cross-render evidence requires a processed model.")
    temp_root = (config.foundry.workspace_root / "temp").resolve()
    unique_files: list[Path] = []
    for source in evidence_files:
        resolved = source.resolve()
        if not resolved.is_file() or not resolved.is_relative_to(temp_root):
            raise FoundryError("Cross-render evidence must be a file under workspace temp.")
        if resolved.name in {item.name for item in unique_files}:
            raise FoundryError("Cross-render evidence filenames must be unique.")
        unique_files.append(resolved)
    if not unique_files:
        raise FoundryError("Cross-render evidence requires at least one file.")

    number = sum(item.role == "cross_render_evidence_index" for item in manifest.artifacts) + 1
    relative_directory = Path("reports") / f"cross-render-{number:03d}"
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    destination = asset_root / relative_directory
    destination.mkdir(parents=True, exist_ok=False)
    processor = Processor(name="cross_render_evidence_import", version="1")
    artifacts: list[Artifact] = []
    try:
        for sequence, source in enumerate(unique_files, start=1):
            target = destination / source.name
            with source.open("rb") as source_stream, target.open("xb") as target_stream:
                shutil.copyfileobj(source_stream, target_stream, length=1024 * 1024)
                target_stream.flush()
            digest, size = _hash_file(target)
            artifacts.append(
                Artifact(
                    artifact_id=f"cross_render_evidence_{number:03d}_{sequence:03d}",
                    role="cross_render_evidence",
                    stage="validation",
                    format=target.suffix.lstrip(".").lower() or "bin",
                    path=RelativeManifestPath(target.relative_to(asset_root).as_posix()),
                    sha256=digest,
                    size_bytes=size,
                    derived_from=[processed[-1].artifact_id],
                    processor=processor,
                )
            )
        index_path = destination / "index.json"
        index_data = {
            "schema_version": 1,
            "asset_id": asset_id,
            "processed_model": {
                "artifact_id": processed[-1].artifact_id,
                "sha256": processed[-1].sha256,
            },
            "evidence": [
                {
                    "artifact_id": item.artifact_id,
                    "path": str(item.path),
                    "sha256": item.sha256,
                    "size_bytes": item.size_bytes,
                }
                for item in artifacts
            ],
            "result_is": "cross-render evidence",
            "result_is_not": "approval, publication, or repaired output",
        }
        index_path.write_text(
            json.dumps(index_data, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        digest, size = _hash_file(index_path)
        index = Artifact(
            artifact_id=f"cross_render_evidence_index_{number:03d}",
            role="cross_render_evidence_index",
            stage="validation",
            format="json",
            path=RelativeManifestPath(index_path.relative_to(asset_root).as_posix()),
            sha256=digest,
            size_bytes=size,
            derived_from=[item.artifact_id for item in artifacts],
            processor=processor,
        )
        manifest.artifacts.extend([*artifacts, index])
        manifest.revision += 1
        manifest.asset.updated_at = utc_now()
        repository.save(
            manifest,
            "asset.cross_render_evidence_imported",
            expected_revision=manifest.revision - 1,
        )
        return [*artifacts, index]
    except BaseException:
        if destination.exists():
            shutil.rmtree(destination)
        raise


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size
