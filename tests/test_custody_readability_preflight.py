import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.conftest import write_config
from vandrel_foundry.cli import app
from vandrel_foundry.domain.custody_preflight import CustodyPrincipal
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.services.build_custody_inventory import build_custody_inventory
from vandrel_foundry.services.preflight_custody_readability import (
    _is_plain_directory,
    _parse_windows_principal,
    preflight_custody_readability,
)

runner = CliRunner()


def _roots(config, tmp_path: Path) -> tuple[Path, Path, Path]:
    outside = tmp_path / "outside"
    workspace = config.foundry.workspace_root
    library = config.foundry.asset_library_root
    (outside / "Package").mkdir(parents=True)
    (workspace / "assets" / "candidate_one").mkdir(parents=True)
    (library / "assets" / "candidate_one" / "r001").mkdir(parents=True)
    (outside / "Package" / "source.bin").write_bytes(b"source")
    (workspace / "assets" / "candidate_one" / "manifest.json").write_bytes(b"{}")
    (library / "assets" / "candidate_one" / "r001" / "asset-release.json").write_bytes(b"{}")
    return outside, workspace, library


def _principal() -> CustodyPrincipal:
    return CustodyPrincipal(
        account="fixture\\reader",
        identifier="fixture-reader-001",
        platform="fixture",
        resolution_status="exact",
    )


def test_preflight_enumerates_exact_targets_and_preserves_bytes(config, tmp_path: Path) -> None:
    outside, workspace, library = _roots(config, tmp_path)
    files = sorted(
        path for root in (outside, workspace, library) for path in root.rglob("*") if path.is_file()
    )
    before = {path: path.read_bytes() for path in files}

    result = preflight_custody_readability(
        config,
        outside,
        workspace,
        principal_resolver=_principal,
    )

    assert result.ready_for_inventory
    assert result.status == "passing"
    assert result.principal.identifier == "fixture-reader-001"
    assert [
        (target.kind, target.asset_id, target.revision) for target in result.governed_targets
    ] == [
        ("candidate", "candidate_one", None),
        ("release", "candidate_one", "r001"),
    ]
    assert result.counts.files_probed == 3
    assert result.counts.unreadable_targets == 0
    assert {path: path.read_bytes() for path in files} == before


def test_preflight_reports_exact_unreadable_file_and_blocks(
    config,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside, workspace, _library = _roots(config, tmp_path)
    blocked = workspace / "assets" / "candidate_one" / "manifest.json"
    actual_open = os.open

    def controlled_open(path, flags, *args, **kwargs):
        if Path(path) == blocked:
            raise PermissionError(13, "fixture access denied", str(path))
        return actual_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(
        "vandrel_foundry.services.preflight_custody_readability.os.open",
        controlled_open,
    )

    result = preflight_custody_readability(
        config,
        outside,
        workspace,
        principal_resolver=_principal,
    )

    assert not result.ready_for_inventory
    assert result.status == "blocked"
    assert result.unreadable_targets[0].path == str(blocked)
    assert result.unreadable_targets[0].operation == "open"
    candidate = next(target for target in result.governed_targets if target.kind == "candidate")
    assert not candidate.readable
    assert candidate.issue_count == 1


def test_inventory_guard_stops_before_scan(
    config,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside, workspace, _library = _roots(config, tmp_path)
    policy = tmp_path / "policy.json"
    policy.write_text("{}", encoding="utf-8")

    def blocked(*_args, **_kwargs):
        raise FoundryError("preflight fixture blocked")

    def unexpected_scan(*_args, **_kwargs):
        raise AssertionError("inventory scan must not start")

    monkeypatch.setattr(
        "vandrel_foundry.services.build_custody_inventory.require_custody_readability_preflight",
        blocked,
    )
    monkeypatch.setattr(
        "vandrel_foundry.services.build_custody_inventory._scan_all",
        unexpected_scan,
    )

    with pytest.raises(FoundryError, match="preflight fixture blocked"):
        build_custody_inventory(config, outside, workspace, policy)


def test_cli_json_emits_blocked_evidence_and_nonzero_exit(
    config_data: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "foundry.toml"
    write_config(config_path, config_data)
    outside = tmp_path / "outside"
    workspace = Path(config_data["foundry"]["workspace_root"])
    library = Path(config_data["foundry"]["asset_library_root"])
    (outside / "Package").mkdir(parents=True)
    (workspace / "assets" / "blocked_candidate").mkdir(parents=True)
    library.mkdir(parents=True)
    blocked = workspace / "assets" / "blocked_candidate" / "manifest.json"
    blocked.write_bytes(b"{}")
    actual_open = os.open

    def controlled_open(path, flags, *args, **kwargs):
        if Path(path) == blocked:
            raise PermissionError(13, "fixture access denied", str(path))
        return actual_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(
        "vandrel_foundry.services.preflight_custody_readability.os.open",
        controlled_open,
    )

    result = runner.invoke(
        app,
        [
            "custody-preflight",
            "--outside-root",
            str(outside),
            "--workspace-root",
            str(workspace),
            "--json",
            "--config",
            str(config_path),
        ],
    )

    assert result.exit_code == 1
    evidence = json.loads(result.output)
    assert evidence["schema_version"] == "vandrel_foundry_custody_readability_preflight/1.0"
    assert evidence["status"] == "blocked"
    assert evidence["ready_for_inventory"] is False
    assert evidence["unreadable_targets"][0]["path"] == str(blocked)


def test_reparse_entry_is_not_discovered_as_governed_directory(tmp_path: Path) -> None:
    class ReparseEntry:
        @staticmethod
        def stat(*, follow_symlinks: bool):
            assert not follow_symlinks
            return type(
                "Metadata",
                (),
                {"st_file_attributes": 0x400, "st_mode": stat.S_IFDIR},
            )()

        @staticmethod
        def is_symlink():
            return False

    import stat

    assert not _is_plain_directory(ReparseEntry())


def test_unresolved_principal_blocks_with_explicit_setup_evidence(
    config,
    tmp_path: Path,
) -> None:
    outside, workspace, _library = _roots(config, tmp_path)

    result = preflight_custody_readability(
        config,
        outside,
        workspace,
        principal_resolver=lambda: CustodyPrincipal(
            account="fixture\\unknown",
            identifier="fixture\\unknown",
            platform="Windows",
            resolution_status="unresolved",
        ),
    )

    assert not result.ready_for_inventory
    assert result.principal.resolution_status == "unresolved"
    assert result.setup_issues[0].code == "principal_unresolved"


@pytest.mark.parametrize(
    "output",
    [
        "",
        '"fixture\\\\reader"',
        '"","S-1-5-21-1"',
        '"fixture\\\\reader",""',
        '"fixture\\\\reader","not-a-sid"',
    ],
)
def test_successful_but_malformed_windows_identity_is_unresolved(output: str) -> None:
    assert _parse_windows_principal(output) is None


def test_valid_windows_identity_is_exactly_parsed() -> None:
    assert _parse_windows_principal(
        '"nerdutron\\\\codexsandboxoffline","S-1-5-21-3868179449-1005"'
    ) == (
        "nerdutron\\\\codexsandboxoffline",
        "S-1-5-21-3868179449-1005",
    )


def test_cli_json_emits_versioned_evidence_for_unavailable_root(
    config_data: dict,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "foundry.toml"
    write_config(config_path, config_data)
    workspace = Path(config_data["foundry"]["workspace_root"])
    library = Path(config_data["foundry"]["asset_library_root"])
    workspace.mkdir(parents=True)
    library.mkdir(parents=True)
    missing_outside = tmp_path / "missing-outside"

    result = runner.invoke(
        app,
        [
            "custody-preflight",
            "--outside-root",
            str(missing_outside),
            "--workspace-root",
            str(workspace),
            "--json",
            "--config",
            str(config_path),
        ],
    )

    assert result.exit_code == 1
    evidence = json.loads(result.output)
    assert evidence["schema_version"] == "vandrel_foundry_custody_readability_preflight/1.0"
    assert evidence["status"] == "blocked"
    assert evidence["setup_issues"][0]["code"] == "root_unavailable"
