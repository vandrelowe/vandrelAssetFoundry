"""Deterministic, fail-closed custody inventory over read-only roots."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import ValidationError

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.custody import CustodyPolicy, CustodyRegister
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.services.audit_asset import audit_asset
from vandrel_foundry.services.preflight_custody_readability import (
    require_custody_readability_preflight,
)
from vandrel_foundry.storage.manifests import ManifestRepository

REGISTER_SCHEMA = "vandrel_foundry_custody_register/1.0"
REPORT_SCHEMA = "vandrel_foundry_custody_run_report/1.0"
BUFFER_SIZE = 1024 * 1024
REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


@dataclass(frozen=True)
class CustodyInventoryResult:
    register: dict[str, Any]
    report: dict[str, Any]
    register_bytes: bytes
    report_bytes: bytes


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()


def build_custody_inventory(
    config: FoundryConfig,
    outside_root: Path,
    workspace_root: Path,
    policy_path: Path,
    *,
    maximum_attempts: int = 2,
) -> CustodyInventoryResult:
    require_custody_readability_preflight(config, outside_root, workspace_root)
    outside_root = outside_root.resolve(strict=True)
    workspace_root = workspace_root.resolve(strict=True)
    if (
        outside_root == workspace_root
        or _is_within(outside_root, workspace_root)
        or _is_within(workspace_root, outside_root)
    ):
        raise FoundryError("Custody scan roots must be distinct and non-nested.")
    if workspace_root != config.foundry.workspace_root.resolve(strict=True):
        raise FoundryError("Workspace root must match configured Foundry workspace authority.")
    policy, policy_bytes = load_custody_policy(policy_path)
    errors: list[str] = []
    for attempt in range(1, maximum_attempts + 1):
        first = _scan_all(config, outside_root, workspace_root, policy, policy_bytes)
        second = _scan_all(config, outside_root, workspace_root, policy, policy_bytes)
        if first["source_fingerprints"] == second["source_fingerprints"]:
            register = second["register"]
            register_bytes = canonical_json(register)
            report = {
                "schema_version": REPORT_SCHEMA,
                "generated_at": datetime.now(UTC).isoformat(),
                "physical_roots": {
                    "outside_assets": str(outside_root),
                    "foundry_workspace": str(workspace_root),
                    "asset_library": str(config.foundry.asset_library_root.resolve(strict=True)),
                },
                "attempts": attempt,
                "stable_fingerprints": second["source_fingerprints"],
                "before_fingerprints": first["source_fingerprints"],
                "after_fingerprints": second["source_fingerprints"],
                "zero_source_mutation_observed": True,
                "canonical_register_sha256": hashlib.sha256(register_bytes).hexdigest(),
                "counts": register["counts"],
                "defects": register["defects"],
            }
            report_bytes = canonical_json(report)
            return CustodyInventoryResult(register, report, register_bytes, report_bytes)
        errors.append(
            f"attempt {attempt}: {first['source_fingerprints']} changed to "
            f"{second['source_fingerprints']}"
        )
    raise FoundryError("Custody roots did not reach a stable fingerprint: " + "; ".join(errors))


def load_custody_policy(path: Path) -> tuple[CustodyPolicy, bytes]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        policy = CustodyPolicy.model_validate(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
        raise FoundryError(f"Invalid custody policy: {exc}") from exc
    canonical = canonical_json(policy.model_dump(mode="json"))
    _validate_policy_paths(policy)
    return policy, canonical


def validate_custody_register(
    register_path: Path,
    policy_path: Path,
    config: FoundryConfig,
    outside_root: Path,
    workspace_root: Path,
) -> dict[str, Any]:
    policy, policy_bytes = load_custody_policy(policy_path)
    try:
        raw_bytes = register_path.read_bytes()
        register = CustodyRegister.model_validate_json(raw_bytes)
    except (OSError, ValidationError) as exc:
        raise FoundryError(f"Invalid custody register: {exc}") from exc
    canonical = canonical_json(register.model_dump(mode="json"))
    if raw_bytes != canonical:
        raise FoundryError("Custody register is not canonical JSON.")
    expected_policy_hash = hashlib.sha256(policy_bytes).hexdigest()
    if register.policy.sha256 != expected_policy_hash:
        raise FoundryError("Custody register policy hash does not match.")
    if (
        register.policy.schema_version != policy.schema_version
        or register.scan_algorithm_version != policy.scan_algorithm_version
    ):
        raise FoundryError("Custody register policy or algorithm version does not match.")
    outside = register.outside_files
    workspace = register.workspace_files
    for entries in (outside, workspace):
        paths = [entry.path for entry in entries]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise FoundryError("Custody register paths are not unique ordinal order.")
        for path in paths:
            _validate_relative_policy_path(path)
    package_records = {item.package_root: item for item in register.packages}
    if len(package_records) != len(register.packages):
        raise FoundryError("Custody package roots are not unique.")
    if [item.package_id for item in register.packages] != sorted(
        item.package_id for item in register.packages
    ):
        raise FoundryError("Custody package records are not in ordinal order.")
    package_policy = {item.package_root: item for item in policy.packages}
    license_policy = {item.binding_id: item for item in policy.license_bindings}
    expected_defects = []
    expected_eligible = 0
    for entry in outside:
        source_id, _hint, package_root = _package_for_path(entry.path, policy)
        expected_package_id = _package_id(source_id, package_root)
        package = package_records.get(package_root)
        if (
            package is None
            or entry.source_id != source_id
            or entry.package_root != package_root
            or entry.package_id != expected_package_id
            or package.package_id != expected_package_id
            or package.source_id != source_id
        ):
            raise FoundryError(f"Custody package membership mismatch: {entry.path}")
        declared = package_policy.get(package_root)
        expected_rights = declared.rights_status if declared else "missing"
        declared_ids = declared.license_binding_ids if declared else []
        applicable_ids = sorted(
            binding_id
            for binding_id in declared_ids
            if _path_in_scope(entry.path, license_policy[binding_id].scope_root)
        )
        package_ids = sorted(
            binding_id
            for binding_id in declared_ids
            if _path_in_scope(package_root, license_policy[binding_id].scope_root)
            or _path_in_scope(license_policy[binding_id].scope_root, package_root)
        )
        package_eligible = (
            source_id is not None and expected_rights == "documented" and bool(package_ids)
        )
        expected_file_eligible = package_eligible and not entry.excluded and bool(applicable_ids)
        if (
            package.rights_status != expected_rights
            or package.license_binding_ids != package_ids
            or package.promotion_eligible != package_eligible
            or entry.effective_rights_status != expected_rights
            or entry.license_binding_ids != applicable_ids
            or entry.promotion_eligible != expected_file_eligible
        ):
            raise FoundryError(f"Custody rights or eligibility mismatch: {entry.path}")
        exclusion = _matching_exclusion("outside_assets", entry.path, policy)
        if (
            entry.excluded != (exclusion is not None)
            or entry.exclusion_reason != (exclusion.reason if exclusion else None)
            or entry.exclusion_duplicate_participating
            != (exclusion.duplicate_participating if exclusion else False)
        ):
            raise FoundryError(f"Custody exclusion mismatch: {entry.path}")
        if expected_file_eligible:
            expected_eligible += 1
        elif not entry.excluded:
            expected_defects.append(
                {
                    "kind": "custody_ineligible",
                    "path": entry.path,
                    "reason": expected_rights,
                }
            )
    hashes: dict[str, list[dict[str, Any]]] = {}
    for entry in outside:
        participates = not entry.excluded or entry.exclusion_duplicate_participating
        digest = entry.sha256
        if participates and digest is None:
            raise FoundryError("Represented Outside file is missing SHA-256.")
        if participates and digest is not None:
            hashes.setdefault(digest, []).append(entry)
    expected_groups = []
    for digest, entries in hashes.items():
        expected = f"sha256:{digest}" if len(entries) > 1 else None
        if any(entry.duplicate_set_id != expected for entry in entries):
            raise FoundryError("Duplicate-set assignment does not reconcile.")
        if expected:
            size = entries[0].size_bytes
            expected_groups.append(
                {
                    "duplicate_set_id": expected,
                    "file_count": len(entries),
                    "size_bytes_each": size,
                    "potential_duplicate_bytes": size * (len(entries) - 1),
                }
            )
    expected_groups.sort(key=lambda item: item["duplicate_set_id"])
    actual_groups = [item.model_dump(mode="json") for item in register.duplicate_sets]
    if actual_groups != expected_groups:
        raise FoundryError("Duplicate-set summary does not reconcile.")
    represented = sum(not entry.excluded for entry in outside)
    excluded = len(outside) - represented
    outside_coverage = register.coverage["outside_assets"]
    workspace_coverage = register.coverage["foundry_workspace"]
    if (
        outside_coverage.discovered_files != len(outside)
        or outside_coverage.represented_files != represented
        or outside_coverage.excluded_files != excluded
        or not outside_coverage.reconciles
        or workspace_coverage.discovered_files != len(workspace)
        or workspace_coverage.represented_files != len(workspace)
        or workspace_coverage.excluded_files != 0
        or not workspace_coverage.reconciles
    ):
        raise FoundryError("Custody coverage equations do not reconcile.")
    candidates = {item.asset_id: item for item in register.workspace_candidates}
    if len(candidates) != len(register.workspace_candidates):
        raise FoundryError("Workspace candidate records are not unique.")
    for asset_id, candidate in candidates.items():
        owned = [item for item in workspace if item.asset_id == asset_id]
        counts: dict[str, int] = {}
        for item in owned:
            counts[item.storage_class] = counts.get(item.storage_class, 0) + 1
        if (
            candidate.physical_file_count != len(owned)
            or candidate.physical_bytes != sum(item.size_bytes for item in owned)
            or candidate.storage_class_counts != counts
            or candidate.deletability_claimed
        ):
            raise FoundryError(f"Workspace candidate totals do not reconcile: {asset_id}")
        holds = set(candidate.retention_hold_reasons)
        if (
            ("rejected_evidence" in holds) != (candidate.workflow_state == "rejected")
            or ("integrity_failure" in holds) != (not candidate.integrity.passed)
            or ("unregistered_content" in holds)
            != any(item.storage_class == "unregistered_file" for item in owned)
            or candidate.workflow_state in {"approved", "rejected"}
            and "active_workflow" in holds
        ):
            raise FoundryError(f"Workspace retention facts do not reconcile: {asset_id}")
    actual_defects = [item.model_dump(mode="json") for item in register.defects]
    if actual_defects != expected_defects:
        raise FoundryError("Custody defect list does not reconcile.")
    expected_counts = {
        "outside_files": len(outside),
        "workspace_files": len(workspace),
        "packages": len(register.packages),
        "eligible_outside_files": expected_eligible,
        "duplicate_groups": len(expected_groups),
        "duplicate_files": sum(item["file_count"] for item in expected_groups),
        "potential_duplicate_bytes": sum(
            item["potential_duplicate_bytes"] for item in expected_groups
        ),
    }
    if register.counts.model_dump(mode="json") != expected_counts:
        raise FoundryError("Custody count summary does not reconcile.")
    authoritative = build_custody_inventory(
        config,
        outside_root,
        workspace_root,
        policy_path,
    )
    if authoritative.register_bytes != raw_bytes:
        raise FoundryError("Custody register does not match current root authority.")
    return {
        "schema_version": REGISTER_SCHEMA,
        "valid": True,
        "policy_sha256": expected_policy_hash,
        "outside_files": len(outside),
        "workspace_files": len(workspace),
    }


def write_custody_outputs(
    result: CustodyInventoryResult,
    register_path: Path,
    report_path: Path,
    scanned_roots: tuple[Path, ...],
) -> None:
    register_resolved = register_path.resolve(strict=False)
    report_resolved = report_path.resolve(strict=False)
    for output in (register_resolved, report_resolved):
        if any(_is_within(output, root.resolve(strict=True)) for root in scanned_roots):
            raise FoundryError("Custody outputs must be outside scanned roots.")
        if output.exists():
            raise FoundryError(f"Custody output already exists: {output}")
    if not register_path.parent.is_dir() or not report_path.parent.is_dir():
        raise FoundryError("Custody output parent directories must already exist.")
    _reject_reparse_ancestors(register_path.parent)
    _reject_reparse_ancestors(report_path.parent)
    parent_fingerprints = {
        register_path.parent: _ancestor_fingerprint(register_path.parent),
        report_path.parent: _ancestor_fingerprint(report_path.parent),
    }
    temporary_register = register_path.with_name(f".{register_path.name}.{os.getpid()}.tmp")
    temporary_report = report_path.with_name(f".{report_path.name}.{os.getpid()}.tmp")
    created: list[Path] = []
    try:
        with temporary_register.open("xb") as stream:
            stream.write(result.register_bytes)
        with temporary_report.open("xb") as stream:
            stream.write(result.report_bytes)
        os.link(temporary_register, register_path)
        created.append(register_path)
        os.link(temporary_report, report_path)
        created.append(report_path)
        for parent, expected in parent_fingerprints.items():
            if _ancestor_fingerprint(parent) != expected:
                raise FoundryError(f"Custody output ancestry changed during publication: {parent}")
        for output in (register_path.resolve(strict=True), report_path.resolve(strict=True)):
            if any(_is_within(output, root.resolve(strict=True)) for root in scanned_roots):
                raise FoundryError("Custody output was redirected into a scanned root.")
    except OSError as exc:
        for path in created:
            path.unlink(missing_ok=True)
        raise FoundryError(f"Could not create custody outputs exclusively: {exc}") from exc
    finally:
        temporary_register.unlink(missing_ok=True)
        temporary_report.unlink(missing_ok=True)


def _scan_all(
    config: FoundryConfig,
    outside_root: Path,
    workspace_root: Path,
    policy: CustodyPolicy,
    policy_bytes: bytes,
) -> dict[str, Any]:
    outside_physical = _scan_root(outside_root)
    workspace_physical = _scan_root(workspace_root)
    library_physical = _scan_root(config.foundry.asset_library_root.resolve(strict=True))
    license_map = _validated_license_bindings(outside_root, policy, outside_physical)
    outside_entries, packages = _outside_entries(outside_physical, policy, license_map)
    workspace_entries, candidates = _workspace_entries(
        config, workspace_root, workspace_physical, policy
    )
    groups: dict[str, list[dict[str, Any]]] = {}
    for entry in outside_entries:
        if (not entry["excluded"] or entry["exclusion_duplicate_participating"]) and entry[
            "sha256"
        ] is not None:
            groups.setdefault(entry["sha256"], []).append(entry)
    duplicate_groups = []
    for digest, entries in sorted(groups.items()):
        duplicate_id = f"sha256:{digest}" if len(entries) > 1 else None
        for entry in entries:
            entry["duplicate_set_id"] = duplicate_id
        if duplicate_id:
            size = entries[0]["size_bytes"]
            duplicate_groups.append(
                {
                    "duplicate_set_id": duplicate_id,
                    "file_count": len(entries),
                    "size_bytes_each": size,
                    "potential_duplicate_bytes": size * (len(entries) - 1),
                }
            )
    outside_entries.sort(key=lambda item: item["path"])
    workspace_entries.sort(key=lambda item: item["path"])
    represented = sum(not entry["excluded"] for entry in outside_entries)
    excluded = len(outside_entries) - represented
    defects = [
        {
            "kind": "custody_ineligible",
            "path": entry["path"],
            "reason": entry["effective_rights_status"],
        }
        for entry in outside_entries
        if not entry["excluded"] and not entry["promotion_eligible"]
    ]
    register = {
        "schema_version": REGISTER_SCHEMA,
        "scan_algorithm_version": policy.scan_algorithm_version,
        "roots": ["outside_assets", "foundry_workspace"],
        "policy": {
            "schema_version": policy.schema_version,
            "sha256": hashlib.sha256(policy_bytes).hexdigest(),
        },
        "outside_files": outside_entries,
        "packages": sorted(packages, key=lambda item: item["package_id"]),
        "duplicate_sets": duplicate_groups,
        "workspace_files": workspace_entries,
        "workspace_candidates": sorted(candidates, key=lambda item: item["asset_id"]),
        "coverage": {
            "outside_assets": {
                "discovered_files": len(outside_physical),
                "represented_files": represented,
                "excluded_files": excluded,
                "reconciles": len(outside_physical) == represented + excluded,
            },
            "foundry_workspace": {
                "discovered_files": len(workspace_physical),
                "represented_files": len(workspace_entries),
                "excluded_files": 0,
                "reconciles": len(workspace_physical) == len(workspace_entries),
            },
        },
        "counts": {
            "outside_files": len(outside_physical),
            "workspace_files": len(workspace_physical),
            "packages": len(packages),
            "eligible_outside_files": sum(
                bool(entry["promotion_eligible"]) for entry in outside_entries
            ),
            "duplicate_groups": len(duplicate_groups),
            "duplicate_files": sum(group["file_count"] for group in duplicate_groups),
            "potential_duplicate_bytes": sum(
                group["potential_duplicate_bytes"] for group in duplicate_groups
            ),
        },
        "defects": defects,
    }
    return {
        "register": register,
        "source_fingerprints": {
            "outside_assets": _records_fingerprint(outside_physical),
            "foundry_workspace": _records_fingerprint(workspace_physical),
            "asset_library": _records_fingerprint(library_physical),
        },
    }


def _scan_root(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            children = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as exc:
            raise FoundryError(f"Unreadable custody directory: {directory}: {exc}") from exc
        for child in children:
            relative = _relative_posix(Path(child.path), root)
            try:
                info = child.stat(follow_symlinks=False)
            except OSError as exc:
                raise FoundryError(f"Unreadable custody entry: {relative}: {exc}") from exc
            if child.is_symlink() or getattr(info, "st_file_attributes", 0) & REPARSE_POINT:
                raise FoundryError(f"Reparse point or symlink is not permitted: {relative}")
            if child.is_dir(follow_symlinks=False):
                pending.append(Path(child.path))
            elif child.is_file(follow_symlinks=False):
                digest, size = _stable_hash(Path(child.path), info, root)
                records.append({"path": relative, "sha256": digest, "size_bytes": size})
            else:
                raise FoundryError(f"Unsupported custody entry kind: {relative}")
    records.sort(key=lambda item: item["path"])
    return records


def _stable_hash(
    path: Path,
    _discovery_info: os.stat_result,
    root: Path | None = None,
) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        if root is not None:
            _reject_reparse_ancestors(path.parent)
            _relative_posix(path, root)
            ancestor_before = _ancestor_fingerprint(path.parent)
        else:
            ancestor_before = None
        before = path.lstat()
        with _open_no_reparse(path) as stream:
            opened = os.fstat(stream.fileno())
            if getattr(opened, "st_file_attributes", 0) & REPARSE_POINT:
                raise FoundryError(f"Reparse point opened during hashing: {path}")
            while chunk := stream.read(BUFFER_SIZE):
                digest.update(chunk)
                size += len(chunk)
        after = path.lstat()
        if root is not None:
            _reject_reparse_ancestors(path.parent)
            _relative_posix(path, root)
            if _ancestor_fingerprint(path.parent) != ancestor_before:
                raise FoundryError(f"File ancestry changed while hashing: {path}")
    except OSError as exc:
        raise FoundryError(f"Unreadable custody file: {path}: {exc}") from exc
    before_id = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    opened_id = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
    after_id = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    discovery_identity_available = bool(_discovery_info.st_dev or _discovery_info.st_ino)
    discovery_mismatch = (
        _discovery_info.st_size != before.st_size
        or _discovery_info.st_mtime_ns != before.st_mtime_ns
        or (
            discovery_identity_available
            and (_discovery_info.st_dev, _discovery_info.st_ino) != (before.st_dev, before.st_ino)
        )
    )
    if (
        discovery_mismatch
        or before_id != opened_id
        or opened_id != after_id
        or size != before.st_size
    ):
        raise FoundryError(f"File changed while hashing: {path}")
    return digest.hexdigest(), size


def _validated_license_bindings(
    outside_root: Path,
    policy: CustodyPolicy,
    files: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    by_path = {entry["path"]: entry for entry in files}
    bindings: dict[str, dict[str, Any]] = {}
    for binding in policy.license_bindings:
        if binding.binding_id in bindings:
            raise FoundryError(f"Duplicate license binding ID: {binding.binding_id}")
        evidence = by_path.get(binding.evidence_path)
        if evidence is None:
            raise FoundryError(f"Missing license evidence target: {binding.evidence_path}")
        if evidence["sha256"] != binding.evidence_sha256:
            raise FoundryError(f"License evidence hash mismatch: {binding.evidence_path}")
        _relative_posix(outside_root / binding.scope_root, outside_root)
        bindings[binding.binding_id] = binding.model_dump(mode="json")
    return bindings


def _outside_entries(
    files: list[dict[str, Any]],
    policy: CustodyPolicy,
    license_map: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    package_policies = {item.package_root: item for item in policy.packages}
    package_records: dict[str, dict[str, Any]] = {}
    results = []
    for physical in files:
        path = physical["path"]
        exclusion = _matching_exclusion("outside_assets", path, policy)
        source_id, hint, package_root = _package_for_path(path, policy)
        package_policy = package_policies.get(package_root)
        rights = package_policy.rights_status if package_policy else "missing"
        binding_ids = package_policy.license_binding_ids if package_policy else []
        applicable = []
        semantics = set()
        for binding_id in binding_ids:
            binding = license_map.get(binding_id)
            if binding is None:
                raise FoundryError(f"Unknown license binding ID: {binding_id}")
            if _path_in_scope(path, binding["scope_root"]):
                applicable.append(binding_id)
                semantics.add((binding["evidence_sha256"], binding["rights_semantics"]))
        if len(semantics) > 1:
            raise FoundryError(f"Conflicting license scopes apply to: {path}")
        if rights == "documented" and not applicable:
            raise FoundryError(f"Documented rights lack applicable evidence: {package_root}")
        package_id = _package_id(source_id, package_root)
        package_eligible = source_id is not None and rights == "documented" and bool(applicable)
        eligible = exclusion is None and package_eligible
        package_records.setdefault(
            package_id,
            {
                "package_id": package_id,
                "package_root": package_root,
                "source_id": source_id,
                "rights_status": rights,
                "license_binding_ids": sorted(applicable),
                "promotion_eligible": package_eligible,
            },
        )
        results.append(
            {
                "path": path,
                "entry_kind": "regular_file",
                "size_bytes": physical["size_bytes"],
                "sha256": physical["sha256"] if exclusion is None or exclusion.hash_file else None,
                "source_id": source_id,
                "mechanical_source_hint": hint,
                "package_id": package_id,
                "package_root": package_root,
                "effective_rights_status": rights,
                "license_binding_ids": sorted(applicable),
                "excluded": exclusion is not None,
                "exclusion_reason": exclusion.reason if exclusion else None,
                "exclusion_duplicate_participating": (
                    exclusion.duplicate_participating if exclusion else False
                ),
                "promotion_eligible": eligible,
                "duplicate_set_id": None,
            }
        )
    return results, list(package_records.values())


def _workspace_entries(
    config: FoundryConfig,
    workspace_root: Path,
    files: list[dict[str, Any]],
    policy: CustodyPolicy,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    repository = ManifestRepository(workspace_root)
    manifests = {}
    assets_root = workspace_root / "assets"
    if assets_root.exists():
        for child in sorted(assets_root.iterdir(), key=lambda item: item.name):
            if child.is_dir() and (child / "manifest.json").is_file():
                manifests[child.name] = repository.load(child.name)
    managed: dict[str, tuple[str, str]] = {}
    for asset_id, manifest in manifests.items():
        managed[f"assets/{asset_id}/manifest.json"] = (asset_id, "candidate_manifest")
        managed[f"assets/{asset_id}/events.jsonl"] = (asset_id, "managed_manifest_artifact")
        for artifact in manifest.artifacts:
            managed[f"assets/{asset_id}/{artifact.path}"] = (
                asset_id,
                "managed_manifest_artifact",
            )
    entries = []
    per_candidate: dict[str, list[dict[str, Any]]] = {key: [] for key in manifests}
    for physical in files:
        path = physical["path"]
        owner = managed.get(path)
        asset_id = owner[0] if owner else _candidate_id_from_path(path, manifests)
        if owner:
            storage_class = owner[1]
        elif any(_path_in_scope(path, rule) for rule in policy.workspace_temp_paths):
            storage_class = "generated_cache_or_temp"
        else:
            storage_class = "unregistered_file"
        entry = {
            "path": path,
            "entry_kind": "regular_file",
            "size_bytes": physical["size_bytes"],
            "sha256": physical["sha256"],
            "asset_id": asset_id,
            "storage_class": storage_class,
        }
        entries.append(entry)
        if asset_id:
            per_candidate[asset_id].append(entry)
    candidates = []
    for asset_id, manifest in manifests.items():
        candidate_files = per_candidate[asset_id]
        integrity = audit_asset(config, asset_id)
        holds = []
        if manifest.workflow.state.value not in {"approved", "rejected"}:
            holds.append("active_workflow")
        if manifest.approval.approved or manifest.release.released:
            holds.append("approval_or_release_history")
        if manifest.workflow.state.value == "rejected":
            holds.append("rejected_evidence")
        if not integrity.passed:
            holds.append("integrity_failure")
        if any(item["storage_class"] == "unregistered_file" for item in candidate_files):
            holds.append("unregistered_content")
        class_counts: dict[str, int] = {}
        for item in candidate_files:
            class_counts[item["storage_class"]] = class_counts.get(item["storage_class"], 0) + 1
        candidates.append(
            {
                "asset_id": asset_id,
                "manifest_revision": manifest.revision,
                "workflow_state": manifest.workflow.state.value,
                "artifact_record_count": len(manifest.artifacts),
                "physical_file_count": len(candidate_files),
                "physical_bytes": sum(item["size_bytes"] for item in candidate_files),
                "released_revision": manifest.release.release_revision,
                "storage_class_counts": class_counts,
                "integrity": {
                    "authority": "audit_asset",
                    "passed": integrity.passed,
                },
                "retention_hold_reasons": sorted(holds),
                "deletability_claimed": False,
            }
        )
    return entries, candidates


def _package_for_path(path: str, policy: CustodyPolicy) -> tuple[str | None, str | None, str]:
    matches = [rule for rule in policy.source_rules if _path_in_scope(path, rule.path_prefix)]
    if len(matches) > 1:
        raise FoundryError(f"Ambiguous source policy for: {path}")
    if not matches:
        parts = PurePosixPath(path).parts
        hint = parts[0].lower() if parts else None
        return None, hint, path
    rule = matches[0]
    suffix = PurePosixPath(path).relative_to(PurePosixPath(rule.path_prefix)).parts
    if not suffix:
        raise FoundryError(f"Source path has no package identity: {path}")
    if rule.package_mode == "first_child" and len(suffix) > 1:
        package_root = str(PurePosixPath(rule.path_prefix) / suffix[0])
    else:
        package_root = path
    return rule.source_id, PurePosixPath(path).parts[0].lower(), package_root


def _matching_exclusion(logical_root: str, path: str, policy: CustodyPolicy):
    matches = [
        item
        for item in policy.exclusions
        if item.logical_root == logical_root and item.path == path
    ]
    if len(matches) > 1:
        raise FoundryError(f"Overlapping exclusions for: {logical_root}:{path}")
    return matches[0] if matches else None


def _validate_policy_paths(policy: CustodyPolicy) -> None:
    paths = [
        *(item.evidence_path for item in policy.license_bindings),
        *(item.scope_root for item in policy.license_bindings),
        *(item.path_prefix for item in policy.source_rules),
        *(item.package_root for item in policy.packages),
        *(item.path for item in policy.exclusions),
        *policy.workspace_temp_paths,
    ]
    for value in paths:
        _validate_relative_policy_path(value)
    _require_unique([item.source_id for item in policy.source_rules], "source IDs")
    _require_unique([item.path_prefix for item in policy.source_rules], "source path prefixes")
    _require_unique([item.package_root for item in policy.packages], "package roots")
    _require_unique([item.binding_id for item in policy.license_bindings], "license binding IDs")
    _require_unique(
        [f"{item.logical_root}:{item.path}" for item in policy.exclusions],
        "exclusion keys",
    )
    binding_ids = {item.binding_id for item in policy.license_bindings}
    for item in policy.packages:
        if item.rights_status == "documented" and not item.license_binding_ids:
            raise FoundryError(f"Documented package has no license bindings: {item.package_root}")
        if any(binding_id not in binding_ids for binding_id in item.license_binding_ids):
            raise FoundryError(
                f"Package references an unknown license binding: {item.package_root}"
            )
    for item in policy.exclusions:
        if item.duplicate_participating and not item.hash_file:
            raise FoundryError("Duplicate-participating exclusions must be hashed.")


def _validate_relative_policy_path(value: str) -> None:
    pure = PurePosixPath(value)
    if (
        not value
        or value == "."
        or pure.is_absolute()
        or ".." in pure.parts
        or "\\" in value
        or str(pure) != value
    ):
        raise FoundryError(f"Custody path is not normalized relative POSIX: {value}")


def _require_unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise FoundryError(f"Custody policy contains duplicate {label}.")


def _relative_posix(path: Path, root: Path) -> str:
    try:
        relative = path.resolve(strict=False).relative_to(root.resolve(strict=True))
    except ValueError as exc:
        raise FoundryError(f"Custody path escapes root: {path}") from exc
    value = relative.as_posix()
    if not value or value == "." or ".." in PurePosixPath(value).parts:
        raise FoundryError(f"Invalid custody relative path: {path}")
    return value


def _path_in_scope(path: str, scope: str) -> bool:
    path_parts = PurePosixPath(path).parts
    scope_parts = PurePosixPath(scope).parts
    return path_parts[: len(scope_parts)] == scope_parts


def _package_id(source_id: str | None, package_root: str) -> str:
    authority = source_id or "unknown"
    digest = hashlib.sha256(f"{authority}\n{package_root}".encode()).hexdigest()[:24]
    return f"pkg:{authority}:{digest}"


def _candidate_id_from_path(path: str, manifests: dict[str, Any]) -> str | None:
    parts = PurePosixPath(path).parts
    if len(parts) >= 3 and parts[0] == "assets" and parts[1] in manifests:
        return parts[1]
    return None


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _records_fingerprint(records: list[dict[str, Any]]) -> str:
    return hashlib.sha256(canonical_json(records)).hexdigest()


def _open_no_reparse(path: Path):
    if sys.platform != "win32":
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        return os.fdopen(descriptor, "rb")
    import ctypes
    import msvcrt
    from ctypes import wintypes

    create_file = ctypes.WinDLL("kernel32", use_last_error=True).CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    handle = create_file(
        str(path),
        0x80000000,
        0x00000001 | 0x00000002 | 0x00000004,
        None,
        3,
        0x00200000 | 0x08000000,
        None,
    )
    if handle == wintypes.HANDLE(-1).value:
        raise OSError(ctypes.get_last_error(), f"Could not open without following reparse: {path}")
    descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    return os.fdopen(descriptor, "rb")


def _reject_reparse_ancestors(path: Path) -> None:
    _ancestor_fingerprint(path)


def _ancestor_fingerprint(path: Path) -> tuple[tuple[str, int, int, int], ...]:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    result = []
    for part in absolute.parts[1:]:
        current /= part
        info = current.lstat()
        if getattr(info, "st_file_attributes", 0) & REPARSE_POINT or current.is_symlink():
            raise FoundryError(f"Custody output ancestor is a reparse point: {current}")
        result.append(
            (
                current.name,
                info.st_dev,
                info.st_ino,
                getattr(info, "st_file_attributes", 0),
            )
        )
    return tuple(result)
