"""Fast, read-only custody root readability preflight."""

from __future__ import annotations

import csv
import getpass
import os
import platform
import re
import stat
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.custody_preflight import (
    CustodyGovernedTarget,
    CustodyPreflightSetupIssue,
    CustodyPrincipal,
    CustodyReadabilityCounts,
    CustodyReadabilityIssue,
    CustodyReadabilityPreflight,
    CustodyRootReadability,
)
from vandrel_foundry.domain.errors import FoundryError

PREFLIGHT_SCHEMA = "vandrel_foundry_custody_readability_preflight/1.0"
REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


@dataclass(frozen=True)
class ProbeResult:
    files: int
    directories: int
    issues: tuple[CustodyReadabilityIssue, ...]


def preflight_custody_readability(
    config: FoundryConfig,
    outside_root: Path,
    workspace_root: Path,
    *,
    principal_resolver: Callable[[], CustodyPrincipal] | None = None,
) -> CustodyReadabilityPreflight:
    """Probe traversal and file-open access without reading file content."""
    principal = (principal_resolver or _current_principal)()
    setup_issues: list[CustodyPreflightSetupIssue] = []
    if principal.resolution_status != "exact":
        setup_issues.append(
            CustodyPreflightSetupIssue(
                code="principal_unresolved",
                logical_root=None,
                path=None,
                detail="Current OS principal identifier could not be resolved exactly.",
            )
        )
    root_inputs = (
        ("outside_assets", outside_root),
        ("foundry_workspace", workspace_root),
        ("asset_library", config.foundry.asset_library_root),
    )
    resolved_roots: dict[str, Path] = {}
    for logical_root, path in root_inputs:
        try:
            resolved_roots[logical_root] = _resolve_authoritative_root(path)
        except FoundryError as exc:
            setup_issues.append(
                CustodyPreflightSetupIssue(
                    code="root_unavailable",
                    logical_root=logical_root,
                    path=str(path),
                    detail=str(exc),
                )
            )
    workspace = resolved_roots.get("foundry_workspace")
    try:
        configured_workspace = config.foundry.workspace_root.resolve(strict=True)
    except OSError as exc:
        if not any(issue.logical_root == "foundry_workspace" for issue in setup_issues):
            setup_issues.append(
                CustodyPreflightSetupIssue(
                    code="root_unavailable",
                    logical_root="foundry_workspace",
                    path=str(config.foundry.workspace_root),
                    detail=str(exc),
                )
            )
    else:
        if workspace is not None and workspace != configured_workspace:
            setup_issues.append(
                CustodyPreflightSetupIssue(
                    code="workspace_authority_mismatch",
                    logical_root="foundry_workspace",
                    path=str(workspace),
                    detail="Workspace root does not match configured Foundry authority.",
                )
            )
    if len(resolved_roots) == 3:
        roots = tuple(resolved_roots.values())
        if len(set(roots)) != 3 or any(
            _is_within(left, right) for left in roots for right in roots if left != right
        ):
            setup_issues.append(
                CustodyPreflightSetupIssue(
                    code="roots_not_distinct",
                    logical_root=None,
                    path=None,
                    detail="Custody preflight roots must be distinct and non-nested.",
                )
            )

    all_issues: list[CustodyReadabilityIssue] = []
    probe_results: dict[str, ProbeResult] = {}
    for logical_root, root in resolved_roots.items():
        result = _probe_tree(root, logical_root)
        probe_results[logical_root] = result
        all_issues.extend(result.issues)

    targets, discovery_issues = _discover_governed_targets(
        workspace,
        resolved_roots.get("asset_library"),
    )
    all_issues.extend(discovery_issues)
    all_issues = _unique_sorted_issues(all_issues)
    governed_targets = [
        CustodyGovernedTarget(
            kind=kind,
            path=str(path),
            asset_id=asset_id,
            revision=revision,
            readable=not any(_is_within(Path(issue.path), path) for issue in all_issues),
            issue_count=sum(_is_within(Path(issue.path), path) for issue in all_issues),
        )
        for kind, path, asset_id, revision in targets
    ]
    root_views = [
        CustodyRootReadability(
            logical_root=logical_root,
            path=str(resolved_roots.get(logical_root, path)),
            readable=not any(issue.logical_root == logical_root for issue in all_issues)
            and not any(issue.logical_root == logical_root for issue in setup_issues),
            issue_count=sum(issue.logical_root == logical_root for issue in all_issues)
            + sum(issue.logical_root == logical_root for issue in setup_issues),
        )
        for logical_root, path in root_inputs
    ]
    ready = not all_issues and not setup_issues
    return CustodyReadabilityPreflight(
        schema_version=PREFLIGHT_SCHEMA,
        generated_at=datetime.now(UTC).isoformat(),
        status="passing" if ready else "blocked",
        ready_for_inventory=ready,
        principal=principal,
        roots=root_views,
        governed_targets=governed_targets,
        setup_issues=setup_issues,
        unreadable_targets=all_issues,
        counts=CustodyReadabilityCounts(
            roots=len(root_views),
            candidate_roots=sum(target.kind == "candidate" for target in governed_targets),
            release_roots=sum(target.kind == "release" for target in governed_targets),
            files_probed=sum(result.files for result in probe_results.values()),
            directories_probed=sum(result.directories for result in probe_results.values()),
            unreadable_targets=len(all_issues),
            setup_issues=len(setup_issues),
        ),
    )


def require_custody_readability_preflight(
    config: FoundryConfig,
    outside_root: Path,
    workspace_root: Path,
) -> None:
    result = preflight_custody_readability(config, outside_root, workspace_root)
    if result.ready_for_inventory:
        return
    if result.setup_issues:
        first_setup = result.setup_issues[0]
        raise FoundryError(
            "Custody readability preflight blocked before hashing: "
            f"setup={first_setup.code} detail={first_setup.detail}. "
            "Run `foundry custody-preflight --json` for complete evidence."
        )
    first = result.unreadable_targets[0]
    raise FoundryError(
        "Custody readability preflight blocked before hashing: "
        f"{len(result.unreadable_targets)} unreadable target(s); "
        f"first={first.path} operation={first.operation} detail={first.detail}. "
        "Run `foundry custody-preflight --json` for complete evidence."
    )


def _resolve_authoritative_root(path: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise FoundryError(f"Root is unavailable: {path}: {exc}") from exc
    if not resolved.is_dir():
        raise FoundryError(f"Root is not a directory: {resolved}")
    return resolved


def _probe_tree(root: Path, logical_root: str) -> ProbeResult:
    files = 0
    directories = 0
    issues: list[CustodyReadabilityIssue] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        directories += 1
        try:
            with os.scandir(directory) as entries:
                ordered = sorted(entries, key=lambda item: item.name)
        except OSError as exc:
            issues.append(_issue(logical_root, directory, "enumerate", exc))
            continue
        for entry in ordered:
            path = Path(entry.path)
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as exc:
                issues.append(_issue(logical_root, path, "stat", exc))
                continue
            if entry.is_symlink() or bool(
                getattr(metadata, "st_file_attributes", 0) & REPARSE_POINT
            ):
                issues.append(
                    CustodyReadabilityIssue(
                        logical_root=logical_root,
                        path=str(path),
                        operation="reparse",
                        error_type="UnsupportedReparsePoint",
                        detail="symlink or reparse point is outside the custody scan boundary.",
                    )
                )
                continue
            if stat.S_ISDIR(metadata.st_mode):
                pending.append(path)
                continue
            if not stat.S_ISREG(metadata.st_mode):
                issues.append(
                    CustodyReadabilityIssue(
                        logical_root=logical_root,
                        path=str(path),
                        operation="stat",
                        error_type="UnsupportedEntryType",
                        detail="Custody roots may contain only regular files and directories.",
                    )
                )
                continue
            files += 1
            try:
                descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
            except OSError as exc:
                issues.append(_issue(logical_root, path, "open", exc))
                continue
            os.close(descriptor)
    return ProbeResult(files=files, directories=directories, issues=tuple(issues))


def _discover_governed_targets(
    workspace: Path | None,
    library: Path | None,
) -> tuple[list[tuple[str, Path, str, str | None]], list[CustodyReadabilityIssue]]:
    targets: list[tuple[str, Path, str, str | None]] = []
    issues: list[CustodyReadabilityIssue] = []
    workspace_assets = workspace / "assets" if workspace is not None else None
    if workspace_assets is not None and workspace_assets.is_dir():
        try:
            candidates = sorted(
                (entry for entry in os.scandir(workspace_assets) if _is_plain_directory(entry)),
                key=lambda entry: entry.name,
            )
        except OSError as exc:
            issues.append(_issue("foundry_workspace", workspace_assets, "enumerate", exc))
        else:
            targets.extend(
                ("candidate", Path(entry.path), entry.name, None) for entry in candidates
            )

    library_assets = library / "assets" if library is not None else None
    if library_assets is not None and library_assets.is_dir():
        try:
            asset_entries = sorted(
                (entry for entry in os.scandir(library_assets) if _is_plain_directory(entry)),
                key=lambda entry: entry.name,
            )
        except OSError as exc:
            issues.append(_issue("asset_library", library_assets, "enumerate", exc))
        else:
            for asset_entry in asset_entries:
                asset_path = Path(asset_entry.path)
                try:
                    release_entries = sorted(
                        (entry for entry in os.scandir(asset_path) if _is_plain_directory(entry)),
                        key=lambda entry: entry.name,
                    )
                except OSError as exc:
                    issues.append(_issue("asset_library", asset_path, "enumerate", exc))
                    continue
                targets.extend(
                    (
                        "release",
                        Path(release_entry.path),
                        asset_entry.name,
                        release_entry.name,
                    )
                    for release_entry in release_entries
                )
    targets.sort(key=lambda item: (item[0], item[2], item[3] or ""))
    return targets, issues


def _current_principal() -> CustodyPrincipal:
    account = getpass.getuser() or "unknown"
    identifier = f"uid:{os.geteuid()}" if hasattr(os, "geteuid") else account
    resolution_status = "exact"
    if os.name == "nt":
        resolution_status = "unresolved"
        try:
            completed = subprocess.run(
                ["whoami", "/user", "/fo", "csv", "/nh"],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            parsed = _parse_windows_principal(completed.stdout)
            if parsed is not None:
                account, identifier = parsed
                resolution_status = "exact"
        except (OSError, subprocess.SubprocessError, StopIteration, csv.Error):
            pass
    return CustodyPrincipal(
        account=account,
        identifier=identifier,
        platform=platform.system() or os.name,
        resolution_status=resolution_status,
    )


def _parse_windows_principal(output: str) -> tuple[str, str] | None:
    try:
        row = next(csv.reader([output.strip()]))
    except (StopIteration, csv.Error):
        return None
    if len(row) < 2:
        return None
    account = row[0].strip()
    identifier = row[1].strip()
    if not account or re.fullmatch(r"S-\d+(?:-\d+)+", identifier, re.IGNORECASE) is None:
        return None
    return account, identifier


def _is_plain_directory(entry: os.DirEntry[str]) -> bool:
    try:
        metadata = entry.stat(follow_symlinks=False)
    except OSError:
        return False
    if entry.is_symlink() or bool(getattr(metadata, "st_file_attributes", 0) & REPARSE_POINT):
        return False
    return stat.S_ISDIR(metadata.st_mode)


def _issue(
    logical_root: str,
    path: Path,
    operation: str,
    error: OSError,
) -> CustodyReadabilityIssue:
    return CustodyReadabilityIssue(
        logical_root=logical_root,
        path=str(path),
        operation=operation,
        error_type=type(error).__name__,
        detail=str(error),
    )


def _unique_sorted_issues(
    issues: list[CustodyReadabilityIssue],
) -> list[CustodyReadabilityIssue]:
    unique = {
        (item.logical_root, item.path, item.operation, item.error_type, item.detail): item
        for item in issues
    }
    return [unique[key] for key in sorted(unique)]


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
