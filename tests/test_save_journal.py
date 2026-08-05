import base64
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType

import pytest

from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.inspect_assets import initialize_workspace
from vandrel_foundry.storage import events as event_storage
from vandrel_foundry.storage import manifests as manifest_storage
from vandrel_foundry.storage import save_journal
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.save_journal import JOURNAL_NAME

ASSET_ID = "journal_asset_001"
EVENT_TYPE = "test.journal_update"


def test_completed_journal_records_exact_bounded_recovery_metadata(
    config, lanes, prompt: Path, monkeypatch
) -> None:
    repository, update, root, before = _prepared_update(config, lanes, prompt)
    monkeypatch.setattr(event_storage, "datetime", _FixedDateTime)

    repository.save(update, EVENT_TYPE, expected_revision=2)

    journal = json.loads((root / JOURNAL_NAME).read_text(encoding="utf-8"))
    event_bytes = _event_bytes()
    assert journal == {
        "version": 1,
        "state": "complete",
        "asset_id": ASSET_ID,
        "source_revision": 2,
        "target_revision": 3,
        "source_manifest_sha256": _sha(before["manifest"]),
        "target_manifest_sha256": _sha((root / "manifest.json").read_bytes()),
        "pre_event_length": len(before["events"]),
        "pre_event_sha256": _sha(before["events"]),
        "event_type": EVENT_TYPE,
        "event_base64": base64.b64encode(event_bytes).decode("ascii"),
    }
    assert base64.b64decode(journal["event_base64"]) == event_bytes
    assert "notes" not in journal


def test_journal_create_replace_failure_precedes_every_save_mutation(
    config, lanes, prompt: Path, monkeypatch
) -> None:
    repository, update, root, before = _prepared_update(config, lanes, prompt)

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("seeded journal replace failure")

    monkeypatch.setattr(save_journal, "_replace_file_durable", fail_replace)
    with pytest.raises(FoundryError, match="seeded journal replace failure") as raised:
        repository.save(update, EVENT_TYPE, expected_revision=2)

    assert isinstance(raised.value.__cause__, OSError)
    assert _state(root) == before
    assert not list(root.glob(".pending-save-*.tmp"))
    assert repository.diagnose_pending_save(ASSET_ID).status == "complete"


def test_reported_journal_durability_failure_after_replace_is_recoverable(
    config, lanes, prompt: Path, monkeypatch
) -> None:
    repository, update, root, before = _prepared_update(config, lanes, prompt)
    original_write = manifest_storage.write_journal

    def durable_then_fail(path, pending):
        original_write(path, pending)
        raise OSError("seeded post-journal-replace durability failure")

    monkeypatch.setattr(manifest_storage, "write_journal", durable_then_fail)
    with pytest.raises(FoundryError, match="post-journal-replace durability failure"):
        repository.save(update, EVENT_TYPE, expected_revision=2)

    assert (root / "manifest.json").read_bytes() == before["manifest"]
    assert (root / "events.jsonl").read_bytes() == before["events"]
    assert repository.diagnose_pending_save(ASSET_ID).status == "source_intact"
    monkeypatch.undo()
    repository.reconcile_pending_save(ASSET_ID)
    repository.save(update, EVENT_TYPE, expected_revision=2)
    assert _event_revisions(root) == [1, 2, 3]


@pytest.mark.parametrize("failure", ["previous_copy", "manifest_replace"])
def test_precommit_interruption_reconciles_then_exact_retry_succeeds(
    config, lanes, prompt: Path, monkeypatch, failure: str
) -> None:
    repository, update, root, before = _prepared_update(config, lanes, prompt)
    if failure == "previous_copy":
        monkeypatch.setattr(
            manifest_storage.shutil,
            "copy2",
            lambda *_args: (_ for _ in ()).throw(OSError("seeded previous-copy failure")),
        )
    else:
        monkeypatch.setattr(
            manifest_storage.os,
            "replace",
            lambda *_args: (_ for _ in ()).throw(OSError("seeded manifest-replace failure")),
        )

    with pytest.raises(FoundryError):
        repository.save(update, EVENT_TYPE, expected_revision=2)

    diagnosis = repository.diagnose_pending_save(ASSET_ID)
    assert diagnosis.status == "source_intact"
    assert (root / "manifest.json").read_bytes() == before["manifest"]
    assert (root / "events.jsonl").read_bytes() == before["events"]
    before_diagnosis = _all_bytes(root)
    assert repository.diagnose_pending_save(ASSET_ID) == diagnosis
    assert _all_bytes(root) == before_diagnosis

    repository.reconcile_pending_save(ASSET_ID)
    monkeypatch.undo()
    repository.save(update, EVENT_TYPE, expected_revision=2)

    assert repository.load(ASSET_ID).revision == 3
    assert repository.diagnose_pending_save(ASSET_ID).status == "complete"
    assert _event_revisions(root) == [1, 2, 3]


def test_reported_manifest_replace_failure_after_commit_reconciles_target(
    config, lanes, prompt: Path, monkeypatch
) -> None:
    repository, update, root, before = _prepared_update(config, lanes, prompt)
    original_replace = manifest_storage.os.replace

    def replace_then_fail(source: Path, destination: Path) -> None:
        original_replace(source, destination)
        raise OSError("seeded post-manifest-replace failure")

    monkeypatch.setattr(manifest_storage.os, "replace", replace_then_fail)
    with pytest.raises(FoundryError, match="post-manifest-replace failure"):
        repository.save(update, EVENT_TYPE, expected_revision=2)

    assert repository.load(ASSET_ID).revision == 3
    assert (root / "events.jsonl").read_bytes() == before["events"]
    assert repository.diagnose_pending_save(ASSET_ID).status == "event_missing"
    monkeypatch.undo()
    repository.reconcile_pending_save(ASSET_ID)
    assert _event_revisions(root) == [1, 2, 3]


@pytest.mark.parametrize(
    ("failure", "expected_status"),
    [
        ("prewrite", "event_missing"),
        ("partial", "event_partial"),
        ("postwrite", "event_complete"),
    ],
)
def test_postcommit_interruption_reconciliation_is_exact_and_idempotent(
    config,
    lanes,
    prompt: Path,
    monkeypatch,
    failure: str,
    expected_status: str,
) -> None:
    repository, update, root, before = _prepared_update(config, lanes, prompt)
    monkeypatch.setattr(event_storage, "datetime", _FixedDateTime)
    _inject_event_failure(monkeypatch, root / "events.jsonl", failure)

    with pytest.raises(FoundryError):
        repository.save(update, EVENT_TYPE, expected_revision=2)

    assert repository.load(ASSET_ID).revision == 3
    assert repository.diagnose_pending_save(ASSET_ID).status == expected_status
    monkeypatch.undo()
    repository.reconcile_pending_save(ASSET_ID)
    exact_events = before["events"] + _event_bytes()
    assert (root / "events.jsonl").read_bytes() == exact_events
    assert repository.diagnose_pending_save(ASSET_ID).status == "complete"

    completed = _all_bytes(root)
    result = repository.reconcile_pending_save(ASSET_ID)
    assert result.status == "complete"
    assert _all_bytes(root) == completed


def test_next_state_changing_save_reconciles_pending_event_under_same_lock(
    config, lanes, prompt: Path, monkeypatch
) -> None:
    repository, update, root, _before = _prepared_update(config, lanes, prompt)
    _inject_event_failure(monkeypatch, root / "events.jsonl", "prewrite")
    with pytest.raises(FoundryError):
        repository.save(update, EVENT_TYPE, expected_revision=2)
    monkeypatch.undo()

    next_update = repository.load(ASSET_ID)
    next_update.revision = 4
    next_update.notes = "revision four"
    repository.save(next_update, "test.next", expected_revision=3)

    assert repository.load(ASSET_ID).revision == 4
    assert _event_revisions(root) == [1, 2, 3, 4]
    assert repository.diagnose_pending_save(ASSET_ID).status == "complete"


def test_reconcile_uses_asset_lock_while_diagnosis_does_not(config, lanes, prompt: Path) -> None:
    _repository, _update, _root, _before = _prepared_update(config, lanes, prompt)
    observed: list[Path] = []

    class RecordingLock:
        def __enter__(self):
            observed.append(Path("entered"))
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            return None

    def factory(path: Path) -> RecordingLock:
        observed.append(path)
        return RecordingLock()

    instrumented = ManifestRepository(config.foundry.workspace_root, factory)
    assert not hasattr(save_journal, "reconcile_pending_save")
    instrumented.diagnose_pending_save(ASSET_ID)
    assert observed == []
    instrumented.reconcile_pending_save(ASSET_ID)
    assert observed == [
        config.foundry.workspace_root / "locks" / f"{ASSET_ID}.lock",
        Path("entered"),
    ]


def test_truncation_interruption_fails_without_appending_and_retry_recovers(
    config, lanes, prompt: Path, monkeypatch
) -> None:
    repository, update, root, before = _prepared_update(config, lanes, prompt)
    monkeypatch.setattr(event_storage, "datetime", _FixedDateTime)
    _inject_event_failure(monkeypatch, root / "events.jsonl", "partial")
    with pytest.raises(FoundryError):
        repository.save(update, EVENT_TYPE, expected_revision=2)
    monkeypatch.undo()
    partial_bytes = (root / "events.jsonl").read_bytes()

    monkeypatch.setattr(
        save_journal,
        "_truncate_event_log",
        lambda *_args: (_ for _ in ()).throw(OSError("seeded truncate failure")),
    )
    with pytest.raises(FoundryError, match="seeded truncate failure"):
        repository.reconcile_pending_save(ASSET_ID)
    assert (root / "events.jsonl").read_bytes() == partial_bytes
    assert repository.diagnose_pending_save(ASSET_ID).status == "event_partial"

    monkeypatch.undo()
    repository.reconcile_pending_save(ASSET_ID)
    assert (root / "events.jsonl").read_bytes() == before["events"] + _event_bytes()


def test_reported_truncation_failure_after_exact_truncate_remains_retryable(
    config, lanes, prompt: Path, monkeypatch
) -> None:
    repository, update, root, before = _prepared_update(config, lanes, prompt)
    monkeypatch.setattr(event_storage, "datetime", _FixedDateTime)
    _inject_event_failure(monkeypatch, root / "events.jsonl", "partial")
    with pytest.raises(FoundryError):
        repository.save(update, EVENT_TYPE, expected_revision=2)
    monkeypatch.undo()
    original_truncate = save_journal._truncate_event_log

    def truncate_then_fail(path: Path, length: int) -> None:
        original_truncate(path, length)
        raise OSError("seeded post-truncate fsync failure")

    monkeypatch.setattr(save_journal, "_truncate_event_log", truncate_then_fail)
    with pytest.raises(FoundryError, match="post-truncate fsync failure"):
        repository.reconcile_pending_save(ASSET_ID)
    assert (root / "events.jsonl").read_bytes() == before["events"]
    assert repository.diagnose_pending_save(ASSET_ID).status == "event_missing"

    monkeypatch.undo()
    repository.reconcile_pending_save(ASSET_ID)
    assert (root / "events.jsonl").read_bytes() == before["events"] + _event_bytes()


def test_reconciled_append_interruption_remains_retryable(
    config, lanes, prompt: Path, monkeypatch
) -> None:
    repository, update, root, before = _prepared_update(config, lanes, prompt)
    monkeypatch.setattr(event_storage, "datetime", _FixedDateTime)
    _inject_event_failure(monkeypatch, root / "events.jsonl", "prewrite")
    with pytest.raises(FoundryError):
        repository.save(update, EVENT_TYPE, expected_revision=2)
    monkeypatch.undo()

    monkeypatch.setattr(
        save_journal,
        "append_event_bytes",
        lambda *_args: (_ for _ in ()).throw(OSError("seeded reconciled append failure")),
    )
    with pytest.raises(FoundryError, match="seeded reconciled append failure"):
        repository.reconcile_pending_save(ASSET_ID)
    assert (root / "events.jsonl").read_bytes() == before["events"]
    assert repository.diagnose_pending_save(ASSET_ID).status == "event_missing"

    monkeypatch.undo()
    repository.reconcile_pending_save(ASSET_ID)
    assert (root / "events.jsonl").read_bytes() == before["events"] + _event_bytes()


def test_reconciled_partial_append_is_proven_and_retryable(
    config, lanes, prompt: Path, monkeypatch
) -> None:
    repository, update, root, before = _prepared_update(config, lanes, prompt)
    monkeypatch.setattr(event_storage, "datetime", _FixedDateTime)
    _inject_event_failure(monkeypatch, root / "events.jsonl", "prewrite")
    with pytest.raises(FoundryError):
        repository.save(update, EVENT_TYPE, expected_revision=2)
    monkeypatch.undo()

    def partial_append(path: Path, event_bytes: bytes) -> None:
        with path.open("ab") as stream:
            stream.write(event_bytes[: len(event_bytes) // 2])
            stream.flush()
        raise OSError("seeded reconciled partial append")

    monkeypatch.setattr(save_journal, "append_event_bytes", partial_append)
    with pytest.raises(FoundryError, match="reconciled partial append"):
        repository.reconcile_pending_save(ASSET_ID)
    assert repository.diagnose_pending_save(ASSET_ID).status == "event_partial"

    monkeypatch.undo()
    repository.reconcile_pending_save(ASSET_ID)
    assert (root / "events.jsonl").read_bytes() == before["events"] + _event_bytes()


def test_reconciled_complete_append_reported_failure_is_idempotent(
    config, lanes, prompt: Path, monkeypatch
) -> None:
    repository, update, root, before = _prepared_update(config, lanes, prompt)
    monkeypatch.setattr(event_storage, "datetime", _FixedDateTime)
    _inject_event_failure(monkeypatch, root / "events.jsonl", "prewrite")
    with pytest.raises(FoundryError):
        repository.save(update, EVENT_TYPE, expected_revision=2)
    monkeypatch.undo()
    original_append = save_journal.append_event_bytes

    def append_then_fail(path: Path, event_bytes: bytes) -> None:
        original_append(path, event_bytes)
        raise OSError("seeded reconciled postwrite fsync failure")

    monkeypatch.setattr(save_journal, "append_event_bytes", append_then_fail)
    with pytest.raises(FoundryError, match="reconciled postwrite fsync failure"):
        repository.reconcile_pending_save(ASSET_ID)
    exact_events = before["events"] + _event_bytes()
    assert (root / "events.jsonl").read_bytes() == exact_events
    assert repository.diagnose_pending_save(ASSET_ID).status == "event_complete"

    monkeypatch.undo()
    repository.reconcile_pending_save(ASSET_ID)
    assert (root / "events.jsonl").read_bytes() == exact_events
    assert repository.diagnose_pending_save(ASSET_ID).status == "complete"


@pytest.mark.parametrize("completion_outcome", ["before_write", "after_write"])
def test_reconciliation_completion_interruption_never_duplicates_event(
    config,
    lanes,
    prompt: Path,
    monkeypatch,
    completion_outcome: str,
) -> None:
    repository, update, root, before = _prepared_update(config, lanes, prompt)
    monkeypatch.setattr(event_storage, "datetime", _FixedDateTime)
    _inject_event_failure(monkeypatch, root / "events.jsonl", "prewrite")
    with pytest.raises(FoundryError):
        repository.save(update, EVENT_TYPE, expected_revision=2)
    monkeypatch.undo()
    original_write = save_journal.write_journal

    def fail_completion(path, pending):
        if completion_outcome == "after_write":
            original_write(path, pending)
        raise OSError(f"seeded reconciliation completion {completion_outcome}")

    monkeypatch.setattr(save_journal, "write_journal", fail_completion)
    with pytest.raises(FoundryError, match=f"reconciliation completion {completion_outcome}"):
        repository.reconcile_pending_save(ASSET_ID)

    exact_events = before["events"] + _event_bytes()
    assert (root / "events.jsonl").read_bytes() == exact_events
    expected_status = "event_complete" if completion_outcome == "before_write" else "complete"
    assert repository.diagnose_pending_save(ASSET_ID).status == expected_status
    monkeypatch.undo()
    repository.reconcile_pending_save(ASSET_ID)
    assert (root / "events.jsonl").read_bytes() == exact_events
    assert repository.diagnose_pending_save(ASSET_ID).status == "complete"


def test_journal_completion_interruption_does_not_duplicate_complete_event(
    config, lanes, prompt: Path, monkeypatch
) -> None:
    repository, update, root, before = _prepared_update(config, lanes, prompt)
    monkeypatch.setattr(event_storage, "datetime", _FixedDateTime)
    original_write = manifest_storage.write_journal
    calls = 0

    def fail_completion(path, pending):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("seeded journal completion failure")
        original_write(path, pending)

    monkeypatch.setattr(manifest_storage, "write_journal", fail_completion)
    with pytest.raises(FoundryError, match="seeded journal completion failure"):
        repository.save(update, EVENT_TYPE, expected_revision=2)

    exact_events = before["events"] + _event_bytes()
    assert (root / "events.jsonl").read_bytes() == exact_events
    assert repository.diagnose_pending_save(ASSET_ID).status == "event_complete"
    monkeypatch.undo()
    repository.reconcile_pending_save(ASSET_ID)
    assert (root / "events.jsonl").read_bytes() == exact_events
    assert repository.diagnose_pending_save(ASSET_ID).status == "complete"


def test_reported_journal_completion_failure_after_durable_mark_is_idempotent(
    config, lanes, prompt: Path, monkeypatch
) -> None:
    repository, update, root, before = _prepared_update(config, lanes, prompt)
    monkeypatch.setattr(event_storage, "datetime", _FixedDateTime)
    original_write = manifest_storage.write_journal
    calls = 0

    def complete_then_fail(path, pending):
        nonlocal calls
        calls += 1
        original_write(path, pending)
        if calls == 2:
            raise OSError("seeded post-completion durability failure")

    monkeypatch.setattr(manifest_storage, "write_journal", complete_then_fail)
    with pytest.raises(FoundryError, match="post-completion durability failure"):
        repository.save(update, EVENT_TYPE, expected_revision=2)

    exact_events = before["events"] + _event_bytes()
    assert (root / "events.jsonl").read_bytes() == exact_events
    assert repository.diagnose_pending_save(ASSET_ID).status == "complete"
    monkeypatch.undo()
    repository.reconcile_pending_save(ASSET_ID)
    assert (root / "events.jsonl").read_bytes() == exact_events


@pytest.mark.parametrize("field", ["event_type", "asset_id", "revision"])
def test_tampered_event_identity_is_rejected_without_mutation(
    config, lanes, prompt: Path, monkeypatch, field: str
) -> None:
    repository, update, root, _before = _prepared_update(config, lanes, prompt)
    _inject_event_failure(monkeypatch, root / "events.jsonl", "prewrite")
    with pytest.raises(FoundryError):
        repository.save(update, EVENT_TYPE, expected_revision=2)
    monkeypatch.undo()
    journal_path = root / JOURNAL_NAME
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    event = json.loads(base64.b64decode(journal["event_base64"]))
    if field == "event_type":
        event["event"] = "wrong.event"
    elif field == "asset_id":
        event["asset_id"] = "wrong_asset"
    else:
        event["revision"] = 99
    journal["event_base64"] = base64.b64encode(
        (json.dumps(event, separators=(",", ":")) + "\n").encode()
    ).decode("ascii")
    journal_path.write_text(json.dumps(journal), encoding="utf-8")
    before_reconcile = _all_bytes(root)

    with pytest.raises(FoundryError, match="Pending event identity mismatch"):
        repository.reconcile_pending_save(ASSET_ID)
    assert _all_bytes(root) == before_reconcile


def test_tampered_journal_asset_identity_is_rejected_without_mutation(
    config, lanes, prompt: Path
) -> None:
    repository, _update, root, _before = _prepared_update(config, lanes, prompt)
    journal_path = root / JOURNAL_NAME
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    journal["state"] = "pending"
    journal["asset_id"] = "wrong_asset"
    journal_path.write_text(json.dumps(journal), encoding="utf-8")
    before_reconcile = _all_bytes(root)

    with pytest.raises(FoundryError, match="Pending save journal asset mismatch"):
        repository.reconcile_pending_save(ASSET_ID)
    assert _all_bytes(root) == before_reconcile


@pytest.mark.parametrize(
    ("tamper", "detail"),
    [
        ("manifest_hash", "manifest=other"),
        ("pre_event_hash", "events=wrong_prefix"),
        ("wrong_tail", "events=other_tail"),
    ],
)
def test_unproven_manifest_or_event_combinations_fail_closed(
    config, lanes, prompt: Path, monkeypatch, tamper: str, detail: str
) -> None:
    repository, update, root, _before = _prepared_update(config, lanes, prompt)
    _inject_event_failure(monkeypatch, root / "events.jsonl", "prewrite")
    with pytest.raises(FoundryError):
        repository.save(update, EVENT_TYPE, expected_revision=2)
    monkeypatch.undo()
    journal_path = root / JOURNAL_NAME
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    if tamper == "manifest_hash":
        journal["target_manifest_sha256"] = "0" * 64
        journal_path.write_text(json.dumps(journal), encoding="utf-8")
    elif tamper == "pre_event_hash":
        journal["pre_event_sha256"] = "0" * 64
        journal_path.write_text(json.dumps(journal), encoding="utf-8")
    else:
        with (root / "events.jsonl").open("ab") as stream:
            stream.write(b"wrong-tail")
    before_reconcile = _all_bytes(root)

    with pytest.raises(FoundryError, match=detail):
        repository.reconcile_pending_save(ASSET_ID)
    assert _all_bytes(root) == before_reconcile


def test_posix_durable_replace_syncs_parent_after_atomic_replace(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(save_journal.os, "name", "posix")
    monkeypatch.setattr(
        save_journal,
        "_OS_REPLACE",
        lambda old, new: calls.append(("replace", (old, new))),
    )
    monkeypatch.setattr(
        save_journal.os,
        "open",
        lambda path, flags: calls.append(("open", (path, flags))) or 17,
    )
    monkeypatch.setattr(
        save_journal.os,
        "fsync",
        lambda descriptor: calls.append(("fsync", descriptor)),
    )
    monkeypatch.setattr(
        save_journal.os,
        "close",
        lambda descriptor: calls.append(("close", descriptor)),
    )

    save_journal._replace_file_durable(source, destination)

    assert calls == [
        ("replace", (source, destination)),
        ("open", (tmp_path, save_journal.os.O_RDONLY)),
        ("fsync", 17),
        ("close", 17),
    ]


def test_windows_durable_replace_requests_replace_existing_and_write_through(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[tuple[str, str, int]] = []

    class MoveFile:
        argtypes = None
        restype = None

        def __call__(self, source: str, destination: str, flags: int) -> int:
            calls.append((source, destination, flags))
            return 1

    class Kernel32:
        MoveFileExW = MoveFile()

    monkeypatch.setattr(save_journal.ctypes, "WinDLL", lambda *_args, **_kwargs: Kernel32())
    source = tmp_path / "source"
    destination = tmp_path / "destination"

    save_journal._replace_file_windows(source, destination)

    assert calls == [(str(source), str(destination), 0x1 | 0x8)]


def test_windows_durable_replace_native_failure_becomes_os_error(
    tmp_path: Path, monkeypatch
) -> None:
    class MoveFile:
        argtypes = None
        restype = None

        def __call__(self, _source: str, _destination: str, _flags: int) -> int:
            return 0

    class Kernel32:
        MoveFileExW = MoveFile()

    monkeypatch.setattr(save_journal.ctypes, "WinDLL", lambda *_args, **_kwargs: Kernel32())
    monkeypatch.setattr(save_journal.ctypes, "get_last_error", lambda: 5, raising=False)
    monkeypatch.setattr(save_journal.ctypes, "FormatError", lambda _error: "access denied")

    with pytest.raises(OSError, match="access denied") as raised:
        save_journal._replace_file_windows(tmp_path / "source", tmp_path / "destination")

    assert raised.value.errno == 5


def test_windows_replace_failure_propagates_and_atomic_writer_cleans_temp(
    tmp_path: Path, monkeypatch
) -> None:
    destination = tmp_path / "journal.json"
    destination.write_bytes(b"existing")
    monkeypatch.setattr(
        save_journal,
        "_replace_file_durable",
        lambda *_args: (_ for _ in ()).throw(OSError("seeded Windows replace failure")),
    )

    with pytest.raises(OSError, match="seeded Windows replace failure"):
        save_journal._write_atomic_durable(destination, b"replacement")

    assert destination.read_bytes() == b"existing"
    assert not list(tmp_path.glob(".pending-save-*.tmp"))


def _prepared_update(config, lanes, prompt: Path):
    initialize_workspace(config.foundry.workspace_root)
    manifest = create_asset(config, lanes, ASSET_ID, "static_prop", "Journal Asset", prompt)
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest.revision = 2
    manifest.notes = "revision two"
    repository.save(manifest, "test.baseline", expected_revision=1)
    root = repository.asset_directory(ASSET_ID)
    before = _state(root)
    update = repository.load(ASSET_ID)
    update.revision = 3
    update.notes = "revision three"
    return repository, update, root, before


def _state(root: Path) -> dict[str, bytes]:
    return {
        "manifest": (root / "manifest.json").read_bytes(),
        "previous": (root / "manifest.previous.json").read_bytes(),
        "events": (root / "events.jsonl").read_bytes(),
        "journal": (root / JOURNAL_NAME).read_bytes(),
    }


def _all_bytes(root: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(root.iterdir()) if path.is_file()}


def _event_revisions(root: Path) -> list[int]:
    return [
        json.loads(line)["revision"]
        for line in (root / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]


def _event_bytes() -> bytes:
    return (
        json.dumps(
            {
                "timestamp": "2026-07-28T20:00:00Z",
                "event": EVENT_TYPE,
                "asset_id": ASSET_ID,
                "revision": 3,
            },
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _inject_event_failure(monkeypatch, event_path: Path, failure: str) -> None:
    original_open = Path.open

    class FailureStream:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            self.stream.close()

        def write(self, value: str) -> int:
            if failure == "prewrite":
                raise OSError("seeded event prewrite failure")
            if failure == "partial":
                self.stream.write(value[: len(value) // 2])
                self.stream.flush()
                raise OSError("seeded event partial failure")
            return self.stream.write(value)

        def flush(self) -> None:
            self.stream.flush()

        def fileno(self) -> int:
            if failure == "postwrite":
                raise OSError("seeded event postwrite failure")
            return self.stream.fileno()

    def failure_open(path: Path, mode: str = "r", *args, **kwargs):
        stream = original_open(path, mode, *args, **kwargs)
        if path == event_path and mode == "a":
            return FailureStream(stream)
        return stream

    monkeypatch.setattr(Path, "open", failure_open)


class _FixedDateTime:
    @classmethod
    def now(cls, timezone):
        assert timezone is UTC
        return datetime(2026, 7, 28, 20, 0, tzinfo=UTC)
