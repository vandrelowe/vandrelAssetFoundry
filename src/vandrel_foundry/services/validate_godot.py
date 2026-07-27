import hashlib
import os
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path
from vandrel_foundry.storage.provider_evidence import write_new_json_evidence

VALIDATOR_VERSION = "1"
SAFE_ENVIRONMENT_KEYS = {
    "APPDATA",
    "HOME",
    "LOCALAPPDATA",
    "PATH",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "WINDIR",
}


@dataclass(frozen=True)
class ProcessResult:
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
    ) -> ProcessResult: ...


def validate_godot_sandbox(
    config: FoundryConfig,
    asset_id: str,
    runner: ProcessRunner | None = None,
    environment: Mapping[str, str] | None = None,
) -> ProcessResult:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.workflow.state is not WorkflowState.STAGED:
        raise FoundryError(f"Godot validation requires staged state: {asset_id}")
    executable = config.tools.godot_executable
    if executable is None or not executable.is_absolute() or not executable.is_file():
        raise FoundryError("Configure tools.godot_executable as an existing absolute file.")
    projects = [item for item in manifest.artifacts if item.role == "godot_validation_project"]
    if not projects:
        raise FoundryError(f"No recorded Godot validation project exists: {asset_id}")
    project_artifact = projects[-1]
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    project_path = contained_path(asset_root, project_artifact.path)
    sandbox = project_path.parent
    _verify_staged_artifacts(asset_root, manifest.artifacts, sandbox)

    safe_environment = {
        key: value
        for key, value in (environment or os.environ).items()
        if key.upper() in SAFE_ENVIRONMENT_KEYS
    }
    arguments = [
        str(executable),
        "--headless",
        "--path",
        str(sandbox),
        "--import",
        "--log-file",
        ".foundry-godot.log",
    ]
    process_runner = runner or run_bounded_process
    result = process_runner(
        arguments,
        sandbox,
        safe_environment,
        config.tools.godot_timeout_seconds,
        config.tools.maximum_output_bytes,
    )
    _verify_staged_artifacts(asset_root, manifest.artifacts, sandbox)

    report_number = _next_report_number(asset_root)
    log_relative = RelativeManifestPath(f"reports/godot-validation-{report_number:03d}.log")
    report_relative = RelativeManifestPath(f"reports/godot-validation-{report_number:03d}.json")
    log_path = contained_path(asset_root, log_relative)
    combined = (f"STDOUT\n{result.stdout}\n\nSTDERR\n{result.stderr}\n").encode(
        "utf-8", errors="replace"
    )
    _write_new_bytes(log_path, combined)
    passed = (
        result.return_code == 0
        and not result.timed_out
        and not result.output_limited
        and (sandbox / ".godot" / "imported").is_dir()
    )
    report = {
        "schema_version": 1,
        "asset_id": asset_id,
        "project_artifact_id": project_artifact.artifact_id,
        "project_artifact_sha256": project_artifact.sha256,
        "arguments": [
            "<godot_executable>",
            "--headless",
            "--path",
            "<sandbox>",
            "--import",
            "--log-file",
            ".foundry-godot.log",
        ],
        "return_code": result.return_code,
        "timed_out": result.timed_out,
        "output_limited": result.output_limited,
        "duration_seconds": result.duration_seconds,
        "import_cache_created": (sandbox / ".godot" / "imported").is_dir(),
        "passed": passed,
    }
    write_new_json_evidence(contained_path(asset_root, report_relative), report)
    log_digest, log_size = _hash_file(log_path)
    report_digest, report_size = _hash_file(contained_path(asset_root, report_relative))
    processor = Processor(name="godot_import_validator", version=VALIDATOR_VERSION)
    manifest.artifacts.extend(
        [
            Artifact(
                artifact_id=f"godot_validation_log_{report_number:03d}",
                role="godot_validation_log",
                stage="validation",
                format="log",
                path=log_relative,
                sha256=log_digest,
                size_bytes=log_size,
                derived_from=[project_artifact.artifact_id],
                processor=processor,
            ),
            Artifact(
                artifact_id=f"godot_validation_report_{report_number:03d}",
                role="godot_validation_report",
                stage="validation",
                format="json",
                path=report_relative,
                sha256=report_digest,
                size_bytes=report_size,
                derived_from=[project_artifact.artifact_id],
                processor=processor,
            ),
        ]
    )
    check = {
        "name": "godot_sandbox_import",
        "passed": passed,
        "report": str(report_relative),
    }
    manifest.validation.checks = [
        item for item in manifest.validation.checks if item.get("name") != check["name"]
    ] + [check]
    manifest.validation.result = "passed" if passed else "failed"
    if passed:
        manifest.workflow.state = WorkflowState.REVIEW
        manifest.workflow.blocked_reason = None
        manifest.workflow.last_error = None
    else:
        manifest.workflow.state = WorkflowState.BLOCKED
        manifest.workflow.blocked_reason = "Godot sandbox import validation failed."
        manifest.workflow.last_error = (
            "Godot validation timed out or exceeded output limits."
            if result.timed_out or result.output_limited
            else f"Godot exited with code {result.return_code}."
        )
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    repository.save(
        manifest,
        "godot.sandbox_validated",
        expected_revision=manifest.revision - 1,
    )
    return result


def run_bounded_process(
    arguments: Sequence[str],
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: float,
    maximum_output_bytes: int,
) -> ProcessResult:
    stdout_path = cwd / ".foundry-stdout.tmp"
    stderr_path = cwd / ".foundry-stderr.tmp"
    godot_log_path = cwd / ".foundry-godot.log"
    started = time.monotonic()
    timed_out = False
    output_limited = False
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
            )
            while process.poll() is None:
                elapsed = time.monotonic() - started
                size = (
                    stdout_stream.tell()
                    + stderr_stream.tell()
                    + (godot_log_path.stat().st_size if godot_log_path.exists() else 0)
                )
                if elapsed > timeout_seconds:
                    timed_out = True
                    process.kill()
                    break
                if size > maximum_output_bytes:
                    output_limited = True
                    process.kill()
                    break
                time.sleep(0.05)
            return_code = process.wait(timeout=5)
            final_size = (
                stdout_stream.tell()
                + stderr_stream.tell()
                + (godot_log_path.stat().st_size if godot_log_path.exists() else 0)
            )
            output_limited = output_limited or final_size > maximum_output_bytes
        stdout = _read_bounded_text(stdout_path, maximum_output_bytes)
        remaining = max(0, maximum_output_bytes - len(stdout.encode("utf-8")))
        stderr = _read_bounded_text(stderr_path, remaining)
        remaining = max(0, remaining - len(stderr.encode("utf-8")))
        if godot_log_path.exists() and remaining:
            stdout += "\nGODOT LOG\n" + _read_bounded_text(godot_log_path, remaining)
        return ProcessResult(
            return_code=return_code,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            output_limited=output_limited,
            duration_seconds=time.monotonic() - started,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise FoundryError(f"Could not execute bounded Godot validation: {exc}") from exc
    finally:
        stdout_path.unlink(missing_ok=True)
        stderr_path.unlink(missing_ok=True)
        godot_log_path.unlink(missing_ok=True)


def _verify_staged_artifacts(
    asset_root: Path,
    artifacts: list[Artifact],
    sandbox: Path,
) -> None:
    staged = [
        item
        for item in artifacts
        if item.stage == "staged" and contained_path(asset_root, item.path).parent == sandbox
    ]
    if not staged:
        raise FoundryError("No recorded staged artifacts belong to the sandbox.")
    for artifact in staged:
        digest, size = _hash_file(contained_path(asset_root, artifact.path))
        if digest != artifact.sha256 or size != artifact.size_bytes:
            raise FoundryError(f"Godot sandbox input changed: {artifact.artifact_id}")


def _next_report_number(asset_root: Path) -> int:
    number = 1
    while contained_path(
        asset_root,
        RelativeManifestPath(f"reports/godot-validation-{number:03d}.json"),
    ).exists():
        number += 1
    return number


def _write_new_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        path.unlink(missing_ok=True)
        raise FoundryError(f"Could not write Godot validation log: {exc}") from exc


def _read_bounded_text(path: Path, maximum_bytes: int) -> str:
    with path.open("rb") as stream:
        return stream.read(maximum_bytes).decode("utf-8", errors="replace")


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise FoundryError(f"Could not hash Godot validation file: {exc}") from exc
    return digest.hexdigest(), size
