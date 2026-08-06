import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.domain.workflow_policy import transition_workflow
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath


def add_compound_creature_sources(
    config: FoundryConfig,
    asset_id: str,
    mesh_source: Path,
    material_dependencies: list[Path],
    rig_animation_donor: Path,
) -> list[Artifact]:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    existing = _committed_artifacts(manifest)
    if existing:
        _verify_retry_inputs(
            repository.asset_directory(asset_id),
            existing,
            mesh_source,
            material_dependencies,
            rig_animation_donor,
        )
        return existing
    if manifest.asset.lane != "creature" or manifest.workflow.state is not WorkflowState.DRAFT:
        raise FoundryError("Compound source intake requires a draft creature candidate.")
    values = [mesh_source, *material_dependencies, rig_animation_donor]
    if not material_dependencies or len({path.resolve() for path in values}) != len(values):
        raise FoundryError("Compound source intake requires distinct mesh, material, and donor files.")
    allowed = [{".fbx", ".glb", ".gltf"}, {".png", ".jpg", ".jpeg"}, {".glb", ".gltf"}]
    if (
        not mesh_source.is_file()
        or mesh_source.suffix.lower() not in allowed[0]
        or any(not item.is_file() or item.suffix.lower() not in allowed[1] for item in material_dependencies)
        or not rig_animation_donor.is_file()
        or rig_animation_donor.suffix.lower() not in allowed[2]
    ):
        raise FoundryError("Compound source intake contains a missing or unsupported file.")
    asset_root = repository.asset_directory(asset_id)
    destination = asset_root / "source" / "compound_roots_001"
    if destination.exists():
        raise FoundryError("Compound source root destination already exists.")
    temporary = Path(tempfile.mkdtemp(prefix=".compound-roots-", dir=asset_root / "source"))
    try:
        copied = []
        for source in values:
            target = temporary / source.name
            if target.exists():
                raise FoundryError("Compound source filenames must be unique.")
            with source.open("rb") as input_stream, target.open("xb") as output_stream:
                shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
                output_stream.flush(); os.fsync(output_stream.fileno())
            if _hash(source) != _hash(target):
                raise FoundryError(f"Compound source copy changed: {source.name}")
            copied.append(target)
        os.rename(temporary, destination)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    processor = Processor(name="local_compound_source_intake", version="1")
    artifacts = []
    roles = ["external_source_model", *("source_texture" for _ in material_dependencies), "external_rig_animation_donor"]
    ids = ["compound_mesh_root_001", *(f"compound_material_root_{index:03d}" for index in range(1, len(material_dependencies) + 1)), "compound_rig_donor_root_001"]
    final_paths = [destination / source.name for source in values]
    for artifact_id, role, path in zip(ids, roles, final_paths, strict=True):
        digest, size = _hash(path)
        artifacts.append(Artifact(
            artifact_id=artifact_id, role=role, stage="source",
            format=path.suffix.lower().removeprefix("."),
            path=RelativeManifestPath(f"source/compound_roots_001/{path.name}"),
            sha256=digest, size_bytes=size, derived_from=[], processor=processor,
        ))
    source_revision = manifest.revision
    manifest.artifacts.extend(artifacts)
    manifest.input.kind = "external"
    transition_workflow(manifest, WorkflowState.DOWNLOADED)
    manifest.revision += 1; manifest.asset.updated_at = utc_now()
    try:
        repository.save(manifest, "source.compound_roots_added", expected_revision=manifest.revision - 1)
    except BaseException:
        live = repository.load(asset_id)
        if _is_exact_target(live, manifest.revision, artifacts):
            diagnosis = repository.diagnose_pending_save(asset_id)
            if diagnosis.status in {"event_missing", "event_partial", "event_complete"}:
                repository.reconcile_pending_save(asset_id)
            return artifacts
        if live.revision == source_revision and not _references(live, artifacts):
            shutil.rmtree(destination, ignore_errors=True)
        raise
    return artifacts


def _hash(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256(); size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk); size += len(chunk)
    return digest.hexdigest(), size


def _committed_artifacts(manifest) -> list[Artifact]:
    ids = {"compound_mesh_root_001", "compound_rig_donor_root_001"}
    found = [
        item
        for item in manifest.artifacts
        if item.artifact_id in ids or item.artifact_id.startswith("compound_material_root_")
    ]
    if not found:
        return []
    if manifest.workflow.state is not WorkflowState.DOWNLOADED:
        raise FoundryError("Existing compound roots are not a committed intake target.")
    return found


def _verify_retry_inputs(
    asset_root: Path,
    artifacts: list[Artifact],
    mesh: Path,
    materials: list[Path],
    donor: Path,
) -> None:
    expected = [mesh, *materials, donor]
    if len(artifacts) != len(expected):
        raise FoundryError("Existing compound root union does not match retry inputs.")
    by_name = {Path(str(item.path)).name: item for item in artifacts}
    if set(by_name) != {item.name for item in expected}:
        raise FoundryError("Existing compound root filenames do not match retry inputs.")
    for path in expected:
        digest, size = _hash(path)
        artifact = by_name[path.name]
        if (digest, size) != (artifact.sha256, artifact.size_bytes):
            raise FoundryError("Existing compound root bytes do not match retry inputs.")
        destination = asset_root / Path(str(artifact.path))
        if not destination.is_file() or _hash(destination) != (
            artifact.sha256,
            artifact.size_bytes,
        ):
            raise FoundryError("Manifest-owned compound root bytes are missing or changed.")


def _is_exact_target(manifest, revision: int, artifacts: list[Artifact]) -> bool:
    return manifest.revision == revision and _references(manifest, artifacts)


def _references(manifest, artifacts: list[Artifact]) -> bool:
    by_id = {item.artifact_id: item for item in manifest.artifacts}
    return all(
        by_id.get(expected.artifact_id) is not None
        and by_id[expected.artifact_id].model_dump(mode="json")
        == expected.model_dump(mode="json")
        for expected in artifacts
    )
