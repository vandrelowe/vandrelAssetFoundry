import hashlib
import os
import shutil
from pathlib import Path

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.custody import PortableCustodyPath
from vandrel_foundry.domain.custody_assertion import (
    CUSTODY_SCHEMA_V1_3,
    current_source_inputs,
    evidence_freshness_sha256,
    user_local_use_register_sha256,
    user_local_use_semantic_sha256,
)
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import (
    Artifact,
    CustodyAssertion,
    CustodyLicenseEvidence,
    CustodySourceContribution,
    utc_now,
)
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path

POLICY_SCHEMA = "vandrel_foundry_user_local_use_policy/1.0"
REGISTER_SCHEMA = "vandrel_foundry_user_local_use_declaration/1.0"


def bind_user_local_use_custody(
    config: FoundryConfig,
    asset_id: str,
    declaration_path: Path,
    meshy_artifact_ids: list[str],
    quaternius_artifact_ids: list[str],
) -> CustodyAssertion:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.custody is not None and manifest.custody.assessment_status == "evaluated":
        return _verify_committed_retry(
            repository.asset_directory(asset_id),
            manifest,
            declaration_path,
            meshy_artifact_ids,
            quaternius_artifact_ids,
        )
    current = current_source_inputs(manifest)
    expected_ids = {item.artifact_id for item in current}
    declared_ids = {*meshy_artifact_ids, *quaternius_artifact_ids}
    if (
        not meshy_artifact_ids or not quaternius_artifact_ids
        or len(declared_ids) != len(meshy_artifact_ids) + len(quaternius_artifact_ids)
        or declared_ids != expected_ids
    ):
        raise FoundryError("User local-use custody assignments must equal the exact root union.")
    content = declaration_path.read_bytes()
    declaration_hash = hashlib.sha256(content).hexdigest()
    relative = RelativeManifestPath(f"custody/evidence/user-local-use-{declaration_hash[:12]}.txt")
    destination = repository.asset_directory(asset_id) / relative
    if destination.exists():
        raise FoundryError("User local-use evidence destination already exists.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    try:
        with declaration_path.open("rb") as source, temporary.open("xb") as output:
            shutil.copyfileobj(source, output); output.flush(); os.fsync(output.fileno())
        os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    evidence_id = "custody_license_evidence_001"
    evidence_artifact = Artifact(
        artifact_id=evidence_id, role="custody_license_evidence", stage="custody", format="txt",
        path=relative, sha256=declaration_hash, size_bytes=len(content), derived_from=[],
    )
    by_id = {item.artifact_id: item for item in current}
    evidence = CustodyLicenseEvidence(
        binding_id="user_directed_local_use_2026_08_06",
        original_evidence_path=PortableCustodyPath(logical_root="foundry_workspace", path=str(relative)),
        evidence_sha256=declaration_hash, size_bytes=len(content),
        scope_root=PortableCustodyPath(logical_root="foundry_workspace", path="source/compound_roots_001"),
        rights_semantics="documented", candidate_evidence_artifact_id=evidence_id,
    )
    contributions = [
        CustodySourceContribution(
            contribution_id="meshy_mesh_material", source_id="meshy_user_directed_local",
            package_id="meshy_silent_grey_doe_exact_roots",
            package_root=PortableCustodyPath(logical_root="foundry_workspace", path="source/compound_roots_001"),
            source_inputs=sorted((by_id[item] for item in meshy_artifact_ids), key=lambda item: item.artifact_id),
            rights_status="documented", license_evidence=[evidence],
        ),
        CustodySourceContribution(
            contribution_id="quaternius_rig_animation", source_id="quaternius_user_directed_local",
            package_id="quaternius_deer_exact_root",
            package_root=PortableCustodyPath(logical_root="foundry_workspace", path="source/compound_roots_001"),
            source_inputs=sorted((by_id[item] for item in quaternius_artifact_ids), key=lambda item: item.artifact_id),
            rights_status="documented", license_evidence=[evidence],
        ),
    ]
    register_hash = user_local_use_register_sha256(manifest, declaration_hash)
    root_fingerprints = {"foundry_workspace": register_hash}
    assertion = CustodyAssertion(
        schema_version=CUSTODY_SCHEMA_V1_3, assessment_status="evaluated",
        source_contributions=contributions, policy_schema_version=POLICY_SCHEMA,
        policy_sha256=declaration_hash, register_schema_version=REGISTER_SCHEMA,
        register_sha256=register_hash, register_root_fingerprints=root_fingerprints,
        evidence_fingerprint_sha256=evidence_freshness_sha256(
            POLICY_SCHEMA, declaration_hash, REGISTER_SCHEMA, register_hash, root_fingerprints),
        evaluated_manifest_revision=manifest.revision, effective_rights_status="documented",
        semantic_assertion_sha256=user_local_use_semantic_sha256(contributions),
    )
    source_revision = manifest.revision
    manifest.artifacts.append(evidence_artifact); manifest.custody = assertion
    manifest.revision += 1; manifest.asset.updated_at = utc_now()
    try:
        repository.save(manifest, "custody.user_local_use_bound", expected_revision=manifest.revision - 1)
    except BaseException:
        live = repository.load(asset_id)
        if _is_exact_target(live, manifest.revision, evidence_artifact, assertion):
            diagnosis = repository.diagnose_pending_save(asset_id)
            if diagnosis.status in {"event_missing", "event_partial", "event_complete"}:
                repository.reconcile_pending_save(asset_id)
            return assertion
        if live.revision == source_revision and not _references(live, evidence_artifact, assertion):
            destination.unlink(missing_ok=True)
        raise
    return assertion


def _verify_committed_retry(
    asset_root: Path,
    manifest,
    declaration_path: Path,
    meshy_artifact_ids: list[str],
    quaternius_artifact_ids: list[str],
) -> CustodyAssertion:
    assertion = manifest.custody
    assert assertion is not None
    digest = hashlib.sha256(declaration_path.read_bytes()).hexdigest()
    by_contribution = {
        contribution.contribution_id: {
            item.artifact_id for item in contribution.source_inputs
        }
        for contribution in assertion.source_contributions
    }
    meshy_ids = set(meshy_artifact_ids)
    quaternius_ids = set(quaternius_artifact_ids)
    evidence = [
        item
        for item in manifest.artifacts
        if item.role == "custody_license_evidence" and item.sha256 == digest
    ]
    if (
        assertion.schema_version != CUSTODY_SCHEMA_V1_3
        or len(meshy_ids) != len(meshy_artifact_ids)
        or len(quaternius_ids) != len(quaternius_artifact_ids)
        or meshy_ids & quaternius_ids
        or by_contribution.get("meshy_mesh_material") != meshy_ids
        or by_contribution.get("quaternius_rig_animation") != quaternius_ids
        or set(by_contribution) != {"meshy_mesh_material", "quaternius_rig_animation"}
        or len(evidence) != 1
        or assertion.policy_sha256 != digest
    ):
        raise FoundryError("Existing user local-use custody does not match retry inputs.")
    artifact = evidence[0]
    destination = contained_path(asset_root, artifact.path)
    try:
        destination_digest, destination_size = _hash_file(destination)
    except OSError as exc:
        raise FoundryError("Manifest-owned user local-use evidence is unreadable.") from exc
    if (
        destination_digest != artifact.sha256
        or destination_size != artifact.size_bytes
        or artifact.size_bytes != len(declaration_path.read_bytes())
    ):
        raise FoundryError("Manifest-owned user local-use evidence is missing or changed.")
    return assertion


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _is_exact_target(
    manifest, revision: int, artifact: Artifact, assertion: CustodyAssertion
) -> bool:
    return manifest.revision == revision and _references(manifest, artifact, assertion)


def _references(manifest, artifact: Artifact, assertion: CustodyAssertion) -> bool:
    live = next(
        (item for item in manifest.artifacts if item.artifact_id == artifact.artifact_id), None
    )
    return bool(
        live is not None
        and live.model_dump(mode="json") == artifact.model_dump(mode="json")
        and manifest.custody is not None
        and manifest.custody.model_dump(mode="json") == assertion.model_dump(mode="json")
    )
