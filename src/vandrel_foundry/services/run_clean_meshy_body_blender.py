"""Clean-body-owned bounded Blender child-process contract."""

from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from vandrel_foundry.domain.errors import FoundryError


@dataclass(frozen=True)
class CleanBodyBlenderProcessResult:
    return_code: int
    stdout: str
    stderr: str
    timed_out: bool
    output_limited: bool
    duration_seconds: float


class CleanBodyBlenderRunner(Protocol):
    def __call__(self, arguments: Sequence[str], cwd: Path, environment: Mapping[str, str], timeout_seconds: float, maximum_output_bytes: int) -> CleanBodyBlenderProcessResult: ...


def run_bounded_clean_body_blender(
    arguments: Sequence[str],
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: float,
    maximum_output_bytes: int,
) -> CleanBodyBlenderProcessResult:
    """Run one Blender operation in an owned finite tree with bounded output."""
    started = time.monotonic()
    timed_out = False
    output_limited = False
    job = None
    with tempfile.TemporaryDirectory(prefix=".clean-body-blender-run-", dir=cwd) as raw:
        operation = Path(raw)
        stdout_path = operation / "stdout.log"
        stderr_path = operation / "stderr.log"
        with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
            process = subprocess.Popen(
                list(arguments),
                cwd=cwd,
                env=dict(environment),
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                shell=False,
                start_new_session=os.name != "nt",
                creationflags=0x00000004 if os.name == "nt" else 0,
            )
            try:
                if os.name == "nt":
                    job = _create_kill_job(process.pid)
                    _resume_process(process.pid)
                while process.poll() is None:
                    if time.monotonic() - started > timeout_seconds:
                        timed_out = True
                        _terminate_tree(process, job)
                        job = None
                        break
                    if stdout.tell() + stderr.tell() > maximum_output_bytes:
                        output_limited = True
                        _terminate_tree(process, job)
                        job = None
                        break
                    time.sleep(0.05)
                return_code = process.wait(timeout=5)
            except BaseException:
                if process.poll() is None:
                    _terminate_tree(process, job)
                    job = None
                raise
            finally:
                if job is not None:
                    _close_job(job)
            output_limited = output_limited or stdout.tell() + stderr.tell() > maximum_output_bytes
        stdout_bytes = stdout_path.read_bytes()[:maximum_output_bytes]
        stderr_limit = max(0, maximum_output_bytes - len(stdout_bytes))
        stderr_bytes = stderr_path.read_bytes()[:stderr_limit]
        return CleanBodyBlenderProcessResult(
            return_code=return_code,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            timed_out=timed_out,
            output_limited=output_limited,
            duration_seconds=time.monotonic() - started,
        )


def _terminate_tree(process: subprocess.Popen[bytes], job) -> None:
    if os.name == "nt" and job is not None:
        import ctypes
        from ctypes import wintypes

        terminate = ctypes.WinDLL("kernel32", use_last_error=True).TerminateJobObject
        terminate.argtypes = [wintypes.HANDLE, wintypes.UINT]
        terminate.restype = wintypes.BOOL
        if not terminate(job, 1):
            raise FoundryError("Could not terminate clean-body Blender Job Object.")
        process.wait(timeout=10)
        _close_job(job)
        return
    if os.name != "nt":
        os.killpg(process.pid, signal.SIGKILL)
    else:
        process.kill()
    process.wait(timeout=10)


def _create_kill_job(pid: int):
    import ctypes
    from ctypes import wintypes

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

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BasicLimitInformation), ("IoInfo", IoCounters), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel32.CreateJobObjectW; create.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]; create.restype = wintypes.HANDLE
    configure = kernel32.SetInformationJobObject; configure.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]; configure.restype = wintypes.BOOL
    open_process = kernel32.OpenProcess; open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]; open_process.restype = wintypes.HANDLE
    assign = kernel32.AssignProcessToJobObject; assign.argtypes = [wintypes.HANDLE, wintypes.HANDLE]; assign.restype = wintypes.BOOL
    close = kernel32.CloseHandle; close.argtypes = [wintypes.HANDLE]; close.restype = wintypes.BOOL
    job = create(None, None)
    if not job:
        raise FoundryError("Could not create clean-body Blender Job Object.")
    try:
        limits = ExtendedLimitInformation(); limits.BasicLimitInformation.LimitFlags = 0x00002000
        if not configure(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise FoundryError("Could not configure clean-body Blender kill-on-close.")
        handle = open_process(0x0001 | 0x0100 | 0x0400, False, pid)
        if not handle:
            raise FoundryError("Could not open suspended clean-body Blender process.")
        try:
            if not assign(job, handle):
                raise FoundryError("Could not assign clean-body Blender process to Job Object.")
        finally:
            close(handle)
        return job
    except BaseException:
        close(job)
        raise


def _resume_process(pid: int) -> None:
    import ctypes
    from ctypes import wintypes

    class ThreadEntry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ThreadID", wintypes.DWORD), ("th32OwnerProcessID", wintypes.DWORD), ("tpBasePri", wintypes.LONG), ("tpDeltaPri", wintypes.LONG), ("dwFlags", wintypes.DWORD)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000004, 0)
    entry = ThreadEntry(); entry.dwSize = ctypes.sizeof(entry); resumed = 0
    try:
        available = bool(kernel32.Thread32First(snapshot, ctypes.byref(entry)))
        while available:
            if int(entry.th32OwnerProcessID) == pid:
                thread = kernel32.OpenThread(0x0002, False, entry.th32ThreadID)
                if thread:
                    try:
                        if kernel32.ResumeThread(thread) != 0xFFFFFFFF: resumed += 1
                    finally: kernel32.CloseHandle(thread)
            available = bool(kernel32.Thread32Next(snapshot, ctypes.byref(entry)))
    finally: kernel32.CloseHandle(snapshot)
    if resumed == 0:
        raise FoundryError("Could not resume Job-owned clean-body Blender process.")


def _close_job(job) -> None:
    import ctypes
    if not ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(job):
        raise FoundryError("Could not close clean-body Blender Job Object.")
