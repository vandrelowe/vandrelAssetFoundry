"""Outer bounded adapter for the dedicated clean-body monitored Godot corridor."""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.services.run_animation_visual_capture import (
    SAFE_ENVIRONMENT_KEYS,
    CaptureProcessResult,
    run_bounded_capture_process,
)
from vandrel_foundry.services.validate_clean_meshy_body import CleanBodyValidationExecution


class ProcessRunner(Protocol):
    def __call__(self, arguments: Sequence[str], cwd: Path, environment: Mapping[str, str], timeout_seconds: float, maximum_output_bytes: int) -> CaptureProcessResult: ...


def run_monitored_clean_body(config: FoundryConfig, sandbox: Path, runner: ProcessRunner | None = None, environment: Mapping[str, str] | None = None, supervisor_executable: Path | None = None) -> CleanBodyValidationExecution:
    godot = config.tools.godot_executable
    if godot is None or not godot.is_absolute() or not godot.is_file() or not godot.stem.casefold().endswith("console"):
        raise FoundryError("Clean-body validation requires the Godot console executable.")
    safe = {key: value for key, value in (environment or os.environ).items() if key.upper() in SAFE_ENVIRONMENT_KEYS}
    powershell = supervisor_executable or (Path(value) if (value := shutil.which("pwsh", path=safe.get("PATH"))) else None)
    if powershell is None or not powershell.is_absolute() or not powershell.is_file():
        raise FoundryError("PowerShell 7 is required for monitored clean-body validation.")
    wrapper = Path(__file__).parents[1] / "godot/Invoke-FoundryCleanMeshyBodyMonitored.ps1"
    authority_root = config.vandrel.reference_repo_root / "tools" / "ai"
    runtime_guard = authority_root / "VandrelGodotRuntimeGuard.ps1"
    crash_evidence = authority_root / "VandrelGodotCrashEvidence.ps1"
    if not runtime_guard.is_file() or not crash_evidence.is_file():
        raise FoundryError("Canonical Vandrel monitored Godot authority is unavailable.")
    arguments = [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(wrapper), "-GodotExe", str(godot), "-SandboxPath", str(sandbox), "-TimeoutSeconds", str(int(config.tools.godot_timeout_seconds)), "-MaximumOutputBytes", str(config.tools.maximum_output_bytes), "-RuntimeGuardPath", str(runtime_guard), "-CrashEvidenceScriptPath", str(crash_evidence)]
    result = (runner or run_bounded_capture_process)(arguments, sandbox, safe, config.tools.godot_timeout_seconds * 5 + 60, config.tools.maximum_output_bytes + 65_536)
    for transient in (sandbox / ".foundry-capture-outer-stdout.tmp", sandbox / ".foundry-capture-outer-stderr.tmp"):
        transient.unlink(missing_ok=True)
    if result.return_code != 0 or result.timed_out or result.output_limited:
        raise FoundryError("Monitored clean-body Godot validation failed.")
    return CleanBodyValidationExecution(sandbox / "output/clean-body-technical.json", sandbox / "output/clean-body-godot-monitor.json", sandbox / "output/clean-body-capture-manifest.json")
