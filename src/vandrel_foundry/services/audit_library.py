import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.ids import validate_asset_id
from vandrel_foundry.domain.release_descriptor import (
    format_release_revision,
    validate_release_descriptor,
)
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path


@dataclass(frozen=True)
class LibraryAuditCheck:
    subject: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class LibraryAuditResult:
    checks: tuple[LibraryAuditCheck, ...]

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(check.passed for check in self.checks)


def audit_library(config: FoundryConfig) -> LibraryAuditResult:
    root = config.foundry.asset_library_root
    catalog_path = root / "catalog.json"
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FoundryError(f"Asset-library catalog does not exist: {catalog_path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise FoundryError(f"Could not read asset-library catalog: {exc}") from exc
    assets = _catalog_assets(catalog)
    checks: list[LibraryAuditCheck] = [
        LibraryAuditCheck("catalog", True, "schema_version 1"),
    ]
    cataloged_directories: set[Path] = set()
    for asset_id, asset_entry in sorted(assets.items()):
        checks.extend(_audit_asset(root, asset_id, asset_entry, cataloged_directories))
    checks.extend(_orphan_checks(root, cataloged_directories))
    return LibraryAuditResult(tuple(checks))


def audit_library_asset(config: FoundryConfig, asset_id: str) -> LibraryAuditResult | None:
    """Audit one cataloged asset without inspecting unrelated library entries."""
    root = config.foundry.asset_library_root
    catalog_path = root / "catalog.json"
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise FoundryError(f"Could not read asset-library catalog: {exc}") from exc
    assets = _catalog_assets(catalog)
    entry = assets.get(asset_id)
    if entry is None:
        return None
    checks = _audit_asset(root, asset_id, entry, set())
    return LibraryAuditResult(tuple(checks))


def _catalog_assets(catalog: Any) -> dict[str, Any]:
    if not isinstance(catalog, dict) or catalog.get("schema_version") != 1:
        raise FoundryError("Asset-library catalog has an unsupported schema.")
    assets = catalog.get("assets")
    if not isinstance(assets, dict):
        raise FoundryError("Asset-library catalog assets must be an object.")
    return assets


def _audit_asset(
    root: Path,
    asset_id: str,
    entry: Any,
    cataloged_directories: set[Path],
) -> list[LibraryAuditCheck]:
    try:
        validate_asset_id(asset_id)
    except (ValueError, FoundryError) as exc:
        return [LibraryAuditCheck(asset_id, False, f"invalid asset ID: {exc}")]
    if not isinstance(entry, dict) or not isinstance(entry.get("releases"), list):
        return [LibraryAuditCheck(asset_id, False, "catalog asset entry is malformed")]
    releases = entry["releases"]
    revisions = [item.get("revision") for item in releases if isinstance(item, dict)]
    checks: list[LibraryAuditCheck] = []
    valid_revisions = [
        value
        for value in revisions
        if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 999
    ]
    expected_latest = max(valid_revisions, default=None)
    checks.append(
        LibraryAuditCheck(
            f"{asset_id}:latest",
            entry.get("latest_revision") == expected_latest,
            f"expected {expected_latest}, found {entry.get('latest_revision')}",
        )
    )
    if len(valid_revisions) != len(releases) or len(set(valid_revisions)) != len(releases):
        checks.append(
            LibraryAuditCheck(
                f"{asset_id}:revisions",
                False,
                "release revisions must be unique integers in the range 1..999",
            )
        )
    for release in releases:
        if not isinstance(release, dict) or not isinstance(release.get("revision"), int):
            continue
        checks.extend(_audit_release(root, asset_id, release, cataloged_directories))
    return checks


def _audit_release(
    root: Path,
    asset_id: str,
    entry: dict[str, Any],
    cataloged_directories: set[Path],
) -> list[LibraryAuditCheck]:
    revision = entry["revision"]
    try:
        formatted_revision = format_release_revision(revision)
    except FoundryError as exc:
        return [LibraryAuditCheck(f"{asset_id}:revision", False, str(exc))]
    subject = f"{asset_id}:{formatted_revision}"
    expected_path = f"assets/{asset_id}/{formatted_revision}/asset-release.json"
    if entry.get("path") != expected_path:
        return [LibraryAuditCheck(subject, False, "catalog descriptor path is not canonical")]
    try:
        descriptor_path = contained_path(root, expected_path)
    except ValueError as exc:
        return [LibraryAuditCheck(subject, False, f"unsafe descriptor path: {exc}")]
    cataloged_directories.add(descriptor_path.parent.resolve())
    try:
        descriptor_bytes = descriptor_path.read_bytes()
        descriptor = json.loads(descriptor_bytes)
    except (OSError, json.JSONDecodeError) as exc:
        return [LibraryAuditCheck(subject, False, f"descriptor unavailable: {exc}")]
    descriptor_hash_matches = _sha256(descriptor_bytes) == entry.get("descriptor_sha256")
    try:
        validate_release_descriptor(descriptor)
        descriptor_schema_valid = True
        descriptor_schema_detail = "descriptor matches its versioned executable schema"
    except ValidationError as exc:
        descriptor_schema_valid = False
        descriptor_schema_detail = f"descriptor schema invalid: {exc}"
    checks = [
        LibraryAuditCheck(
            f"{subject}:descriptor_hash",
            descriptor_hash_matches,
            (
                "descriptor hash matches catalog"
                if descriptor_hash_matches
                else "descriptor hash differs from catalog"
            ),
        ),
        LibraryAuditCheck(
            f"{subject}:schema",
            descriptor_schema_valid,
            descriptor_schema_detail,
        ),
        LibraryAuditCheck(
            f"{subject}:identity",
            isinstance(descriptor, dict)
            and descriptor.get("schema_version") in {1, 2}
            and descriptor.get("asset_id") == asset_id
            and descriptor.get("release_revision") == revision,
            "descriptor identity matches catalog",
        ),
    ]
    if isinstance(descriptor, dict) and descriptor.get("schema_version") == 2:
        custody = descriptor.get("custody")
        files = descriptor.get("files")
        custody_files = {
            (
                item.get("role"),
                item.get("path"),
                item.get("sha256"),
                item.get("size_bytes"),
                item.get("source_artifact_id"),
            )
            for item in (files if isinstance(files, list) else [])
            if isinstance(item, dict) and item.get("role") == "custody_license_evidence"
        }
        evidence = (
            [
                item
                for contribution in custody.get("source_contributions", [])
                if isinstance(contribution, dict)
                for item in contribution.get("license_evidence", [])
                if isinstance(item, dict)
            ]
            if isinstance(custody, dict)
            else []
        )
        custody_ok = (
            isinstance(custody, dict)
            and custody.get("assessment_status") == "evaluated"
            and custody.get("effective_rights_status") == "documented"
            and isinstance(custody.get("semantic_assertion_sha256"), str)
            and len(custody["semantic_assertion_sha256"]) == 64
            and isinstance(custody.get("source_contributions"), list)
            and bool(custody["source_contributions"])
            and bool(evidence)
            and all(
                (
                    "custody_license_evidence",
                    item.get("release_path"),
                    item.get("sha256"),
                    item.get("size_bytes"),
                    item.get("source_artifact_id"),
                )
                in custody_files
                for item in evidence
            )
        )
        checks.append(
            LibraryAuditCheck(
                f"{subject}:custody",
                custody_ok,
                "v2 descriptor has evaluated documented custody",
            )
        )
        evidence_roles_ok = _v2_evidence_roles_reconcile(
            descriptor, descriptor_path.parent
        )
        checks.append(
            LibraryAuditCheck(
                f"{subject}:evidence_roles",
                evidence_roles_ok,
                (
                    "primary payload, custody, and declared evidence roles reconcile"
                    if evidence_roles_ok
                    else "release evidence role or source binding is inconsistent"
                ),
            )
        )
    if not isinstance(descriptor, dict) or not isinstance(descriptor.get("files"), list):
        checks.append(LibraryAuditCheck(f"{subject}:files", False, "descriptor files malformed"))
        return checks
    for file_entry in descriptor["files"]:
        checks.append(_audit_file(descriptor_path.parent, subject, file_entry))
    return checks


def _audit_file(release_root: Path, subject: str, entry: Any) -> LibraryAuditCheck:
    if not isinstance(entry, dict):
        return LibraryAuditCheck(f"{subject}:file", False, "file entry is malformed")
    relative = entry.get("path")
    try:
        safe = RelativeManifestPath.validate(relative)
        path = contained_path(release_root, safe)
        content = path.read_bytes()
    except (OSError, TypeError, ValueError) as exc:
        return LibraryAuditCheck(f"{subject}:{relative}", False, f"file unavailable: {exc}")
    passed = _sha256(content) == entry.get("sha256") and len(content) == entry.get("size_bytes")
    return LibraryAuditCheck(
        f"{subject}:{safe}",
        passed,
        "hash and size match descriptor" if passed else "hash or size differs from descriptor",
    )


def _v2_evidence_roles_reconcile(
    descriptor: dict[str, Any], release_root: Path
) -> bool:
    files = descriptor.get("files")
    if not isinstance(files, list) or not all(isinstance(item, dict) for item in files):
        return False
    file_bindings = {
        (
            item.get("role"),
            item.get("path"),
            item.get("sha256"),
            item.get("size_bytes"),
            item.get("source_artifact_id"),
        )
        for item in files
    }
    lane = descriptor.get("lane")
    primary_payload = descriptor.get("primary_payload") or "model"
    model_files = [item for item in files if item.get("role") == "model"]
    library_files = [item for item in files if item.get("role") == "animation_library"]
    animation_library = descriptor.get("animation_library")
    if primary_payload == "clean_body":
        clean_body = descriptor.get("clean_body")
        if (
            lane != "humanoid"
            or len(model_files) != 1
            or library_files
            or animation_library is not None
            or not isinstance(clean_body, dict)
            or model_files[0].get("sha256") != clean_body.get("output_sha256")
        ):
            return False
        for role, report_name in (
            ("clean_body_processing_report", "processing_report"),
            ("clean_body_technical_report", "technical_report"),
            ("clean_body_godot_monitor_report", "monitor_report"),
            ("clean_body_visual_review_report", "visual_review_report"),
        ):
            report = clean_body.get(report_name)
            if not isinstance(report, dict) or (role, report.get("release_path"), report.get("sha256"), report.get("size_bytes"), report.get("source_artifact_id")) not in file_bindings:
                return False
        dependency_hashes = {item.get("sha256") for item in files if item.get("role") in {"clean_body_buffer", "clean_body_albedo"}}
        if dependency_hashes != set(clean_body.get("dependency_sha256s", [])):
            return False
    elif lane == "animation_library":
        if (
            primary_payload != "animation_library"
            or model_files
            or len(library_files) != 1
            or not isinstance(animation_library, dict)
            or library_files[0].get("sha256") != animation_library.get("output_sha256")
        ):
            return False
        for role, report_name in (
            ("animation_library_technical_report", "technical_report"),
            ("animation_library_godot_monitor_report", "monitor_report"),
            ("animation_library_isolation_report", "isolation_report"),
            ("animation_library_visual_matrix_report", "visual_matrix_report"),
        ):
            report = animation_library.get(report_name)
            if (
                not isinstance(report, dict)
                or (
                    role,
                    report.get("release_path"),
                    report.get("sha256"),
                    report.get("size_bytes"),
                    report.get("source_artifact_id"),
                )
                not in file_bindings
            ):
                return False
        import_policy = animation_library.get("import_policy")
        expected_processor_version = (
            "5"
            if import_policy
            == "godot_skeleton_profile_humanoid_meshy_bone_map_rest_fixer_carrier_bake_v2"
            else "4"
        )
        technical_binding = animation_library.get("technical_report")
        technical_file = next(
            (
                item
                for item in files
                if item.get("role") == "animation_library_technical_report"
                and isinstance(technical_binding, dict)
                and item.get("path") == technical_binding.get("release_path")
            ),
            None,
        )
        if (
            import_policy
            not in {
                "godot_skeleton_profile_humanoid_meshy_bone_map_rest_fixer_v1",
                "godot_skeleton_profile_humanoid_meshy_bone_map_rest_fixer_carrier_bake_v2",
            }
            or animation_library.get("processor_version")
            != expected_processor_version
            or not isinstance(technical_file, dict)
        ):
            return False
        try:
            technical_path = contained_path(
                release_root,
                RelativeManifestPath.validate(technical_file.get("path")),
            )
            technical_bytes = technical_path.read_bytes()
            technical_value = json.loads(technical_bytes)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return False
        if (
            _sha256(technical_bytes) != technical_file.get("sha256")
            or len(technical_bytes) != technical_file.get("size_bytes")
            or not isinstance(technical_value, dict)
            or technical_value.get("import_policy") != import_policy
        ):
            return False
    elif (
        primary_payload != "model"
        or len(model_files) != 1
        or library_files
        or animation_library is not None
    ):
        return False
    custody = descriptor.get("custody")
    if not isinstance(custody, dict):
        return False
    contributions = custody.get("source_contributions")
    if not isinstance(contributions, list):
        return False
    for contribution in contributions:
        if not isinstance(contribution, dict):
            return False
        evidence_items = contribution.get("license_evidence")
        if not isinstance(evidence_items, list):
            return False
        for evidence in evidence_items:
            if (
                not isinstance(evidence, dict)
                or (
                    "custody_license_evidence",
                    evidence.get("release_path"),
                    evidence.get("sha256"),
                    evidence.get("size_bytes"),
                    evidence.get("source_artifact_id"),
                )
                not in file_bindings
            ):
                return False
    humanoid = descriptor.get("humanoid_compatibility")
    if humanoid is None:
        return True
    if not isinstance(humanoid, dict) or not isinstance(humanoid.get("report"), dict):
        return False
    report = humanoid["report"]
    return (
        "humanoid_compatibility_report",
        report.get("release_path"),
        report.get("sha256"),
        report.get("size_bytes"),
        report.get("source_artifact_id"),
    ) in file_bindings


def _orphan_checks(root: Path, cataloged: set[Path]) -> list[LibraryAuditCheck]:
    assets_root = root / "assets"
    if not assets_root.is_dir():
        return []
    checks: list[LibraryAuditCheck] = []
    for path in sorted(assets_root.glob("*/r*")):
        if not path.is_dir():
            continue
        if not (
            len(path.name) == 4
            and path.name.startswith("r")
            and path.name[1:].isdigit()
            and 1 <= int(path.name[1:]) <= 999
        ):
            checks.append(
                LibraryAuditCheck(
                    path.relative_to(root).as_posix(),
                    False,
                    "release directory must use canonical r001..r999 layout",
                )
            )
        elif path.resolve() not in cataloged:
            checks.append(
                LibraryAuditCheck(
                    path.relative_to(root).as_posix(),
                    False,
                    "release directory is absent from catalog",
                )
            )
    return checks


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
