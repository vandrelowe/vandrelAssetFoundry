import hashlib
import json
from pathlib import Path

import pytest

from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.services.audit_library import audit_library


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_library(root: Path) -> Path:
    release = root / "assets" / "stone_knife_001" / "r001"
    release.mkdir(parents=True)
    model = b"immutable model"
    (release / "model.glb").write_bytes(model)
    descriptor = {
        "schema_version": 1,
        "asset_id": "stone_knife_001",
        "release_revision": 1,
        "files": [
            {
                "role": "model",
                "path": "model.glb",
                "sha256": _sha256(model),
                "size_bytes": len(model),
                "source_artifact_id": "model-001",
            }
        ],
    }
    descriptor_bytes = (json.dumps(descriptor, indent=2) + "\n").encode()
    (release / "asset-release.json").write_bytes(descriptor_bytes)
    catalog = {
        "schema_version": 1,
        "assets": {
            "stone_knife_001": {
                "latest_revision": 1,
                "releases": [
                    {
                        "revision": 1,
                        "path": "assets/stone_knife_001/r001/asset-release.json",
                        "descriptor_sha256": _sha256(descriptor_bytes),
                    }
                ],
            }
        },
    }
    (root / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    return release


def test_audit_library_verifies_catalog_descriptor_and_files(config) -> None:
    _write_library(config.foundry.asset_library_root)

    result = audit_library(config)

    assert result.passed
    assert len(result.checks) == 5


def test_audit_library_detects_changed_release_file(config) -> None:
    release = _write_library(config.foundry.asset_library_root)
    (release / "model.glb").write_bytes(b"changed")

    result = audit_library(config)

    assert not result.passed
    assert any(check.subject.endswith(":model.glb") and not check.passed for check in result.checks)


def test_audit_library_detects_orphaned_release(config) -> None:
    root = config.foundry.asset_library_root
    _write_library(root)
    (root / "assets" / "extra_asset_001" / "r001").mkdir(parents=True)

    result = audit_library(config)

    assert not result.passed
    assert any("extra_asset_001/r001" in check.subject for check in result.checks)


def test_audit_library_rejects_missing_catalog(config) -> None:
    with pytest.raises(FoundryError, match="does not exist"):
        audit_library(config)
