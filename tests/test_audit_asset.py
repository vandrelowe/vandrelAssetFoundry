import hashlib
import json
from pathlib import Path

from vandrel_foundry.domain.manifest import Artifact
from vandrel_foundry.services.audit_asset import audit_asset
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.inspect_assets import initialize_workspace
from vandrel_foundry.storage.manifests import ManifestRepository


def test_asset_audit_rehashes_artifacts_and_detects_tampering(config, lanes, prompt: Path) -> None:
    initialize_workspace(config.foundry.workspace_root)
    manifest = create_asset(
        config,
        lanes,
        "audit_prop_001",
        "static_prop",
        "Audit Prop",
        prompt,
    )
    asset_root = config.foundry.workspace_root / "assets/audit_prop_001"
    artifact_path = asset_root / "source/model.glb"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    content = b"immutable artifact"
    artifact_path.write_bytes(content)
    manifest.artifacts.append(
        Artifact(
            artifact_id="source_glb_001",
            role="source_model",
            stage="source",
            format="glb",
            path="source/model.glb",
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
        )
    )
    manifest.revision += 1
    ManifestRepository(config.foundry.workspace_root).save(
        manifest,
        "test.artifact_added",
        expected_revision=1,
    )

    assert audit_asset(config, "audit_prop_001").passed

    artifact_path.write_bytes(b"x" * len(content))
    failed = audit_asset(config, "audit_prop_001")
    assert not failed.passed
    assert failed.artifact_checks[0].detail == "SHA-256 mismatch"


def test_asset_audit_detects_unresolved_derivation(config, lanes, prompt: Path) -> None:
    initialize_workspace(config.foundry.workspace_root)
    manifest = create_asset(
        config,
        lanes,
        "audit_derivation_001",
        "static_prop",
        "Audit Derivation",
        prompt,
    )
    asset_root = config.foundry.workspace_root / "assets/audit_derivation_001"
    artifact_path = asset_root / "processed/model.glb"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    content = b"derived artifact"
    artifact_path.write_bytes(content)
    manifest.artifacts.append(
        Artifact(
            artifact_id="processed_glb_001",
            role="processed_model",
            stage="processed",
            format="glb",
            path="processed/model.glb",
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            derived_from=["missing_source_001"],
        )
    )
    manifest.revision += 1
    ManifestRepository(config.foundry.workspace_root).save(
        manifest,
        "test.artifact_added",
        expected_revision=1,
    )

    result = audit_asset(config, "audit_derivation_001")

    assert not result.passed
    check = next(
        item for item in result.manifest_checks if item["name"] == "artifact_derivations_resolve"
    )
    assert check["missing"] == ["missing_source_001"]

    with (asset_root / "events.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "timestamp": "2026-01-01T00:00:00Z",
                    "event": "unexpected.gap",
                    "asset_id": "audit_derivation_001",
                    "revision": 4,
                }
            )
            + "\n"
        )
    event_result = audit_asset(config, "audit_derivation_001")
    event_check = next(
        item for item in event_result.manifest_checks if item["name"] == "event_history"
    )
    assert not event_check["passed"]
    assert event_check["expected_revisions"] == [1, 2]
