"""Candidate-relevant custody evaluation and freshness authority."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from pathlib import Path

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.custody import CustodyRegister, PortableCustodyPath
from vandrel_foundry.domain.custody_assertion import (
    CUSTODY_SCHEMA_V1_1,
    current_source_inputs,
    evidence_freshness_sha256,
    semantic_assertion_sha256,
)
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import (
    Artifact,
    AssetManifest,
    CustodyAssertion,
    CustodyLicenseEvidence,
    CustodySourceContribution,
    CustodySourceInput,
    utc_now,
)
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.build_custody_inventory import (
    load_custody_policy,
    validate_custody_register,
)
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import contained_path

SAFE_ID = re.compile(r"[^a-zA-Z0-9_.-]+")


def bind_candidate_custody(
    config: FoundryConfig,
    asset_id: str,
    outside_root: Path,
    register_path: Path,
    policy_path: Path,
    package_ids: list[str],
) -> AssetManifest:
    if not package_ids or len(package_ids) != len(set(package_ids)):
        raise FoundryError("Custody evaluation requires unique package IDs.")
    validation = validate_custody_register(
        register_path,
        policy_path,
        config,
        outside_root,
        config.foundry.workspace_root,
    )
    policy, policy_bytes = load_custody_policy(policy_path)
    try:
        register_bytes = register_path.read_bytes()
        register = CustodyRegister.model_validate_json(register_bytes)
    except (OSError, ValueError) as exc:
        raise FoundryError(f"Could not load validated custody register: {exc}") from exc
    packages = {item.package_id: item for item in register.packages}
    missing_packages = sorted(set(package_ids) - packages.keys())
    if missing_packages:
        raise FoundryError(f"Custody packages are absent from register: {missing_packages}")
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    source_inputs = current_source_inputs(manifest)
    if not source_inputs:
        raise FoundryError("Candidate has no root source inputs to bind.")
    outside_entries = [
        item
        for item in register.outside_files
        if item.package_id in package_ids and not item.excluded
    ]
    assignments: dict[str, list[CustodySourceInput]] = {
        package_id: [] for package_id in package_ids
    }
    for source in source_inputs:
        matches = {
            item.package_id
            for item in outside_entries
            if item.sha256 == source.sha256 and item.size_bytes == source.size_bytes
        }
        if len(matches) != 1:
            raise FoundryError(
                f"Source input {source.artifact_id} must match exactly one selected package; "
                f"matched {sorted(matches)}"
            )
        assignments[next(iter(matches))].append(source)
    empty = sorted(package_id for package_id, values in assignments.items() if not values)
    if empty:
        raise FoundryError(f"Selected custody packages bind no source inputs: {empty}")
    package_policy = {item.package_root: item for item in policy.packages}
    license_policy = {item.binding_id: item for item in policy.license_bindings}
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    created_paths: list[Path] = []
    evidence_by_binding: dict[str, CustodyLicenseEvidence] = {}
    try:
        contributions = []
        for index, package_id in enumerate(sorted(package_ids), start=1):
            package = packages[package_id]
            evidence = []
            if package.rights_status == "documented":
                declared = package_policy.get(package.package_root)
                if declared is None or not declared.license_binding_ids:
                    raise FoundryError(f"Documented package lacks policy evidence: {package_id}")
                for binding_id in sorted(declared.license_binding_ids):
                    existing = evidence_by_binding.get(binding_id)
                    if existing is None:
                        binding = license_policy[binding_id]
                        existing, artifact, destination, created = _retain_license_evidence(
                            asset_root,
                            outside_root,
                            manifest,
                            binding_id,
                            binding.evidence_path,
                            binding.evidence_sha256,
                            binding.scope_root,
                        )
                        evidence_by_binding[binding_id] = existing
                        if artifact.artifact_id not in {
                            item.artifact_id for item in manifest.artifacts
                        }:
                            manifest.artifacts.append(artifact)
                        if created:
                            created_paths.append(destination)
                    evidence.append(existing)
            contributions.append(
                CustodySourceContribution(
                    contribution_id=f"source_{index:03d}",
                    source_id=package.source_id or "unknown",
                    package_id=package.package_id,
                    package_root=PortableCustodyPath(
                        logical_root="outside_assets",
                        path=package.package_root,
                    ),
                    source_inputs=sorted(
                        assignments[package_id],
                        key=lambda item: item.artifact_id,
                    ),
                    rights_status=package.rights_status,
                    license_evidence=evidence,
                )
            )
        statuses = {item.rights_status for item in contributions}
        effective = (
            "disputed"
            if "disputed" in statuses
            else "missing"
            if "missing" in statuses
            else "documented"
        )
        semantic_sha = semantic_assertion_sha256(contributions)
        register_sha = hashlib.sha256(register_bytes).hexdigest()
        policy_sha = hashlib.sha256(policy_bytes).hexdigest()
        root_fingerprints = validation["root_fingerprints"]
        evidence_fingerprint = evidence_freshness_sha256(
            policy.schema_version,
            policy_sha,
            register.schema_version,
            register_sha,
            root_fingerprints,
        )
        assertion = CustodyAssertion(
            schema_version=CUSTODY_SCHEMA_V1_1,
            assessment_status="evaluated",
            source_contributions=contributions,
            policy_schema_version=policy.schema_version,
            policy_sha256=policy_sha,
            register_schema_version=register.schema_version,
            register_sha256=register_sha,
            register_root_fingerprints=root_fingerprints,
            evidence_fingerprint_sha256=evidence_fingerprint,
            evaluated_manifest_revision=manifest.revision,
            effective_rights_status=effective,
            semantic_assertion_sha256=semantic_sha,
        )
        previous_sha = (
            manifest.custody.semantic_assertion_sha256
            if manifest.custody is not None and manifest.custody.assessment_status == "evaluated"
            else None
        )
        if manifest.approval.approved and previous_sha != semantic_sha:
            _clear_approval(manifest)
            manifest.workflow.state = WorkflowState.REVIEW
        manifest.schema_version = 2
        manifest.custody = assertion
        manifest.revision += 1
        manifest.asset.updated_at = utc_now()
        repository.save(
            manifest,
            "custody.evaluated",
            expected_revision=manifest.revision - 1,
        )
        return manifest
    except BaseException:
        for path in created_paths:
            path.unlink(missing_ok=True)
        raise


def _retain_license_evidence(
    asset_root: Path,
    outside_root: Path,
    manifest: AssetManifest,
    binding_id: str,
    evidence_path: str,
    evidence_sha256: str,
    scope_root: str,
) -> tuple[CustodyLicenseEvidence, Artifact, Path, bool]:
    source = contained_path(outside_root, evidence_path)
    try:
        content = source.read_bytes()
    except OSError as exc:
        raise FoundryError(f"Custody license evidence is unavailable: {evidence_path}") from exc
    if hashlib.sha256(content).hexdigest() != evidence_sha256:
        raise FoundryError(f"Custody license evidence changed: {evidence_path}")
    safe_id = SAFE_ID.sub("_", binding_id).strip("._") or "evidence"
    suffix = source.suffix.lower() or ".bin"
    relative = Path("custody/evidence") / f"{safe_id}-{evidence_sha256[:12]}{suffix}"
    destination = contained_path(asset_root, relative.as_posix())
    existing_artifact = next(
        (
            item
            for item in manifest.artifacts
            if str(item.path) == relative.as_posix()
            and item.role == "custody_license_evidence"
            and item.sha256 == evidence_sha256
            and item.size_bytes == len(content)
        ),
        None,
    )
    if destination.exists() and existing_artifact is None:
        raise FoundryError(f"Custody evidence destination conflicts: {relative.as_posix()}")
    if existing_artifact is not None:
        artifact_id = existing_artifact.artifact_id
        evidence = CustodyLicenseEvidence(
            binding_id=binding_id,
            original_evidence_path=PortableCustodyPath(
                logical_root="outside_assets",
                path=evidence_path,
            ),
            evidence_sha256=evidence_sha256,
            size_bytes=len(content),
            scope_root=PortableCustodyPath(
                logical_root="outside_assets",
                path=scope_root,
            ),
            rights_semantics="documented",
            candidate_evidence_artifact_id=artifact_id,
        )
        return evidence, existing_artifact, destination, False
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + f".{os.getpid()}.tmp")
    try:
        with source.open("rb") as input_stream, temporary.open("xb") as output_stream:
            shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != evidence_sha256:
            raise FoundryError(f"Copied custody evidence changed: {binding_id}")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    artifact_id = _next_evidence_artifact_id(manifest)
    artifact = Artifact(
        artifact_id=artifact_id,
        role="custody_license_evidence",
        stage="custody",
        format=suffix.lstrip("."),
        path=relative.as_posix(),
        sha256=evidence_sha256,
        size_bytes=len(content),
        derived_from=[],
    )
    evidence = CustodyLicenseEvidence(
        binding_id=binding_id,
        original_evidence_path=PortableCustodyPath(
            logical_root="outside_assets",
            path=evidence_path,
        ),
        evidence_sha256=evidence_sha256,
        size_bytes=len(content),
        scope_root=PortableCustodyPath(
            logical_root="outside_assets",
            path=scope_root,
        ),
        rights_semantics="documented",
        candidate_evidence_artifact_id=artifact_id,
    )
    return evidence, artifact, destination, True


def _next_evidence_artifact_id(manifest: AssetManifest) -> str:
    existing = {item.artifact_id for item in manifest.artifacts}
    index = 1
    while f"custody_license_evidence_{index:03d}" in existing:
        index += 1
    return f"custody_license_evidence_{index:03d}"


def _clear_approval(manifest: AssetManifest) -> None:
    manifest.approval.approved = False
    manifest.approval.approved_at = None
    manifest.approval.approved_artifact_hashes = {}
    manifest.approval.custody_assertion_sha256 = None
    manifest.approval.custody_source_inputs = []
    manifest.approval.reviewer = None
