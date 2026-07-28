import os
import subprocess
from collections.abc import Callable
from pathlib import Path

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError

AclRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def apply_candidate_acl(
    config: FoundryConfig,
    destination: Path,
    *,
    runner: AclRunner | None = None,
    platform_name: str | None = None,
) -> None:
    _apply_acl(
        config,
        destination,
        authority_root=config.foundry.workspace_root / "assets",
        sandbox_rights="M",
        runner=runner,
        platform_name=platform_name,
    )


def apply_release_acl(
    config: FoundryConfig,
    destination: Path,
    *,
    runner: AclRunner | None = None,
    platform_name: str | None = None,
) -> None:
    _apply_acl(
        config,
        destination,
        authority_root=config.foundry.asset_library_root / "assets",
        sandbox_rights="RX",
        runner=runner,
        platform_name=platform_name,
    )


def _apply_acl(
    config: FoundryConfig,
    destination: Path,
    *,
    authority_root: Path,
    sandbox_rights: str,
    runner: AclRunner | None,
    platform_name: str | None,
) -> None:
    policy = config.windows_acl
    if not policy.enabled:
        return
    if (platform_name or os.name) != "nt":
        raise FoundryError("Configured Windows ACL policy requires Windows.")
    try:
        resolved_destination = destination.resolve(strict=True)
        resolved_root = authority_root.resolve(strict=True)
        resolved_destination.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise FoundryError(
            f"ACL target is outside its configured authority: {destination}"
        ) from exc
    assert policy.owner_sid is not None
    assert policy.offline_sandbox_sid is not None
    commands = [
        [
            "icacls.exe",
            str(resolved_destination),
            "/grant:r",
            f"*{policy.owner_sid}:(OI)(CI)(F)",
            f"*{policy.offline_sandbox_sid}:(OI)(CI)({sandbox_rights})",
            "*S-1-5-18:(OI)(CI)(F)",
            "*S-1-5-32-544:(OI)(CI)(F)",
        ],
        [
            "icacls.exe",
            str(resolved_destination),
            "/inheritance:r",
        ],
        [
            "icacls.exe",
            str(resolved_destination),
            "/remove:g",
            "*S-1-3-4",
        ],
    ]
    run = runner or _run_acl_command
    for command in commands:
        result = run(command)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "unknown icacls failure").strip()
            raise FoundryError(f"Could not apply Windows ACL policy: {detail}")


def _run_acl_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        shell=False,
    )
