"""Bounded adapter for the monitored animation visual-capture corridor."""

from __future__ import annotations

import hashlib
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.services.capture_animation_visual_matrix import (
    CAMERA_CONFIG_SHA256,
    AnimationVisualCaptureExecution,
)
from vandrel_foundry.storage.atomic import json_bytes

SAFE_ENVIRONMENT_KEYS = {
    "APPDATA",
    "HOME",
    "LOCALAPPDATA",
    "PATH",
    "PROGRAMDATA",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "WINDIR",
}
OUTER_WATCHDOG_SCHEMA = "vandrel_foundry_animation_visual_outer_watchdog/1.0"
OUTER_WATCHDOG_POLICY = "vandrel_capture_local_outer_watchdog_v1"
OUTER_WATCHDOG_PATH = "animation-visual-outer-watchdog.json"
SUPERVISOR_MONITOR_PATH = "animation-visual-godot-monitor.json"


class CaptureOuterFailure(FoundryError):
    """A capture-local outer execution failure with a stable reason code."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class CaptureProcessResult:
    return_code: int
    stdout: str
    stderr: str
    timed_out: bool
    output_limited: bool
    duration_seconds: float


class ProcessRunner(Protocol):
    def __call__(
        self,
        arguments: Sequence[str],
        cwd: Path,
        environment: Mapping[str, str],
        timeout_seconds: float,
        maximum_output_bytes: int,
    ) -> CaptureProcessResult: ...


def run_monitored_animation_visual_capture(
    config: FoundryConfig,
    sandbox: Path,
    runtime_request_sha256: str,
    capture_script_sha256: str,
    runner: ProcessRunner | None = None,
    environment: Mapping[str, str] | None = None,
    supervisor_executable: Path | None = None,
) -> AnimationVisualCaptureExecution:
    """Execute import and capture under the reviewed outer Job Object corridor."""
    executable = config.tools.godot_executable
    if executable is None or not executable.is_absolute():
        raise FoundryError("Configure tools.godot_executable as an absolute path.")
    safe_environment = {
        key: value
        for key, value in (environment or os.environ).items()
        if key.upper() in SAFE_ENVIRONMENT_KEYS
    }
    powershell = supervisor_executable or (
        Path(found) if (found := shutil.which("pwsh", path=safe_environment.get("PATH"))) else None
    )
    if powershell is None or not powershell.is_absolute() or not powershell.is_file():
        raise FoundryError("PowerShell 7 is required for monitored animation visual capture.")
    supervisor = (
        Path(__file__).resolve().parent.parent
        / "godot"
        / "Invoke-FoundryAnimationVisualCaptureMonitored.ps1"
    )
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
        "-RuntimeRequestSha256",
        runtime_request_sha256,
        "-CaptureScriptSha256",
        capture_script_sha256,
        "-CameraConfigSha256",
        CAMERA_CONFIG_SHA256,
    ]
    try:
        result = (runner or run_bounded_capture_process)(
            arguments,
            sandbox,
            safe_environment,
            config.tools.godot_timeout_seconds * 2 + 60,
            config.tools.maximum_output_bytes + 65_536,
        )
    except FoundryError as exc:
        reason = (
            exc.reason
            if isinstance(exc, CaptureOuterFailure)
            else "outer_process_failure"
        )
        evidence = _ensure_outer_watchdog_failure(
            sandbox,
            reason=reason,
            detail=str(exc),
            maximum_output_bytes=config.tools.maximum_output_bytes,
        )
        suffix = _outer_watchdog_suffix(evidence)
        raise FoundryError(f"{exc}{suffix}") from exc
    if result.timed_out:
        evidence = _ensure_outer_watchdog_failure(
            sandbox,
            reason="outer_timeout",
            detail="Monitored animation visual capture exceeded its outer timeout.",
            maximum_output_bytes=config.tools.maximum_output_bytes,
            result=result,
        )
        raise FoundryError(
            "Monitored animation visual capture timed out."
            + _outer_watchdog_suffix(evidence)
        )
    if result.output_limited:
        evidence = _ensure_outer_watchdog_failure(
            sandbox,
            reason="outer_output_limit",
            detail="Monitored animation visual capture exceeded its outer output limit.",
            maximum_output_bytes=config.tools.maximum_output_bytes,
            result=result,
        )
        raise FoundryError(
            "Monitored animation visual capture exceeded its output limit."
            + _outer_watchdog_suffix(evidence)
        )
    if result.return_code != 0:
        evidence = _ensure_outer_watchdog_failure(
            sandbox,
            reason="outer_nonzero_without_supervisor_monitor",
            detail=f"Capture supervisor exited with code {result.return_code}.",
            maximum_output_bytes=config.tools.maximum_output_bytes,
            result=result,
        )
        raise FoundryError(
            "Monitored animation visual capture failed: "
            + (result.stderr.strip() or result.stdout.strip() or f"exit {result.return_code}")
            + _outer_watchdog_suffix(evidence)
        )
    cleanup_issue = _cleanup_outer_temp_logs(sandbox)
    if cleanup_issue is not None:
        exc = CaptureOuterFailure(
            "outer_cleanup_failed",
            f"Capture outer-process cleanup failed: {cleanup_issue}",
        )
        evidence = _ensure_outer_watchdog_failure(
            sandbox,
            reason=exc.reason,
            detail=str(exc),
            maximum_output_bytes=config.tools.maximum_output_bytes,
            result=result,
        )
        suffix = _outer_watchdog_suffix(evidence)
        raise FoundryError(f"{exc}{suffix}") from exc
    return AnimationVisualCaptureExecution(
        capture_report=sandbox / "output" / "capture-report.json",
        monitor_report=sandbox / "output" / "animation-visual-godot-monitor.json",
        evidence_directory=sandbox / "output" / "cells",
    )


def run_bounded_capture_process(
    arguments: Sequence[str],
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: float,
    maximum_output_bytes: int,
) -> CaptureProcessResult:
    """Run the capture supervisor under one owned finite process tree."""
    stdout_path = cwd / ".foundry-capture-outer-stdout.tmp"
    stderr_path = cwd / ".foundry-capture-outer-stderr.tmp"
    started = time.monotonic()
    timed_out = False
    output_limited = False
    windows_job = None
    try:
        with stdout_path.open("xb") as stdout_stream, stderr_path.open("xb") as stderr_stream:
            process = subprocess.Popen(
                list(arguments),
                cwd=cwd,
                env=dict(environment),
                stdin=subprocess.DEVNULL,
                stdout=stdout_stream,
                stderr=stderr_stream,
                shell=False,
                start_new_session=os.name != "nt",
                creationflags=0x00000004 if os.name == "nt" else 0,
            )
            if os.name == "nt":
                try:
                    windows_job = _create_windows_kill_job(process.pid)
                    _resume_windows_process(process.pid)
                except Exception as exc:
                    if windows_job is not None:
                        _terminate_windows_job(windows_job, process)
                        windows_job = None
                    elif process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)
                    raise CaptureOuterFailure(
                        "job_setup_failed",
                        f"Could not establish the capture outer Job Object: {exc}",
                    ) from exc
            while process.poll() is None:
                if time.monotonic() - started > timeout_seconds:
                    timed_out = True
                    try:
                        _terminate_capture_tree(process, windows_job)
                    except FoundryError as exc:
                        raise CaptureOuterFailure(
                            "outer_timeout_termination_failed", str(exc)
                        ) from exc
                    windows_job = None
                    break
                if stdout_stream.tell() + stderr_stream.tell() > maximum_output_bytes:
                    output_limited = True
                    try:
                        _terminate_capture_tree(process, windows_job)
                    except FoundryError as exc:
                        raise CaptureOuterFailure(
                            "outer_output_termination_failed", str(exc)
                        ) from exc
                    windows_job = None
                    break
                time.sleep(0.05)
            return_code = process.wait(timeout=5)
            if os.name == "nt" and windows_job is not None:
                _close_windows_job(windows_job)
                windows_job = None
                remaining = _windows_godot_process_inventory()
                if remaining:
                    raise CaptureOuterFailure(
                        "final_inventory_failed",
                        "Capture outer Job completed with Godot processes: "
                        + ", ".join(remaining),
                    )
            output_limited = output_limited or (
                stdout_stream.tell() + stderr_stream.tell() > maximum_output_bytes
            )
        stdout = _read_bounded_text(stdout_path, maximum_output_bytes)
        remaining_bytes = max(0, maximum_output_bytes - len(stdout.encode("utf-8")))
        stderr = _read_bounded_text(stderr_path, remaining_bytes)
        return CaptureProcessResult(
            return_code=return_code,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            output_limited=output_limited,
            duration_seconds=time.monotonic() - started,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CaptureOuterFailure(
            "outer_process_failure",
            f"Could not execute bounded animation visual capture: {exc}",
        ) from exc
    finally:
        cleanup_error: Exception | None = None
        if os.name == "nt" and windows_job is not None:
            try:
                _close_windows_job(windows_job)
            except FoundryError as exc:  # cleanup must not hide the active primary failure
                cleanup_error = exc
        if cleanup_error is not None and sys.exc_info()[0] is None:
            raise CaptureOuterFailure(
                "outer_cleanup_failed",
                f"Capture outer-process cleanup failed: {cleanup_error}"
            ) from cleanup_error


def _ensure_outer_watchdog_failure(
    sandbox: Path,
    *,
    reason: str,
    detail: str,
    maximum_output_bytes: int,
    result: CaptureProcessResult | None = None,
) -> tuple[Path, str | None] | None:
    """Write a bounded outer failure record only when no supervisor monitor exists."""
    output = sandbox / "output"
    supervisor_monitor = output / SUPERVISOR_MONITOR_PATH
    if supervisor_monitor.is_file():
        return None
    record_path = output / OUTER_WATCHDOG_PATH
    if record_path.is_file():
        return record_path.relative_to(sandbox), None
    if not output.is_dir():
        raise FoundryError("Capture outer-watchdog output directory is unavailable.")
    stdout_limit = maximum_output_bytes // 2
    stderr_limit = maximum_output_bytes - stdout_limit
    stdout = _bounded_outer_bytes(
        sandbox / ".foundry-capture-outer-stdout.tmp",
        result.stdout if result is not None else "",
        stdout_limit,
    )
    stderr = _bounded_outer_bytes(
        sandbox / ".foundry-capture-outer-stderr.tmp",
        result.stderr if result is not None else "",
        stderr_limit,
    )
    stdout_binding = _write_outer_stream(output, "outer-watchdog.stdout.log", stdout)
    stderr_binding = _write_outer_stream(output, "outer-watchdog.stderr.log", stderr)
    detail_bytes = detail.encode("utf-8", errors="replace")
    detail_excerpt = detail_bytes[:4096].decode("utf-8", errors="replace")
    record = {
        "schema_version": OUTER_WATCHDOG_SCHEMA,
        "policy": OUTER_WATCHDOG_POLICY,
        "recorded_utc": datetime.now(UTC).isoformat(),
        "reason": reason,
        "detail_excerpt": detail_excerpt,
        "detail_truncated": len(detail_bytes) > 4096,
        "supervisor_monitor_present": False,
        "maximum_output_bytes": maximum_output_bytes,
        "process_result": {
            "return_code": result.return_code if result is not None else None,
            "timed_out": result.timed_out if result is not None else False,
            "output_limited": result.output_limited if result is not None else False,
            "duration_seconds": result.duration_seconds if result is not None else None,
        },
        "stdout_evidence": stdout_binding,
        "stderr_evidence": stderr_binding,
        "raw_temp_cleanup": {
            "attempted": False,
            "failed": False,
            "issue_excerpt": None,
            "issue_truncated": False,
        },
    }
    _write_exclusive(record_path, json_bytes(record))
    cleanup_issue = _cleanup_outer_temp_logs(sandbox)
    cleanup_bytes = (cleanup_issue or "").encode("utf-8", errors="replace")
    record["raw_temp_cleanup"] = {
        "attempted": True,
        "failed": cleanup_issue is not None,
        "issue_excerpt": (
            cleanup_bytes[:4096].decode("utf-8", errors="replace")
            if cleanup_issue is not None
            else None
        ),
        "issue_truncated": len(cleanup_bytes) > 4096,
    }
    _replace_json(record_path, record)
    return record_path.relative_to(sandbox), cleanup_issue


def _outer_watchdog_suffix(evidence: tuple[Path, str | None] | None) -> str:
    if evidence is None:
        return ""
    path, cleanup_issue = evidence
    suffix = f" Outer watchdog evidence: {path}"
    if cleanup_issue is not None:
        suffix += f" Raw temp cleanup issue: {cleanup_issue}"
    return suffix


def _bounded_outer_bytes(path: Path, fallback: str, maximum_bytes: int) -> tuple[bytes, int]:
    if path.is_file():
        source_size = path.stat().st_size
        with path.open("rb") as stream:
            return stream.read(maximum_bytes), source_size
    value = fallback.encode("utf-8", errors="replace")
    return value[:maximum_bytes], len(value)


def _write_outer_stream(
    output: Path, name: str, bounded: tuple[bytes, int]
) -> dict[str, object]:
    payload, source_size = bounded
    path = output / name
    _write_exclusive(path, payload)
    return {
        "path": name,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
        "source_size_bytes": source_size,
        "truncated": source_size > len(payload),
    }


def _write_exclusive(path: Path, payload: bytes) -> None:
    try:
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise FoundryError(f"Could not retain outer-watchdog evidence: {exc}") from exc


def _replace_json(path: Path, value: dict[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.update")
    _write_exclusive(temporary, json_bytes(value))
    try:
        os.replace(temporary, path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise FoundryError(f"Could not update outer-watchdog evidence: {exc}") from exc


def _cleanup_outer_temp_logs(sandbox: Path) -> str | None:
    issues: list[str] = []
    for name in (
        ".foundry-capture-outer-stdout.tmp",
        ".foundry-capture-outer-stderr.tmp",
    ):
        path = sandbox / name
        try:
            _remove_outer_temp_file(path)
        except OSError as exc:
            issues.append(f"{name}: {exc}")
            try:
                if path.is_file():
                    with path.open("wb") as stream:
                        stream.flush()
                        os.fsync(stream.fileno())
                _remove_outer_temp_file(path)
            except OSError as retry_exc:
                issues.append(f"{name} retry: {retry_exc}")
    return "; ".join(issues) if issues else None


def _remove_outer_temp_file(path: Path) -> None:
    path.unlink(missing_ok=True)


def _terminate_capture_tree(process: subprocess.Popen[bytes], windows_job) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        if windows_job is None:
            raise FoundryError("Capture supervisor has no owned Windows Job Object.")
        _terminate_windows_job(windows_job, process)
        remaining = _windows_godot_process_inventory()
        if remaining:
            raise FoundryError(
                "Capture outer watchdog left Godot processes: " + ", ".join(remaining)
            )
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=10)


def _windows_godot_process_inventory() -> list[str]:
    return [
        name
        for _pid, (_parent, name) in _windows_process_entries().items()
        if name.casefold().startswith("godot") and name.casefold().endswith(".exe")
    ]


def _windows_process_entries() -> dict[int, tuple[int, str]]:
    import ctypes
    from ctypes import wintypes

    class ProcessEntry32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_snapshot = kernel32.CreateToolhelp32Snapshot
    create_snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    create_snapshot.restype = wintypes.HANDLE
    process_first = kernel32.Process32FirstW
    process_first.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W)]
    process_first.restype = wintypes.BOOL
    process_next = kernel32.Process32NextW
    process_next.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W)]
    process_next.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    snapshot = create_snapshot(0x00000002, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        raise FoundryError("Could not create capture final process inventory.")
    entries: dict[int, tuple[int, str]] = {}
    try:
        entry = ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(entry)
        available = bool(process_first(snapshot, ctypes.byref(entry)))
        while available:
            entries[int(entry.th32ProcessID)] = (
                int(entry.th32ParentProcessID),
                str(entry.szExeFile),
            )
            available = bool(process_next(snapshot, ctypes.byref(entry)))
    finally:
        close_handle(snapshot)
    return entries


def _create_windows_kill_job(pid: int):
    import ctypes
    from ctypes import wintypes

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
        )]

    class BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimitInformation),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_job = kernel32.CreateJobObjectW
    create_job.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    create_job.restype = wintypes.HANDLE
    set_information = kernel32.SetInformationJobObject
    set_information.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD
    ]
    set_information.restype = wintypes.BOOL
    open_process = kernel32.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    assign_process = kernel32.AssignProcessToJobObject
    assign_process.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    assign_process.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    job = create_job(None, None)
    if not job:
        raise FoundryError("Could not create capture Windows Job Object.")
    try:
        limits = ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = 0x00002000
        if not set_information(
            job, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            raise FoundryError("Could not configure capture Job kill-on-close.")
        process_handle = open_process(0x0001 | 0x0100 | 0x0400, False, pid)
        if not process_handle:
            raise FoundryError("Could not open suspended capture supervisor.")
        try:
            if not assign_process(job, process_handle):
                raise FoundryError("Could not assign capture supervisor to its Job Object.")
        finally:
            close_handle(process_handle)
        return job
    except Exception:
        close_handle(job)
        raise


def _resume_windows_process(pid: int) -> None:
    import ctypes
    from ctypes import wintypes

    class ThreadEntry32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ThreadID", wintypes.DWORD),
            ("th32OwnerProcessID", wintypes.DWORD),
            ("tpBasePri", wintypes.LONG),
            ("tpDeltaPri", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_snapshot = kernel32.CreateToolhelp32Snapshot
    create_snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    create_snapshot.restype = wintypes.HANDLE
    thread_first = kernel32.Thread32First
    thread_first.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry32)]
    thread_first.restype = wintypes.BOOL
    thread_next = kernel32.Thread32Next
    thread_next.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry32)]
    thread_next.restype = wintypes.BOOL
    open_thread = kernel32.OpenThread
    open_thread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_thread.restype = wintypes.HANDLE
    resume_thread = kernel32.ResumeThread
    resume_thread.argtypes = [wintypes.HANDLE]
    resume_thread.restype = wintypes.DWORD
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    snapshot = create_snapshot(0x00000004, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        raise FoundryError("Could not enumerate suspended capture supervisor thread.")
    resumed = 0
    try:
        entry = ThreadEntry32()
        entry.dwSize = ctypes.sizeof(entry)
        available = bool(thread_first(snapshot, ctypes.byref(entry)))
        while available:
            if int(entry.th32OwnerProcessID) == pid:
                thread = open_thread(0x0002, False, entry.th32ThreadID)
                if not thread:
                    raise FoundryError("Could not open suspended capture thread.")
                try:
                    if resume_thread(thread) == 0xFFFFFFFF:
                        raise FoundryError("Could not resume Job-owned capture supervisor.")
                    resumed += 1
                finally:
                    close_handle(thread)
            available = bool(thread_next(snapshot, ctypes.byref(entry)))
    finally:
        close_handle(snapshot)
    if resumed == 0:
        raise FoundryError("Suspended capture supervisor exposed no resumable thread.")


def _terminate_windows_job(job, process: subprocess.Popen[bytes]) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    terminate_job = kernel32.TerminateJobObject
    terminate_job.argtypes = [wintypes.HANDLE, wintypes.UINT]
    terminate_job.restype = wintypes.BOOL
    if not terminate_job(job, 1):
        _close_windows_job(job)
        raise FoundryError("Could not terminate capture Windows Job Object.")
    process.wait(timeout=10)
    _close_windows_job(job)


def _close_windows_job(job) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    if not close_handle(job):
        raise FoundryError("Could not close capture Windows Job Object.")


def _read_bounded_text(path: Path, maximum_bytes: int) -> str:
    with path.open("rb") as stream:
        return stream.read(maximum_bytes).decode("utf-8", errors="replace")
