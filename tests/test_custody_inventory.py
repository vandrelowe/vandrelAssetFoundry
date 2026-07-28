import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.services.build_custody_inventory import (
    _reject_reparse_ancestors,
    _scan_root,
    _stable_hash,
    build_custody_inventory,
    canonical_json,
    load_custody_policy,
    validate_custody_register,
    write_custody_outputs,
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _policy(
    path: Path,
    evidence_hash: str,
    *,
    rights: str = "documented",
    extra_bindings: list[dict] | None = None,
    exclusions: list[dict] | None = None,
) -> Path:
    bindings = [
        {
            "binding_id": "source_license",
            "evidence_path": "Source/Pack/LICENSE.txt",
            "evidence_sha256": evidence_hash,
            "scope_root": "Source/Pack",
            "rights_semantics": "documented",
        }
    ]
    bindings.extend(extra_bindings or [])
    value = {
        "schema_version": "vandrel_foundry_custody_policy/1.0",
        "scan_algorithm_version": "vandrel_foundry_custody_scan/1.0",
        "source_rules": [
            {
                "source_id": "source",
                "path_prefix": "Source",
                "package_mode": "first_child",
            }
        ],
        "packages": [
            {
                "package_root": "Source/Pack",
                "rights_status": rights,
                "license_binding_ids": (
                    [item["binding_id"] for item in bindings] if rights == "documented" else []
                ),
            }
        ],
        "license_bindings": bindings,
        "exclusions": exclusions or [],
        "workspace_temp_paths": ["cache"],
    }
    path.write_bytes(canonical_json(value))
    return path


def _roots(config, tmp_path: Path) -> tuple[Path, Path, Path]:
    outside = tmp_path / "outside"
    workspace = config.foundry.workspace_root
    library = config.foundry.asset_library_root
    (outside / "Source/Pack").mkdir(parents=True)
    (workspace / "assets").mkdir(parents=True)
    library.mkdir(parents=True)
    return outside, workspace, library


def test_inventory_is_deterministic_and_reconciles_duplicates(config, tmp_path: Path) -> None:
    outside, workspace, _library = _roots(config, tmp_path)
    license_bytes = b"documented license"
    (outside / "Source/Pack/LICENSE.txt").write_bytes(license_bytes)
    (outside / "Source/Pack/a.bin").write_bytes(b"same")
    (outside / "Source/Pack/b.bin").write_bytes(b"same")
    (outside / "Source/Loose.bin").write_bytes(b"loose")
    (workspace / "cache").mkdir()
    (workspace / "cache/transient.bin").write_bytes(b"cache")
    (workspace / "review.txt").write_bytes(b"unregistered")
    policy = _policy(tmp_path / "policy.json", _sha(license_bytes))

    first = build_custody_inventory(config, outside, workspace, policy)
    second = build_custody_inventory(config, outside, workspace, policy)

    assert first.register_bytes == second.register_bytes
    assert first.register["coverage"]["outside_assets"] == {
        "discovered_files": 4,
        "represented_files": 4,
        "excluded_files": 0,
        "reconciles": True,
    }
    duplicate = first.register["duplicate_sets"]
    assert len(duplicate) == 1
    assert duplicate[0]["duplicate_set_id"] == f"sha256:{_sha(b'same')}"
    loose = next(
        item for item in first.register["outside_files"] if item["path"].endswith("Loose.bin")
    )
    assert loose["effective_rights_status"] == "missing"
    assert not loose["promotion_eligible"]
    classes = {item["path"]: item["storage_class"] for item in first.register["workspace_files"]}
    assert classes == {
        "cache/transient.bin": "generated_cache_or_temp",
        "review.txt": "unregistered_file",
    }

    register = tmp_path / "register.json"
    report = tmp_path / "report.json"
    write_custody_outputs(
        first, register, report, (outside, workspace, config.foundry.asset_library_root)
    )
    assert validate_custody_register(register, policy, config, outside, workspace)["valid"]


def test_validator_rejects_tampered_rights_eligibility_and_noncanonical_bytes(
    config, tmp_path: Path
) -> None:
    outside, workspace, _library = _roots(config, tmp_path)
    license_bytes = b"license"
    (outside / "Source/Pack/LICENSE.txt").write_bytes(license_bytes)
    (outside / "Source/Pack/model.bin").write_bytes(b"model")
    policy = _policy(tmp_path / "policy.json", _sha(license_bytes))
    result = build_custody_inventory(config, outside, workspace, policy)
    register = tmp_path / "register.json"
    register.write_bytes(result.register_bytes)

    tampered = result.register.copy()
    tampered["outside_files"] = [dict(item) for item in result.register["outside_files"]]
    tampered["outside_files"][0]["promotion_eligible"] = False
    register.write_bytes(canonical_json(tampered))
    with pytest.raises(FoundryError, match="rights or eligibility"):
        validate_custody_register(register, policy, config, outside, workspace)

    register.write_bytes(result.register_bytes.rstrip() + b"\n\n")
    with pytest.raises(FoundryError, match="not canonical"):
        validate_custody_register(register, policy, config, outside, workspace)


@pytest.mark.parametrize(
    "mutation",
    ["orphan_package", "fabricated_candidate", "forged_storage_class"],
)
def test_validator_rejects_fabricated_workspace_and_package_authority(
    config, tmp_path: Path, mutation: str
) -> None:
    outside, workspace, _library = _roots(config, tmp_path)
    license_bytes = b"license"
    (outside / "Source/Pack/LICENSE.txt").write_bytes(license_bytes)
    (workspace / "unregistered.bin").write_bytes(b"workspace")
    policy = _policy(tmp_path / "policy.json", _sha(license_bytes))
    result = build_custody_inventory(config, outside, workspace, policy)
    tampered = json.loads(result.register_bytes)
    if mutation == "orphan_package":
        tampered["packages"].append(
            {
                "package_id": "pkg:source:ffffffffffffffffffffffff",
                "package_root": "Source/Z-Orphan",
                "source_id": "source",
                "rights_status": "missing",
                "license_binding_ids": [],
                "promotion_eligible": False,
            }
        )
        tampered["packages"].sort(key=lambda item: item["package_id"])
        tampered["counts"]["packages"] += 1
    elif mutation == "fabricated_candidate":
        tampered["workspace_candidates"].append(
            {
                "asset_id": "fabricated_001",
                "manifest_revision": 99,
                "workflow_state": "draft",
                "artifact_record_count": 42,
                "physical_file_count": 0,
                "physical_bytes": 0,
                "released_revision": 7,
                "storage_class_counts": {},
                "integrity": {"authority": "audit_asset", "passed": True},
                "retention_hold_reasons": [],
                "deletability_claimed": False,
            }
        )
    else:
        tampered["workspace_files"][0]["storage_class"] = "generated_cache_or_temp"
    register = tmp_path / f"{mutation}.json"
    register.write_bytes(canonical_json(tampered))
    with pytest.raises(FoundryError):
        validate_custody_register(register, policy, config, outside, workspace)


def test_policy_rejects_traversal_and_invalid_duplicate_exclusion(tmp_path: Path) -> None:
    path = _policy(tmp_path / "policy.json", "a" * 64)
    value = json.loads(path.read_text())
    value["workspace_temp_paths"] = ["../escape"]
    path.write_bytes(canonical_json(value))
    with pytest.raises(FoundryError, match="normalized relative POSIX"):
        load_custody_policy(path)

    value["workspace_temp_paths"] = []
    value["exclusions"] = [
        {
            "logical_root": "outside_assets",
            "path": "Source/Pack/skip.bin",
            "reason": "fixture",
            "hash_file": False,
            "duplicate_participating": True,
        }
    ]
    path.write_bytes(canonical_json(value))
    with pytest.raises(FoundryError, match="must be hashed"):
        load_custody_policy(path)


def test_missing_rights_is_valid_but_disputed_is_ineligible(config, tmp_path: Path) -> None:
    outside, workspace, _library = _roots(config, tmp_path)
    license_bytes = b"license"
    (outside / "Source/Pack/LICENSE.txt").write_bytes(license_bytes)
    (outside / "Source/Pack/model.bin").write_bytes(b"model")
    policy = _policy(tmp_path / "policy.json", _sha(license_bytes), rights="disputed")
    result = build_custody_inventory(config, outside, workspace, policy)
    model = next(
        item for item in result.register["outside_files"] if item["path"].endswith("model.bin")
    )
    assert model["effective_rights_status"] == "disputed"
    assert not model["promotion_eligible"]


def test_conflicting_license_scope_and_hash_mismatch_fail(config, tmp_path: Path) -> None:
    outside, workspace, _library = _roots(config, tmp_path)
    license_bytes = b"license"
    other_bytes = b"other"
    (outside / "Source/Pack/LICENSE.txt").write_bytes(license_bytes)
    (outside / "Source/Pack/OTHER.txt").write_bytes(other_bytes)
    (outside / "Source/Pack/model.bin").write_bytes(b"model")
    extra = [
        {
            "binding_id": "other_license",
            "evidence_path": "Source/Pack/OTHER.txt",
            "evidence_sha256": _sha(other_bytes),
            "scope_root": "Source/Pack",
            "rights_semantics": "documented",
        }
    ]
    policy = _policy(tmp_path / "policy.json", _sha(license_bytes), extra_bindings=extra)
    with pytest.raises(FoundryError, match="Conflicting license scopes"):
        build_custody_inventory(config, outside, workspace, policy)

    policy = _policy(tmp_path / "policy.json", "0" * 64)
    with pytest.raises(FoundryError, match="hash mismatch"):
        build_custody_inventory(config, outside, workspace, policy)


def test_output_boundary_and_symlink_fail_closed(config, tmp_path: Path) -> None:
    outside, workspace, _library = _roots(config, tmp_path)
    license_bytes = b"license"
    (outside / "Source/Pack/LICENSE.txt").write_bytes(license_bytes)
    policy = _policy(tmp_path / "policy.json", _sha(license_bytes))
    result = build_custody_inventory(config, outside, workspace, policy)
    with pytest.raises(FoundryError, match="outside scanned roots"):
        write_custody_outputs(
            result,
            outside / "register.json",
            tmp_path / "report.json",
            (outside, workspace, config.foundry.asset_library_root),
        )
    assert not (outside / "register.json").exists()

    target = tmp_path / "target.bin"
    target.write_bytes(b"target")
    link = outside / "Source/Pack/link.bin"
    try:
        os.symlink(target, link)
    except OSError:
        pytest.skip("Symlink creation is unavailable.")
    with pytest.raises(FoundryError, match="symlink"):
        build_custody_inventory(config, outside, workspace, policy)


def test_hash_drift_is_rejected(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "drift.bin"
    path.write_bytes(b"before")
    before = path.stat()
    opened = SimpleNamespace(
        st_dev=before.st_dev,
        st_ino=before.st_ino,
        st_size=before.st_size + 1,
        st_mtime_ns=before.st_mtime_ns + 1,
    )
    monkeypatch.setattr(
        "vandrel_foundry.services.build_custody_inventory.os.fstat",
        lambda _descriptor: opened,
    )
    with pytest.raises(FoundryError, match="changed while hashing"):
        _stable_hash(path, before)


def test_zero_discovery_identity_is_not_false_hash_drift(tmp_path: Path) -> None:
    path = tmp_path / "stable.bin"
    path.write_bytes(b"stable")
    actual = path.stat()
    discovery = SimpleNamespace(
        st_dev=0,
        st_ino=0,
        st_size=actual.st_size,
        st_mtime_ns=actual.st_mtime_ns,
    )
    digest, size = _stable_hash(path, discovery)
    assert digest == _sha(b"stable")
    assert size == len(b"stable")


def test_reparse_point_metadata_fails_closed(tmp_path: Path, monkeypatch) -> None:
    class ReparseEntry:
        name = "junction"
        path = str(tmp_path / "junction")

        @staticmethod
        def stat(*, follow_symlinks=False):
            assert not follow_symlinks
            return SimpleNamespace(st_file_attributes=0x400)

        @staticmethod
        def is_symlink():
            return False

    monkeypatch.setattr(
        "vandrel_foundry.services.build_custody_inventory.os.scandir",
        lambda _path: [ReparseEntry()],
    )
    with pytest.raises(FoundryError, match="Reparse point"):
        _scan_root(tmp_path)


def test_output_ancestor_reparse_is_checked_lexically(tmp_path: Path, monkeypatch) -> None:
    junction = tmp_path / "junction"
    junction.mkdir()
    original_lstat = type(junction).lstat

    def controlled_lstat(self, *args, **kwargs):
        result = original_lstat(self, *args, **kwargs)
        if self == junction:
            return SimpleNamespace(st_file_attributes=0x400)
        return result

    monkeypatch.setattr(type(junction), "lstat", controlled_lstat)
    with pytest.raises(FoundryError, match="ancestor is a reparse point"):
        _reject_reparse_ancestors(junction)


def test_concurrent_ancestor_identity_change_fails_closed(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    path = root / "stable.bin"
    path.write_bytes(b"stable")
    stable = (("root", 1, 1, 1, 0),)
    changed = (("root", 1, 2, 2, 0),)
    observed = iter((stable, stable, stable, changed))
    monkeypatch.setattr(
        "vandrel_foundry.services.build_custody_inventory._ancestor_fingerprint",
        lambda _path: next(observed),
    )
    with pytest.raises(FoundryError, match="ancestry changed"):
        _stable_hash(path, path.stat(), root)
