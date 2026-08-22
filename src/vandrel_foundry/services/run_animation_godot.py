"""Bounded Windows adapter for the monitored animation-library Godot corridor."""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.services.animation_library import AnimationPipelineExecution
from vandrel_foundry.services.validate_godot import (
    SAFE_ENVIRONMENT_KEYS,
    ProcessResult,
    run_bounded_process,
)


class ProcessRunner(Protocol):
    def __call__(
        self,
        arguments: Sequence[str],
        cwd: Path,
        environment: Mapping[str, str],
        timeout_seconds: float,
        maximum_output_bytes: int,
    ) -> ProcessResult: ...


def run_monitored_animation_pipeline(
    config: FoundryConfig,
    sandbox: Path,
    runner: ProcessRunner | None = None,
    environment: Mapping[str, str] | None = None,
    supervisor_executable: Path | None = None,
) -> AnimationPipelineExecution:
    """Execute five fixed phases under one outer kill-on-close process job."""
    executable = config.tools.godot_executable
    if executable is None or not executable.is_absolute() or not executable.is_file():
        raise FoundryError("Configure tools.godot_executable as an existing absolute file.")
    if not executable.stem.casefold().endswith("console"):
        raise FoundryError("Animation-library processing requires the Godot console executable.")
    safe_environment = {
        key: value
        for key, value in (environment or os.environ).items()
        if key.upper() in SAFE_ENVIRONMENT_KEYS
    }
    powershell = supervisor_executable or (
        Path(found) if (found := shutil.which("pwsh", path=safe_environment.get("PATH"))) else None
    )
    if powershell is None or not powershell.is_absolute() or not powershell.is_file():
        raise FoundryError("PowerShell 7 is required for monitored animation processing.")
    supervisor = (
        Path(__file__).resolve().parent.parent
        / "godot"
        / "Invoke-FoundryAnimationLibraryMonitored.ps1"
    )
    if not supervisor.is_file():
        raise FoundryError("The monitored animation-library Godot supervisor is missing.")
    arguments = [
        str(powershell.resolve()),
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-File",
        str(supervisor),
        "-GodotExe",
        str(executable),
        "-SandboxPath",
        str(sandbox),
        "-TimeoutSeconds",
        str(int(config.tools.godot_timeout_seconds)),
        "-MaximumOutputBytes",
        str(config.tools.maximum_output_bytes),
    ]
    result = (runner or run_bounded_process)(
        arguments,
        sandbox,
        safe_environment,
        config.tools.godot_timeout_seconds * 5 + 60,
        config.tools.maximum_output_bytes + 65_536,
    )
    if result.timed_out:
        raise FoundryError("Monitored animation-library processing timed out.")
    if result.output_limited:
        raise FoundryError("Monitored animation-library processing exceeded its output limit.")
    if result.return_code != 0:
        raise FoundryError(
            "Monitored animation-library processing failed: "
            + (result.stderr.strip() or result.stdout.strip() or f"exit {result.return_code}")
        )
    return AnimationPipelineExecution(
        animation_library=sandbox / "output" / "animation_library.res",
        technical_report=sandbox / "output" / "animation-library-technical.json",
        isolation_report=sandbox / "output" / "animation-library-isolation.json",
        monitor_report=sandbox / "output" / "animation-library-godot-monitor.json",
    )
