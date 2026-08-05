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


def _write_tampered_v2_library(root: Path, case: str) -> None:
    fixture = Path(__file__).parent / "fixtures" / "release_descriptors" / "release-v2.json"
    descriptor = json.loads(fixture.read_text(encoding="utf-8"))
    model = b"model-content"
    license_bytes = b"license-content"
    model_entry, license_entry = descriptor["files"]
    model_entry["sha256"] = _sha256(model)
    model_entry["size_bytes"] = len(model)
    license_entry["sha256"] = _sha256(license_bytes)
    license_entry["size_bytes"] = len(license_bytes)
    evidence = descriptor["custody"]["source_contributions"][0]["license_evidence"][0]
    evidence["sha256"] = license_entry["sha256"]
    evidence["size_bytes"] = license_entry["size_bytes"]
    extra_payloads: list[tuple[dict, bytes]] = []
    if case == "model_as_license":
        evidence.update(
            {
                "release_path": model_entry["path"],
                "sha256": model_entry["sha256"],
                "size_bytes": model_entry["size_bytes"],
                "source_artifact_id": model_entry["source_artifact_id"],
            }
        )
    elif case == "model_as_report":
        descriptor["humanoid_compatibility"] = {
            "evidence_route": "retarget_mapping",
            "candidate_only": True,
            "vandrel_runtime_accepted": False,
            "mapping_profile": "profile/v1",
            "report": {
                "release_path": model_entry["path"],
                "sha256": model_entry["sha256"],
                "size_bytes": model_entry["size_bytes"],
                "source_artifact_id": model_entry["source_artifact_id"],
            },
            "animation_donor_asset_id": "donor_asset_001",
            "direct_skeleton_match": True,
            "direct_rest_transform_match": True,
            "humanoid_retarget_candidate": True,
        }
    elif case == "static_role_confusion":
        license_entry["role"] = "model"
    elif case == "license_source_mismatch":
        evidence["source_artifact_id"] = "different-evidence-artifact"
    elif case == "humanoid_report_source_mismatch":
        report_bytes = b'{"passed":true}\n'
        report_entry = {
            "role": "humanoid_compatibility_report",
            "path": "evidence/humanoid/report.json",
            "sha256": _sha256(report_bytes),
            "size_bytes": len(report_bytes),
            "source_artifact_id": "humanoid-report-001",
        }
        descriptor["files"].append(report_entry)
        descriptor["humanoid_compatibility"] = {
            "evidence_route": "retarget_mapping",
            "candidate_only": True,
            "vandrel_runtime_accepted": False,
            "mapping_profile": "profile/v1",
            "report": {
                "release_path": report_entry["path"],
                "sha256": report_entry["sha256"],
                "size_bytes": report_entry["size_bytes"],
                "source_artifact_id": "different-humanoid-report",
            },
            "animation_donor_asset_id": "donor_asset_001",
            "direct_skeleton_match": True,
            "direct_rest_transform_match": True,
            "humanoid_retarget_candidate": True,
        }
        extra_payloads.append((report_entry, report_bytes))
    else:
        raise AssertionError(case)
    release = root / "assets" / descriptor["asset_id"] / "r001"
    release.mkdir(parents=True)
    (release / model_entry["path"]).write_bytes(model)
    license_path = release / license_entry["path"]
    license_path.parent.mkdir(parents=True)
    license_path.write_bytes(license_bytes)
    for entry, payload in extra_payloads:
        extra_path = release / entry["path"]
        extra_path.parent.mkdir(parents=True, exist_ok=True)
        extra_path.write_bytes(payload)
    descriptor_bytes = (json.dumps(descriptor, indent=2) + "\n").encode()
    (release / "asset-release.json").write_bytes(descriptor_bytes)
    catalog = {
        "schema_version": 1,
        "assets": {
            descriptor["asset_id"]: {
                "latest_revision": 1,
                "releases": [
                    {
                        "revision": 1,
                        "path": (f"assets/{descriptor['asset_id']}/r001/asset-release.json"),
                        "descriptor_sha256": _sha256(descriptor_bytes),
                    }
                ],
            }
        },
    }
    (root / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")


def test_audit_library_verifies_catalog_descriptor_and_files(config) -> None:
    _write_library(config.foundry.asset_library_root)

    result = audit_library(config)

    assert result.passed
    assert len(result.checks) == 6


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


def test_audit_library_rejects_r1000_layout(config) -> None:
    _write_library(config.foundry.asset_library_root)
    (config.foundry.asset_library_root / "assets" / "stone_knife_001" / "r1000").mkdir()

    result = audit_library(config)

    assert not result.passed
    assert any(
        check.subject.endswith("r1000") and "r001..r999" in check.detail for check in result.checks
    )


@pytest.mark.parametrize(
    "case",
    [
        "model_as_license",
        "model_as_report",
        "static_role_confusion",
        "license_source_mismatch",
        "humanoid_report_source_mismatch",
    ],
)
def test_live_audit_rejects_v2_evidence_role_or_source_substitution(
    config,
    case: str,
) -> None:
    _write_tampered_v2_library(config.foundry.asset_library_root, case)

    result = audit_library(config)

    assert not result.passed
    assert any(
        check.subject.endswith(":evidence_roles") and not check.passed for check in result.checks
    )
