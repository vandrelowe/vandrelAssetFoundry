import json
from pathlib import Path
from types import TracebackType

import pytest

from vandrel_foundry.domain.errors import AssetExistsError, FoundryError, UnknownLaneError
from vandrel_foundry.services.create_asset import ASSET_DIRECTORIES, create_asset
from vandrel_foundry.services.doctor import run_doctor
from vandrel_foundry.services.inspect_assets import initialize_workspace
from vandrel_foundry.storage.manifests import ManifestRepository


def test_create_asset_layout_prompt_manifest_and_event(config, lanes, prompt: Path) -> None:
    initialize_workspace(config.foundry.workspace_root)
    manifest = create_asset(config, lanes, "stone_knife_001", "static_prop", "Stone Knife", prompt)
    root = config.foundry.workspace_root / "assets" / "stone_knife_001"
    assert manifest.workflow.state.value == "draft"
    assert all((root / relative).is_dir() for relative in ASSET_DIRECTORIES)
    assert (root / "input/prompt.txt").read_text(encoding="utf-8") == "a rough stone knife"
    assert json.loads((root / "manifest.json").read_text(encoding="utf-8"))["schema_version"] == 1
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
