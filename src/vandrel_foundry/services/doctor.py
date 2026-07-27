import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.lanes import LaneConfiguration


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def run_doctor(config: FoundryConfig, lanes: LaneConfiguration) -> list[Check]:
    checks = [
        Check("Configuration", True, "loaded and validated"),
        Check("Lane configuration", bool(lanes.lanes), f"{len(lanes.lanes)} lanes loaded"),
        Check("Vandrel writes", not config.vandrel.write_enabled, "disabled"),
        Check(
            "Meshy key setting",
            bool(config.providers.meshy.api_key_environment_variable),
            f"environment variable name: {config.providers.meshy.api_key_environment_variable}",
        ),
    ]
    workspace = config.foundry.workspace_root
    if workspace.exists() and not workspace.is_dir():
        checks.append(Check("Workspace", False, f"not a directory: {workspace}"))
    elif workspace.is_dir():
        try:
            descriptor, probe = tempfile.mkstemp(prefix=".doctor-", dir=workspace)
            os.close(descriptor)
            Path(probe).unlink()
            checks.append(Check("Workspace", True, f"writable: {workspace}"))
        except OSError as exc:
            checks.append(Check("Workspace", False, f"not writable: {workspace} ({exc})"))
    else:
        parent = _nearest_existing_parent(workspace)
        writable = os.access(parent, os.W_OK)
        detail = f"not initialized; parent {'writable' if writable else 'not writable'}: {parent}"
        checks.append(Check("Workspace", writable, detail))

    marker = config.vandrel.reference_repo_root / config.vandrel.required_marker
    checks.append(
        Check(
            "Vandrel marker",
            marker.is_file(),
            f"{marker} {'found' if marker.is_file() else 'not found'}",
        )
    )
    for name, executable in (
        ("Godot executable", config.tools.godot_executable),
        ("Blender executable", config.tools.blender_executable),
    ):
        if executable is not None:
            checks.append(
                Check(
                    name,
                    executable.is_absolute() and executable.is_file(),
                    str(executable),
                )
            )
    return checks


def _nearest_existing_parent(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate
