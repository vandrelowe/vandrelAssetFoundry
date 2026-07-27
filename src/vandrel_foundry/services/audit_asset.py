import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.manifest import Artifact
from vandrel_foundry.services.review_asset import APPROVAL_ROLES
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import contained_path

MAX_EVENT_LOG_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class ArtifactAudit:
    artifact_id: str
    path: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class AssetAudit:
    asset_id: str
    passed: bool
    artifact_checks: list[ArtifactAudit]
    manifest_checks: list[dict[str, object]]


def audit_asset(config: FoundryConfig, asset_id: str) -> AssetAudit:
    manifest = ManifestRepository(config.foundry.workspace_root).load(asset_id)
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    artifact_checks = [_audit_artifact(asset_root, artifact) for artifact in manifest.artifacts]
    artifact_ids = [artifact.artifact_id for artifact in manifest.artifacts]
    artifact_paths = [str(artifact.path) for artifact in manifest.artifacts]
    known_ids = set(artifact_ids)
    missing_derivations = sorted(
        {
            parent
            for artifact in manifest.artifacts
            for parent in artifact.derived_from
            if parent not in known_ids
        }
    )
    approval_bindings_ok = not manifest.approval.approved or (
        set(APPROVAL_ROLES).issubset(manifest.approval.approved_artifact_hashes)
        and all(
            any(
                artifact.role == role and artifact.sha256 == expected_hash
                for artifact in manifest.artifacts
            )
            for role, expected_hash in manifest.approval.approved_artifact_hashes.items()
        )
    )
    manifest_checks: list[dict[str, object]] = [
        {
            "name": "unique_artifact_ids",
            "passed": len(artifact_ids) == len(set(artifact_ids)),
        },
        {
            "name": "unique_artifact_paths",
            "passed": len(artifact_paths) == len(set(artifact_paths)),
        },
        {
            "name": "artifact_derivations_resolve",
            "passed": not missing_derivations,
            "missing": missing_derivations,
        },
        {
            "name": "approval_bindings_resolve",
            "passed": approval_bindings_ok,
        },
        _audit_events(asset_root, asset_id, manifest.revision),
    ]
    passed = all(check.passed for check in artifact_checks) and all(
        bool(check["passed"]) for check in manifest_checks
    )
    return AssetAudit(
        asset_id=asset_id,
        passed=passed,
        artifact_checks=artifact_checks,
        manifest_checks=manifest_checks,
    )


def _audit_artifact(asset_root: Path, artifact: Artifact) -> ArtifactAudit:
    digest = hashlib.sha256()
    size = 0
    try:
        path = contained_path(asset_root, artifact.path)
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
    except (OSError, ValueError) as exc:
        return ArtifactAudit(
            artifact_id=artifact.artifact_id,
            path=str(artifact.path),
            passed=False,
            detail=f"unreadable: {exc}",
        )
    if size != artifact.size_bytes:
        detail = f"size mismatch: expected {artifact.size_bytes}, observed {size}"
        passed = False
    elif digest.hexdigest() != artifact.sha256:
        detail = "SHA-256 mismatch"
        passed = False
    else:
        detail = "hash and size match"
        passed = True
    return ArtifactAudit(
        artifact_id=artifact.artifact_id,
        path=str(artifact.path),
        passed=passed,
        detail=detail,
    )


def _audit_events(asset_root: Path, asset_id: str, manifest_revision: int) -> dict[str, object]:
    path = asset_root / "events.jsonl"
    try:
        if path.stat().st_size > MAX_EVENT_LOG_BYTES:
            return {
                "name": "event_history",
                "passed": False,
                "detail": "event log exceeds the audit size limit",
            }
        lines = path.read_text(encoding="utf-8").splitlines()
        events = [json.loads(line) for line in lines]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {
            "name": "event_history",
            "passed": False,
            "detail": f"event log is unreadable or invalid: {exc}",
        }
    revisions = [event.get("revision") for event in events if isinstance(event, dict)]
    valid_shape = len(events) == len(revisions) and all(
        event.get("asset_id") == asset_id
        and isinstance(event.get("event"), str)
        and bool(event["event"])
        and isinstance(event.get("timestamp"), str)
        and bool(event["timestamp"])
        for event in events
        if isinstance(event, dict)
    )
    expected_revisions = list(range(1, manifest_revision + 1))
    passed = valid_shape and revisions == expected_revisions
    return {
        "name": "event_history",
        "passed": passed,
        "observed_revisions": revisions,
        "expected_revisions": expected_revisions,
    }
