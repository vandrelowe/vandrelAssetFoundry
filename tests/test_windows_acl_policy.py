import subprocess
from pathlib import Path

import pytest

import vandrel_foundry.services.create_asset as creation
from vandrel_foundry.config import FoundryConfig, WindowsAclSettings
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.services.windows_acl_policy import (
    apply_candidate_acl,
    apply_release_acl,
)


def _enabled(config: FoundryConfig) -> FoundryConfig:
    return config.model_copy(
        update={
            "windows_acl": WindowsAclSettings(
                enabled=True,
                owner_sid="S-1-5-21-1-2-3-1003",
                offline_sandbox_sid="S-1-5-21-1-2-3-1005",
            )
        }
    )


def test_candidate_acl_uses_exact_modify_principal(config: FoundryConfig) -> None:
    candidate = config.foundry.workspace_root / "assets" / "fixture_001"
    candidate.mkdir(parents=True)
    commands: list[list[str]] = []

    def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "ok", "")

    apply_candidate_acl(_enabled(config), candidate, runner=runner, platform_name="nt")

    assert commands == [
        [
            "icacls.exe",
            str(candidate.resolve()),
            "/grant:r",
            "*S-1-5-21-1-2-3-1003:(OI)(CI)(F)",
            "*S-1-5-21-1-2-3-1005:(OI)(CI)(M)",
            "*S-1-5-18:(OI)(CI)(F)",
            "*S-1-5-32-544:(OI)(CI)(F)",
        ],
        ["icacls.exe", str(candidate.resolve()), "/inheritance:r"],
        ["icacls.exe", str(candidate.resolve()), "/remove:g", "*S-1-3-4"],
    ]


def test_release_acl_is_read_only_for_sandbox(config: FoundryConfig) -> None:
    release = config.foundry.asset_library_root / "assets" / "fixture_001" / "r001"
    release.mkdir(parents=True)
    commands: list[list[str]] = []

    def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "ok", "")

    apply_release_acl(_enabled(config), release, runner=runner, platform_name="nt")

    assert "*S-1-5-21-1-2-3-1005:(OI)(CI)(RX)" in commands[0]
    assert commands[1][-1] == "/inheritance:r"
    assert commands[2][-1] == "*S-1-3-4"


def test_disabled_policy_does_not_invoke_icacls(config: FoundryConfig, tmp_path: Path) -> None:
    called = False

    def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        nonlocal called
        called = True
        return subprocess.CompletedProcess(command, 0, "", "")

    apply_candidate_acl(config, tmp_path, runner=runner, platform_name="nt")

    assert not called


def test_acl_target_must_remain_inside_authority(config: FoundryConfig, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(FoundryError, match="outside its configured authority"):
        apply_candidate_acl(_enabled(config), outside, platform_name="nt")


def test_acl_failure_is_fail_closed(config: FoundryConfig) -> None:
    candidate = config.foundry.workspace_root / "assets" / "fixture_001"
    candidate.mkdir(parents=True)

    def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 5, "", "Access is denied")

    with pytest.raises(FoundryError, match="Access is denied"):
        apply_candidate_acl(_enabled(config), candidate, runner=runner, platform_name="nt")


def test_acl_cleanup_failure_is_fail_closed(config: FoundryConfig) -> None:
    candidate = config.foundry.workspace_root / "assets" / "fixture_001"
    candidate.mkdir(parents=True)
    calls = 0

    def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls == 2:
            return subprocess.CompletedProcess(command, 5, "", "Inheritance cleanup failed")
        return subprocess.CompletedProcess(command, 0, "ok", "")

    with pytest.raises(FoundryError, match="Inheritance cleanup failed"):
        apply_candidate_acl(_enabled(config), candidate, runner=runner, platform_name="nt")

    assert calls == 2


def test_create_asset_applies_candidate_policy(
    config: FoundryConfig,
    lanes,
    prompt: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destinations: list[Path] = []
    monkeypatch.setattr(
        creation,
        "apply_candidate_acl",
        lambda _config, destination: destinations.append(destination),
    )

    creation.create_asset(
        config,
        lanes,
        "acl_hook_fixture_001",
        "static_prop",
        "ACL Hook Fixture",
        prompt,
    )

    assert destinations == [config.foundry.workspace_root / "assets" / "acl_hook_fixture_001"]
