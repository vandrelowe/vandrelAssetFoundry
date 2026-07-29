import json
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType

import pytest

from vandrel_foundry.domain.errors import AssetExistsError, FoundryError, UnknownLaneError
from vandrel_foundry.services.audit_asset import audit_asset
from vandrel_foundry.services.create_asset import ASSET_DIRECTORIES, create_asset
from vandrel_foundry.services.doctor import run_doctor
from vandrel_foundry.services.inspect_assets import initialize_workspace
from vandrel_foundry.storage import events as event_storage
from vandrel_foundry.storage import manifests as manifest_storage
from vandrel_foundry.storage.manifests import ManifestRepository


def test_create_asset_layout_prompt_manifest_and_event(config, lanes, prompt: Path) -> None:
    initialize_workspace(config.foundry.workspace_root)
    manifest = create_asset(config, lanes, "stone_knife_001", "static_prop", "Stone Knife", prompt)
    root = config.foundry.workspace_root / "assets" / "stone_knife_001"
    assert manifest.workflow.state.value == "draft"
    assert all((root / relative).is_dir() for relative in ASSET_DIRECTORIES)
    assert (root / "input/prompt.txt").read_text(encoding="utf-8") == "a rough stone knife"
    assert json.loads((root / "manifest.json").read_text(encoding="utf-8"))["schema_version"] == 2
    event = json.loads((root / "events.jsonl").read_text(encoding="utf-8"))
    assert event["event"] == "asset.created"


def test_duplicate_rejected(config, lanes, prompt: Path) -> None:
    initialize_workspace(config.foundry.workspace_root)
    create_asset(config, lanes, "stone_knife_001", "static_prop", "Stone Knife", prompt)
    with pytest.raises(AssetExistsError):
        create_asset(config, lanes, "stone_knife_001", "static_prop", "Again", prompt)


@pytest.mark.parametrize("case", ["unknown_lane", "missing_prompt", "invalid_id"])
def test_validation_failure_leaves_no_partial_directory(
    config, lanes, prompt: Path, case: str
) -> None:
    initialize_workspace(config.foundry.workspace_root)
    asset_id = "valid_asset"
    lane = "static_prop"
    source = prompt
    expected = FoundryError
    if case == "unknown_lane":
        lane = "missing"
        expected = UnknownLaneError
    elif case == "missing_prompt":
        source = prompt.parent / "missing.txt"
    else:
        asset_id = "NO"
    with pytest.raises(expected):
        create_asset(config, lanes, asset_id, lane, "Name", source)
    assert list((config.foundry.workspace_root / "assets").iterdir()) == []


def test_atomic_update_preserves_previous_and_appends_event(config, lanes, prompt: Path) -> None:
    initialize_workspace(config.foundry.workspace_root)
    manifest = create_asset(config, lanes, "stone_knife_001", "static_prop", "Stone Knife", prompt)
    manifest.revision = 2
    manifest.notes = "changed"
    repository = ManifestRepository(config.foundry.workspace_root)
    repository.save(manifest)
    root = repository.asset_directory("stone_knife_001")
    previous = json.loads((root / "manifest.previous.json").read_text(encoding="utf-8"))
    current = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert previous["revision"] == 1
    assert current["revision"] == 2
    assert len((root / "events.jsonl").read_text(encoding="utf-8").splitlines()) == 2


def test_revision_check_prevents_stale_manifest_overwrite(config, lanes, prompt: Path) -> None:
    initialize_workspace(config.foundry.workspace_root)
    create_asset(config, lanes, "stone_knife_001", "static_prop", "Stone Knife", prompt)
    repository = ManifestRepository(config.foundry.workspace_root)
    first = repository.load("stone_knife_001")
    stale = repository.load("stone_knife_001")
    first.revision += 1
    first.notes = "first writer"
    repository.save(first, expected_revision=1)
    stale.revision += 1
    stale.notes = "stale writer"

    with pytest.raises(FoundryError, match="revision conflict"):
        repository.save(stale, expected_revision=1)

    assert repository.load("stone_knife_001").notes == "first writer"


def test_manifest_repository_uses_injected_lock_factory(config, lanes, prompt: Path) -> None:
    initialize_workspace(config.foundry.workspace_root)
    manifest = create_asset(config, lanes, "stone_knife_001", "static_prop", "Stone Knife", prompt)
    observed_paths: list[Path] = []

    class RecordingLock:
        def __enter__(self):
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            return None

    def lock_factory(path: Path) -> RecordingLock:
        observed_paths.append(path)
        return RecordingLock()

    manifest.revision = 2
    ManifestRepository(config.foundry.workspace_root, lock_factory).save(manifest)
    assert observed_paths == [config.foundry.workspace_root / "locks" / "stone_knife_001.lock"]


def test_init_is_idempotent_and_preserves_files(config) -> None:
    initialize_workspace(config.foundry.workspace_root)
    marker = config.foundry.workspace_root / "cache" / "user-file"
    marker.write_text("keep", encoding="utf-8")
    initialize_workspace(config.foundry.workspace_root)
    assert marker.read_text(encoding="utf-8") == "keep"


def test_doctor_does_not_initialize_missing_workspace(config, lanes) -> None:
    assert not config.foundry.workspace_root.exists()
    run_doctor(config, lanes)
    assert not config.foundry.workspace_root.exists()


def test_manifest_save_previous_copy_failure_preserves_all_durable_state(
    config,
    lanes,
    prompt: Path,
    monkeypatch,
) -> None:
    repository, update, root, before = _prepared_manifest_update(config, lanes, prompt)

    def fail_copy(_source: Path, _destination: Path) -> None:
        raise OSError("seeded previous-copy failure")

    monkeypatch.setattr(manifest_storage.shutil, "copy2", fail_copy)

    with pytest.raises(FoundryError) as raised:
        repository.save(update, "test.update", expected_revision=2)

    assert str(raised.value) == (
        "Could not save manifest for durability_asset_001: seeded previous-copy failure"
    )
    assert isinstance(raised.value.__cause__, OSError)
    assert str(raised.value.__cause__) == "seeded previous-copy failure"
    assert _durable_manifest_state(root) == before
    assert repository.load("durability_asset_001").revision == 2
    assert not list(root.glob(".manifest-*.tmp"))


def test_manifest_save_atomic_replace_failure_advances_only_recovery_copy(
    config,
    lanes,
    prompt: Path,
    monkeypatch,
) -> None:
    repository, update, root, before = _prepared_manifest_update(config, lanes, prompt)

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("seeded manifest-replace failure")

    monkeypatch.setattr(manifest_storage.os, "replace", fail_replace)

    with pytest.raises(FoundryError) as raised:
        repository.save(update, "test.update", expected_revision=2)

    assert str(raised.value) == (
        "Could not save manifest for durability_asset_001: seeded manifest-replace failure"
    )
    assert isinstance(raised.value.__cause__, OSError)
    assert str(raised.value.__cause__) == "seeded manifest-replace failure"
    after = _durable_manifest_state(root)
    assert after["manifest"] == before["manifest"]
    assert after["previous"] == before["manifest"]
    assert after["events"] == before["events"]
    assert repository.load("durability_asset_001").revision == 2
    assert not list(root.glob(".manifest-*.tmp"))


def test_manifest_save_event_prewrite_failure_exposes_exact_post_replace_split(
    config,
    lanes,
    prompt: Path,
    monkeypatch,
) -> None:
    repository, update, root, before = _prepared_manifest_update(config, lanes, prompt)

    expected_manifest = _canonical_manifest_bytes(update)
    event_path = root / "events.jsonl"
    original_open = Path.open

    def fail_event_open(path: Path, mode: str = "r", *args, **kwargs):
        if path == event_path and mode == "a":
            raise OSError("seeded event-prewrite failure")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_event_open)

    with pytest.raises(FoundryError) as raised:
        repository.save(update, "test.update", expected_revision=2)

    assert str(raised.value) == (
        "Could not save manifest for durability_asset_001: seeded event-prewrite failure"
    )
    assert isinstance(raised.value.__cause__, OSError)
    assert str(raised.value.__cause__) == "seeded event-prewrite failure"
    after = _durable_manifest_state(root)
    assert after["manifest"] == expected_manifest
    assert after["previous"] == before["manifest"]
    assert after["events"] == before["events"]
    assert repository.load("durability_asset_001").revision == 3
    event_check = next(
        check
        for check in audit_asset(config, "durability_asset_001").manifest_checks
        if check["name"] == "event_history"
    )
    assert not event_check["passed"]
    assert event_check["observed_revisions"] == [1, 2]
    assert event_check["expected_revisions"] == [1, 2, 3]
    assert not list(root.glob(".manifest-*.tmp"))


def test_manifest_save_event_partial_write_failure_retains_exact_invalid_tail(
    config,
    lanes,
    prompt: Path,
    monkeypatch,
) -> None:
    repository, update, root, before = _prepared_manifest_update(config, lanes, prompt)
    expected_manifest = _canonical_manifest_bytes(update)
    event_path = root / "events.jsonl"
    event_line = _expected_event_line()
    partial = event_line[: len(event_line) // 2]
    original_open = Path.open

    class PartialWriteStream:
        def __init__(self, stream) -> None:
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback) -> None:
            self.stream.close()

        def write(self, value: str) -> int:
            assert value == event_line.decode("utf-8")
            self.stream.write(partial.decode("utf-8"))
            self.stream.flush()
            raise OSError("seeded event-partial-write failure")

    def partial_event_open(path: Path, mode: str = "r", *args, **kwargs):
        stream = original_open(path, mode, *args, **kwargs)
        if path == event_path and mode == "a":
            return PartialWriteStream(stream)
        return stream

    monkeypatch.setattr(event_storage, "datetime", _FixedDateTime)
    monkeypatch.setattr(Path, "open", partial_event_open)

    with pytest.raises(FoundryError) as raised:
        repository.save(update, "test.update", expected_revision=2)

    assert str(raised.value) == (
        "Could not save manifest for durability_asset_001: "
        "seeded event-partial-write failure"
    )
    assert isinstance(raised.value.__cause__, OSError)
    assert str(raised.value.__cause__) == "seeded event-partial-write failure"
    after = _durable_manifest_state(root)
    assert after["manifest"] == expected_manifest
    assert after["previous"] == before["manifest"]
    assert after["events"] == before["events"] + partial
    assert repository.load("durability_asset_001").revision == 3
    event_check = next(
        check
        for check in audit_asset(config, "durability_asset_001").manifest_checks
        if check["name"] == "event_history"
    )
    assert not event_check["passed"]
    assert "unreadable or invalid" in str(event_check["detail"])
    assert not list(root.glob(".manifest-*.tmp"))


def test_manifest_save_event_postwrite_failure_has_complete_event_but_raises(
    config,
    lanes,
    prompt: Path,
    monkeypatch,
) -> None:
    repository, update, root, before = _prepared_manifest_update(config, lanes, prompt)
    expected_manifest = _canonical_manifest_bytes(update)
    event_path = root / "events.jsonl"
    event_line = _expected_event_line()
    original_open = Path.open

    class FsyncFailureStream:
        def __init__(self, stream) -> None:
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback) -> None:
            self.stream.close()

        def write(self, value: str) -> int:
            return self.stream.write(value)

        def flush(self) -> None:
            self.stream.flush()

        def fileno(self) -> int:
            raise OSError("seeded event-postwrite-fsync failure")

    def fsync_failure_open(path: Path, mode: str = "r", *args, **kwargs):
        stream = original_open(path, mode, *args, **kwargs)
        if path == event_path and mode == "a":
            return FsyncFailureStream(stream)
        return stream

    monkeypatch.setattr(event_storage, "datetime", _FixedDateTime)
    monkeypatch.setattr(Path, "open", fsync_failure_open)

    with pytest.raises(FoundryError) as raised:
        repository.save(update, "test.update", expected_revision=2)

    assert str(raised.value) == (
        "Could not save manifest for durability_asset_001: "
        "seeded event-postwrite-fsync failure"
    )
    assert isinstance(raised.value.__cause__, OSError)
    assert str(raised.value.__cause__) == "seeded event-postwrite-fsync failure"
    after = _durable_manifest_state(root)
    assert after["manifest"] == expected_manifest
    assert after["previous"] == before["manifest"]
    assert after["events"] == before["events"] + event_line
    assert repository.load("durability_asset_001").revision == 3
    event_check = next(
        check
        for check in audit_asset(config, "durability_asset_001").manifest_checks
        if check["name"] == "event_history"
    )
    assert event_check["passed"]
    assert event_check["observed_revisions"] == [1, 2, 3]
    assert not list(root.glob(".manifest-*.tmp"))


def _prepared_manifest_update(config, lanes, prompt: Path):
    initialize_workspace(config.foundry.workspace_root)
    manifest = create_asset(
        config,
        lanes,
        "durability_asset_001",
        "static_prop",
        "Durability Asset",
        prompt,
    )
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest.revision = 2
    manifest.notes = "committed revision two"
    repository.save(manifest, "test.baseline", expected_revision=1)
    root = repository.asset_directory("durability_asset_001")
    before = _durable_manifest_state(root)
    update = repository.load("durability_asset_001")
    update.revision = 3
    update.notes = "attempted revision three"
    return repository, update, root, before


def _durable_manifest_state(root: Path) -> dict[str, bytes]:
    return {
        "manifest": (root / "manifest.json").read_bytes(),
        "previous": (root / "manifest.previous.json").read_bytes(),
        "events": (root / "events.jsonl").read_bytes(),
    }


def _canonical_manifest_bytes(manifest) -> bytes:
    return (
        json.dumps(manifest.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
    ).encode()


def _expected_event_line() -> bytes:
    return (
        json.dumps(
            {
                "timestamp": "2026-07-28T20:00:00Z",
                "event": "test.update",
                "asset_id": "durability_asset_001",
                "revision": 3,
            },
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


class _FixedDateTime:
    @classmethod
    def now(cls, timezone):
        assert timezone is UTC
        return datetime(2026, 7, 28, 20, 0, tzinfo=UTC)
