from __future__ import annotations

import hashlib
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.custody import PortableCustodyPath
from vandrel_foundry.domain.custody_assertion import (
    CUSTODY_SCHEMA_V1_2,
    current_source_inputs,
    evidence_freshness_sha256,
    provider_provenance_sha256,
    semantic_assertion_sha256,
)
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import (
    Artifact,
    CustodyAssertion,
    CustodyLicenseEvidence,
    CustodySourceContribution,
    utc_now,
)
from vandrel_foundry.domain.provider import ProviderTaskStatus
from vandrel_foundry.domain.workflow_policy import invalidate_approval
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path


class ProviderRights(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rights_status: str
    evidence_retrieved_at: str
    evidence_urls: list[str] = Field(min_length=1)
    basis: str = Field(min_length=1)


class ProviderRightsPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str
    providers: dict[str, ProviderRights]


def bind_provider_custody(
    config: FoundryConfig,
    asset_id: str,
    policy_path: Path,
) -> CustodyAssertion:
    try:
        policy_bytes = policy_path.read_bytes()
        policy = ProviderRightsPolicy.model_validate_json(policy_bytes)
    except (OSError, ValueError) as exc:
        raise FoundryError(f"Could not load provider rights policy: {exc}") from exc
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    provider = manifest.generation.provider
    rights = policy.providers.get(provider)
    if rights is None or rights.rights_status != "documented":
        raise FoundryError(f"Provider rights are not documented: {provider}")
    selected = manifest.generation.selected_task_key
    tasks = [item for item in manifest.generation.tasks if item.task_key == selected]
    if not selected or not tasks:
        raise FoundryError("Provider custody requires a selected provider task.")
    task = tasks[-1]
    if task.status is not ProviderTaskStatus.SUCCEEDED or not task.provider_task_id:
        raise FoundryError("Provider custody requires a succeeded provider task.")
    sources = current_source_inputs(manifest)
    if not sources or any(
        item.artifact_id not in {a.artifact_id for a in manifest.artifacts} for item in sources
    ):
        raise FoundryError("Provider custody requires immutable source artifacts.")

    policy_sha = hashlib.sha256(policy_bytes).hexdigest()
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    relative = RelativeManifestPath(
        f"custody/evidence/{provider}-rights-policy-{policy_sha[:12]}.json"
    )
    destination = contained_path(asset_root, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    created = False
    if not destination.exists():
        temporary = destination.with_name(f".{destination.name}.tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(policy_bytes)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
            created = True
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    elif destination.read_bytes() != policy_bytes:
        raise FoundryError(f"Provider rights evidence conflicts: {relative}")

    artifact = next(
        (item for item in manifest.artifacts if item.path == relative),
        None,
    )
    if artifact is None:
        artifact = Artifact(
            artifact_id=f"custody_provider_rights_{sum(a.role == 'custody_license_evidence' for a in manifest.artifacts) + 1:03d}",
            role="custody_license_evidence",
            stage="custody",
            format="json",
            path=relative,
            sha256=policy_sha,
            size_bytes=len(policy_bytes),
        )
        manifest.artifacts.append(artifact)
    elif artifact.sha256 != policy_sha or artifact.size_bytes != len(policy_bytes):
        raise FoundryError("Recorded provider rights evidence does not match policy bytes.")

    workspace_base = f"assets/{asset_id}"
    evidence = CustodyLicenseEvidence(
        binding_id=f"{provider}_paid_api_commercial_rights_v1",
        original_evidence_path=PortableCustodyPath(
            logical_root="foundry_workspace",
            path=f"{workspace_base}/{relative}",
        ),
        evidence_sha256=policy_sha,
        size_bytes=len(policy_bytes),
        scope_root=PortableCustodyPath(
            logical_root="foundry_workspace",
            path=f"{workspace_base}/provider/{provider}",
        ),
        rights_semantics="documented",
        candidate_evidence_artifact_id=artifact.artifact_id,
    )
    contribution = CustodySourceContribution(
        contribution_id="provider_source_001",
        source_id=provider,
        package_id=f"{provider}-task-{task.provider_task_id}",
        package_root=PortableCustodyPath(
            logical_root="foundry_workspace",
            path=f"{workspace_base}/provider/{provider}",
        ),
        source_inputs=sources,
        rights_status="documented",
        license_evidence=[evidence],
    )
    register_sha = provider_provenance_sha256(manifest, policy_sha)
    roots = {"foundry_workspace": register_sha}
    assertion = CustodyAssertion(
        schema_version=CUSTODY_SCHEMA_V1_2,
        assessment_status="evaluated",
        source_contributions=[contribution],
        policy_schema_version=policy.schema_version,
        policy_sha256=policy_sha,
        register_schema_version="vandrel_foundry_provider_provenance/1.0",
        register_sha256=register_sha,
        register_root_fingerprints=roots,
        evidence_fingerprint_sha256=evidence_freshness_sha256(
            policy.schema_version,
            policy_sha,
            "vandrel_foundry_provider_provenance/1.0",
            register_sha,
            roots,
        ),
        evaluated_manifest_revision=manifest.revision,
        effective_rights_status="documented",
        semantic_assertion_sha256=semantic_assertion_sha256([contribution]),
    )
    invalidate_approval(manifest)
    manifest.custody = assertion
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    try:
        repository.save(
            manifest,
            "custody.provider_evaluated",
            expected_revision=manifest.revision - 1,
        )
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise
    return assertion
