import hashlib
import os

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, utc_now
from vandrel_foundry.domain.meshy_native_canary import MeshyNativeIntakeProvenanceCorrection
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.add_meshy_native_animation_package import (
    ARCHIVE_ID,
    FBX_ID,
    REPORT_ID,
)
from vandrel_foundry.services.windows_acl_policy import apply_candidate_acl
from vandrel_foundry.storage.atomic import json_bytes
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path

PROCESSOR = Processor(name="meshy_native_intake_provenance_correction", version="1")


def supersede_meshy_native_intake_provenance(config: FoundryConfig, asset_id: str) -> Artifact:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.workflow.state is not WorkflowState.PROCESSED:
        raise FoundryError("Meshy native provenance correction requires a processed canary.")
    sources = {item.artifact_id: item for item in manifest.artifacts}
    archive = sources.get(ARCHIVE_ID)
    fbx = sources.get(FBX_ID)
    superseded = sources.get(REPORT_ID)
    if archive is None or fbx is None or superseded is None:
        raise FoundryError("Meshy native provenance correction requires the original intake roots.")
    asset_root = repository.asset_directory(asset_id)
    for item in (archive, fbx, superseded):
        _verify(contained_path(asset_root, item.path), item)
    number = sum(item.role == "meshy_native_intake_provenance" for item in manifest.artifacts) + 1
    artifact_id = f"meshy_native_intake_provenance_{number:03d}"
    relative = RelativeManifestPath(f"reports/meshy-native-intake-provenance-{number:03d}.json")
    path = contained_path(asset_root, relative)
    if path.exists():
        raise FoundryError("Meshy native provenance correction destination already exists.")
    apply_candidate_acl(config, path.parent)
    report = MeshyNativeIntakeProvenanceCorrection(
        schema="vandrel_foundry_meshy_native_intake_provenance/1.0",
        supersedes_artifact_id=REPORT_ID,
        source_union=sorted((ARCHIVE_ID, FBX_ID)),
        provider_task_metadata="not_inspected",
        license_metadata="not_inspected",
        external_provider_lookup="not_performed_by_intake_service",
        provider_download="not_performed_by_intake_service",
    )
    _write_new(path, json_bytes(report.model_dump(mode="json", by_alias=True)))
    digest, size = _hash(path)
    artifact = Artifact(
        artifact_id=artifact_id,
        role="meshy_native_intake_provenance",
        stage="source",
        format="json",
        path=relative,
        sha256=digest,
        size_bytes=size,
        derived_from=[ARCHIVE_ID, FBX_ID, REPORT_ID],
        processor=PROCESSOR,
    )
    source_revision = manifest.revision
    manifest.artifacts.append(artifact)
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    try:
        repository.save(
            manifest,
            "source.meshy_native_intake_provenance_superseded",
            expected_revision=source_revision,
        )
    except BaseException:
        live = repository.load(asset_id)
        present = next((item for item in live.artifacts if item.artifact_id == artifact_id), None)
        if live.revision == manifest.revision and present == artifact:
            diagnosis = repository.diagnose_pending_save(asset_id)
            if diagnosis.status in {"event_missing", "event_partial", "event_complete"}:
                repository.reconcile_pending_save(asset_id)
            return artifact
        if live.revision == source_revision and present is None:
            path.unlink(missing_ok=True)
        raise
    _verify(path, artifact)
    return artifact


def _hash(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _verify(path, artifact):
    if not path.is_file() or _hash(path) != (artifact.sha256, artifact.size_bytes):
        raise FoundryError(f"Meshy native provenance input changed: {artifact.artifact_id}")


def _write_new(path, value):
    with path.open("xb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
