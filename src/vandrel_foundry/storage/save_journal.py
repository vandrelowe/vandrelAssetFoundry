import base64
import ctypes
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import AssetManifest
from vandrel_foundry.storage.events import append_event_bytes

JOURNAL_NAME = "manifest.pending-save.json"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_OS_REPLACE = os.replace


class _JournalRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    version: Literal[1] = 1
    state: Literal["pending", "complete"]
    asset_id: str
    source_revision: int | None
    target_revision: int = Field(ge=1)
    source_manifest_sha256: str | None = Field(pattern=_SHA256_PATTERN)
    target_manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    pre_event_length: int = Field(ge=0)
    pre_event_sha256: str = Field(pattern=_SHA256_PATTERN)
    event_type: str
    event_base64: str


@dataclass(frozen=True)
class PendingSave:
    state: Literal["pending", "complete"]
    asset_id: str
    source_revision: int | None
    target_revision: int
    source_manifest_sha256: str | None
    target_manifest_sha256: str
    pre_event_length: int
    pre_event_sha256: str
    event_type: str
    event_bytes: bytes


@dataclass(frozen=True)
class SaveDiagnosis:
    status: Literal[
        "none",
        "complete",
        "source_intact",
        "event_missing",
        "event_partial",
        "event_complete",
        "mismatch",
    ]
    detail: str


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def create_pending_save(
    *,
    asset_id: str,
    source_revision: int | None,
    target_revision: int,
    source_manifest_bytes: bytes | None,
    target_manifest_bytes: bytes,
    event_log_bytes: bytes,
    event_type: str,
    event_bytes: bytes,
) -> PendingSave:
    pending = PendingSave(
        state="pending",
        asset_id=asset_id,
        source_revision=source_revision,
        target_revision=target_revision,
        source_manifest_sha256=(
            sha256_bytes(source_manifest_bytes) if source_manifest_bytes is not None else None
        ),
        target_manifest_sha256=sha256_bytes(target_manifest_bytes),
        pre_event_length=len(event_log_bytes),
        pre_event_sha256=sha256_bytes(event_log_bytes),
        event_type=event_type,
        event_bytes=event_bytes,
    )
    _validate_event(pending)
    return pending


def read_journal(path: Path, expected_asset_id: str) -> PendingSave | None:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise FoundryError(f"Could not read pending save journal for {expected_asset_id}: {exc}") from exc
    try:
        record = _JournalRecord.model_validate_json(raw)
        event_bytes = base64.b64decode(record.event_base64, validate=True)
    except (ValidationError, ValueError) as exc:
        raise FoundryError(f"Invalid pending save journal for {expected_asset_id}: {exc}") from exc
    pending = PendingSave(
        state=record.state,
        asset_id=record.asset_id,
        source_revision=record.source_revision,
        target_revision=record.target_revision,
        source_manifest_sha256=record.source_manifest_sha256,
        target_manifest_sha256=record.target_manifest_sha256,
        pre_event_length=record.pre_event_length,
        pre_event_sha256=record.pre_event_sha256,
        event_type=record.event_type,
        event_bytes=event_bytes,
    )
    if pending.asset_id != expected_asset_id:
        raise FoundryError(
            f"Pending save journal asset mismatch for {expected_asset_id}: {pending.asset_id}"
        )
    _validate_event(pending)
    if (pending.source_revision is None) != (pending.source_manifest_sha256 is None):
        raise FoundryError(
            f"Invalid pending save journal for {expected_asset_id}: "
            "source revision and hash must both be present or absent"
        )
    return pending


def write_journal(path: Path, pending: PendingSave) -> None:
    record = _JournalRecord(
        state=pending.state,
        asset_id=pending.asset_id,
        source_revision=pending.source_revision,
        target_revision=pending.target_revision,
        source_manifest_sha256=pending.source_manifest_sha256,
        target_manifest_sha256=pending.target_manifest_sha256,
        pre_event_length=pending.pre_event_length,
        pre_event_sha256=pending.pre_event_sha256,
        event_type=pending.event_type,
        event_base64=base64.b64encode(pending.event_bytes).decode("ascii"),
    )
    value = (json.dumps(record.model_dump(mode="json"), indent=2) + "\n").encode("utf-8")
    _write_atomic_durable(path, value)


def diagnose_pending_save(directory: Path, asset_id: str) -> SaveDiagnosis:
    pending = read_journal(directory / JOURNAL_NAME, asset_id)
    if pending is None:
        return SaveDiagnosis("none", "No pending save journal.")
    if pending.state == "complete":
        return SaveDiagnosis("complete", "The last save journal is durably complete.")
    return _classify(directory, pending)


def _reconcile_pending_save_locked(directory: Path, asset_id: str) -> SaveDiagnosis:
    """Mutate pending state only for a repository caller already holding the asset lock."""
    journal_path = directory / JOURNAL_NAME
    pending = read_journal(journal_path, asset_id)
    if pending is None:
        return SaveDiagnosis("none", "No pending save journal.")
    if pending.state == "complete":
        return SaveDiagnosis("complete", "The last save journal is durably complete.")
    diagnosis = _classify(directory, pending)
    events_path = directory / "events.jsonl"
    if diagnosis.status == "source_intact":
        write_journal(journal_path, replace(pending, state="complete"))
    elif diagnosis.status == "event_missing":
        append_event_bytes(events_path, pending.event_bytes)
        write_journal(journal_path, replace(pending, state="complete"))
    elif diagnosis.status == "event_partial":
        _truncate_event_log(events_path, pending.pre_event_length)
        append_event_bytes(events_path, pending.event_bytes)
        write_journal(journal_path, replace(pending, state="complete"))
    elif diagnosis.status == "event_complete":
        write_journal(journal_path, replace(pending, state="complete"))
    else:
        raise FoundryError(
            f"Pending save reconciliation failed closed for {asset_id}: {diagnosis.detail}"
        )
    return diagnosis


def _classify(directory: Path, pending: PendingSave) -> SaveDiagnosis:
    manifest_bytes = _read_optional(directory / "manifest.json")
    event_bytes = _read_optional(directory / "events.jsonl") or b""
    manifest_state = _manifest_state(manifest_bytes, pending)
    event_state = _event_state(event_bytes, pending)
    if manifest_state == "source" and event_state == "prefix":
        return SaveDiagnosis("source_intact", "Source manifest and pre-event log are exact.")
    if manifest_state == "target" and event_state == "prefix":
        return SaveDiagnosis("event_missing", "Target manifest is exact and event is absent.")
    if manifest_state == "target" and event_state == "partial":
        return SaveDiagnosis("event_partial", "Target manifest and exact event prefix are present.")
    if manifest_state == "target" and event_state == "complete":
        return SaveDiagnosis("event_complete", "Target manifest and exact event are present.")
    return SaveDiagnosis(
        "mismatch",
        f"manifest={manifest_state}, events={event_state}; no deterministic repair is allowed",
    )


def _manifest_state(value: bytes | None, pending: PendingSave) -> str:
    if value is None:
        return "source" if pending.source_manifest_sha256 is None else "missing"
    digest = sha256_bytes(value)
    if digest == pending.target_manifest_sha256:
        return (
            "target"
            if _manifest_identity(value) == (pending.asset_id, pending.target_revision)
            else "invalid_target"
        )
    if digest == pending.source_manifest_sha256:
        return (
            "source"
            if _manifest_identity(value) == (pending.asset_id, pending.source_revision)
            else "invalid_source"
        )
    return "other"


def _event_state(value: bytes, pending: PendingSave) -> str:
    if len(value) < pending.pre_event_length:
        return "short"
    prefix = value[: pending.pre_event_length]
    if sha256_bytes(prefix) != pending.pre_event_sha256:
        return "wrong_prefix"
    tail = value[pending.pre_event_length :]
    if not tail:
        return "prefix"
    if tail == pending.event_bytes:
        return "complete"
    if len(tail) < len(pending.event_bytes) and pending.event_bytes.startswith(tail):
        return "partial"
    return "other_tail"


def _manifest_identity(value: bytes) -> tuple[str, int] | None:
    try:
        manifest = AssetManifest.model_validate_json(value)
    except ValidationError:
        return None
    return manifest.asset.asset_id, manifest.revision


def _validate_event(pending: PendingSave) -> None:
    try:
        if not pending.event_bytes.endswith(b"\n") or b"\n" in pending.event_bytes[:-1]:
            raise ValueError("event must be exactly one newline-terminated JSON record")
        event = json.loads(pending.event_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise FoundryError(f"Invalid pending event for {pending.asset_id}: {exc}") from exc
    if not isinstance(event, dict) or set(event) != {"timestamp", "event", "asset_id", "revision"}:
        raise FoundryError(f"Invalid pending event shape for {pending.asset_id}")
    if (
        event["asset_id"] != pending.asset_id
        or event["revision"] != pending.target_revision
        or type(event["revision"]) is not int
        or event["event"] != pending.event_type
        or not pending.event_type
        or not isinstance(event["timestamp"], str)
        or not event["timestamp"]
    ):
        raise FoundryError(f"Pending event identity mismatch for {pending.asset_id}")


def _read_optional(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise FoundryError(f"Could not inspect pending save state at {path}: {exc}") from exc


def _truncate_event_log(path: Path, length: int) -> None:
    with path.open("r+b") as stream:
        stream.truncate(length)
        stream.flush()
        os.fsync(stream.fileno())


def _write_atomic_durable(path: Path, value: bytes) -> None:
    descriptor, raw_path = tempfile.mkstemp(prefix=".pending-save-", suffix=".tmp", dir=path.parent)
    temporary = Path(raw_path)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        _replace_file_durable(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _replace_file_durable(source: Path, destination: Path) -> None:
    if os.name == "nt":
        _replace_file_windows(source, destination)
        return
    _OS_REPLACE(source, destination)
    descriptor = os.open(destination.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _replace_file_windows(source: Path, destination: Path) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    move_file = kernel32.MoveFileExW
    move_file.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
    move_file.restype = ctypes.c_int
    replace_existing = 0x1
    write_through = 0x8
    if not move_file(str(source), str(destination), replace_existing | write_through):
        error = ctypes.get_last_error()
        raise OSError(error, ctypes.FormatError(error), str(destination))
