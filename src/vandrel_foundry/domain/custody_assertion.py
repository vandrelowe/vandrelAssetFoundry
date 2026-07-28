"""Pure candidate custody semantics and freshness checks."""

import hashlib
import json

from vandrel_foundry.domain.custody import PortableCustodyPath
from vandrel_foundry.domain.manifest import (
    AssetManifest,
    CustodySourceContribution,
    CustodySourceInput,
)

CUSTODY_SCHEMA = "vandrel_foundry_candidate_custody/1.0"
CUSTODY_SCHEMA_V1_1 = "vandrel_foundry_candidate_custody/1.1"
EVIDENCE_FRESHNESS_SCHEMA = "vandrel_foundry_custody_evidence_freshness/1.0"


def current_source_inputs(manifest: AssetManifest) -> list[CustodySourceInput]:
    return sorted(
        (
            CustodySourceInput(
                artifact_id=item.artifact_id,
                role=item.role,
                sha256=item.sha256,
                size_bytes=item.size_bytes,
            )
            for item in manifest.artifacts
            if item.stage == "source" and not item.derived_from
        ),
        key=lambda item: item.artifact_id,
    )


def semantic_assertion_sha256(
    contributions: list[CustodySourceContribution],
) -> str:
    schema_version = (
        CUSTODY_SCHEMA_V1_1
        if any(
            isinstance(item.package_root, PortableCustodyPath)
            for item in contributions
        )
        else CUSTODY_SCHEMA
    )
    semantic = {
        "schema_version": schema_version,
        "source_contributions": [
            {
                "contribution_id": item.contribution_id,
                "source_id": item.source_id,
                "package_id": item.package_id,
                "package_root": _custody_path_value(item.package_root),
                "source_inputs": [
                    value.model_dump(mode="json")
                    for value in sorted(item.source_inputs, key=lambda value: value.artifact_id)
                ],
                "rights_status": item.rights_status,
                "license_evidence": [
                    {
                        "binding_id": value.binding_id,
                        "original_evidence_path": _custody_path_value(
                            value.original_evidence_path
                        ),
                        "evidence_sha256": value.evidence_sha256,
                        "size_bytes": value.size_bytes,
                        "scope_root": _custody_path_value(value.scope_root),
                        "rights_semantics": value.rights_semantics,
                    }
                    for value in sorted(
                        item.license_evidence,
                        key=lambda value: value.binding_id,
                    )
                ],
            }
            for item in sorted(contributions, key=lambda item: item.contribution_id)
        ],
    }
    canonical = (json.dumps(semantic, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()
    return hashlib.sha256(canonical).hexdigest()


def evidence_freshness_sha256(
    policy_schema_version: str,
    policy_sha256: str,
    register_schema_version: str,
    register_sha256: str,
    root_fingerprints: dict[str, str],
) -> str:
    evidence = {
        "schema_version": EVIDENCE_FRESHNESS_SCHEMA,
        "policy": {
            "schema_version": policy_schema_version,
            "sha256": policy_sha256,
        },
        "register": {
            "schema_version": register_schema_version,
            "sha256": register_sha256,
        },
        "root_fingerprints": dict(sorted(root_fingerprints.items())),
    }
    canonical = (json.dumps(evidence, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()
    return hashlib.sha256(canonical).hexdigest()


def custody_freshness(manifest: AssetManifest) -> tuple[bool, list[str]]:
    if manifest.schema_version == 1:
        return False, ["historical_v1_unassessed"]
    assertion = manifest.custody
    if assertion is None or assertion.assessment_status == "absent":
        return False, ["custody_absent"]
    if assertion.assessment_status == "historical_unassessed":
        return False, ["custody_historical_unassessed"]
    blockers = []
    if assertion.schema_version == CUSTODY_SCHEMA:
        blockers.append("custody_assertion_legacy_stale")
    if assertion.effective_rights_status != "documented":
        blockers.append(f"custody_rights_{assertion.effective_rights_status}")
    semantic = semantic_assertion_sha256(assertion.source_contributions)
    if semantic != assertion.semantic_assertion_sha256:
        blockers.append("custody_semantic_hash_stale")
    if assertion.schema_version.endswith("/1.1"):
        root_fingerprints = assertion.register_root_fingerprints or {}
        expected_roots = {"outside_assets", "foundry_workspace", "asset_library"}
        valid_roots = set(root_fingerprints) == expected_roots and all(
            len(value) == 64 and all(character in "0123456789abcdef" for character in value)
            for value in root_fingerprints.values()
        )
        if not valid_roots:
            blockers.append("custody_evidence_root_fingerprints_invalid")
        elif (
            assertion.policy_schema_version is None
            or assertion.policy_sha256 is None
            or assertion.register_schema_version is None
            or assertion.register_sha256 is None
            or assertion.evidence_fingerprint_sha256
            != evidence_freshness_sha256(
                assertion.policy_schema_version,
                assertion.policy_sha256,
                assertion.register_schema_version,
                assertion.register_sha256,
                root_fingerprints,
            )
        ):
            blockers.append("custody_evidence_fingerprint_stale")
    bound_inputs = sorted(
        (
            item
            for contribution in assertion.source_contributions
            for item in contribution.source_inputs
        ),
        key=lambda item: item.artifact_id,
    )
    current_inputs = current_source_inputs(manifest)
    if bound_inputs != current_inputs or len({item.artifact_id for item in bound_inputs}) != len(
        bound_inputs
    ):
        blockers.append("custody_source_inputs_stale_or_incomplete")
    artifacts = {item.artifact_id: item for item in manifest.artifacts}
    for evidence in (
        item
        for contribution in assertion.source_contributions
        for item in contribution.license_evidence
    ):
        artifact = artifacts.get(evidence.candidate_evidence_artifact_id)
        if (
            artifact is None
            or artifact.role != "custody_license_evidence"
            or artifact.sha256 != evidence.evidence_sha256
            or artifact.size_bytes != evidence.size_bytes
        ):
            blockers.append(f"custody_evidence_stale:{evidence.binding_id}")
    return not blockers, sorted(set(blockers))


def approval_custody_freshness(manifest: AssetManifest) -> tuple[bool, list[str]]:
    fresh, blockers = custody_freshness(manifest)
    if not fresh:
        return False, blockers
    assertion = manifest.custody
    assert assertion is not None
    bound_inputs = sorted(
        (
            item
            for contribution in assertion.source_contributions
            for item in contribution.source_inputs
        ),
        key=lambda item: item.artifact_id,
    )
    if manifest.approval.custody_assertion_sha256 != assertion.semantic_assertion_sha256:
        blockers.append("approval_custody_assertion_stale")
    if manifest.approval.custody_source_inputs != bound_inputs:
        blockers.append("approval_custody_sources_stale")
    return not blockers, sorted(set(blockers))


def custody_display_status(manifest: AssetManifest) -> str:
    if manifest.schema_version == 1:
        return "historical_v1_unassessed"
    if manifest.custody is None:
        return "absent"
    if manifest.custody.assessment_status == "historical_unassessed":
        return "historical_v1_unassessed"
    if manifest.custody.assessment_status == "absent":
        return "absent"
    return f"evaluated_{manifest.custody.effective_rights_status}"


def _custody_path_value(value: object) -> object:
    if isinstance(value, PortableCustodyPath):
        return value.model_dump(mode="json")
    return str(value)
