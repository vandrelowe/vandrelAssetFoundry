import os
import shutil
from dataclasses import replace
from pathlib import Path

from pydantic import ValidationError

from vandrel_foundry.domain.errors import AssetNotFoundError, FoundryError
from vandrel_foundry.domain.manifest import AssetManifest
from vandrel_foundry.storage.atomic import json_bytes, write_bytes_temp
from vandrel_foundry.storage.events import append_event_bytes, build_event_bytes
from vandrel_foundry.storage.locks import AssetLock, LockFactory
from vandrel_foundry.storage.save_journal import (
    JOURNAL_NAME,
    SaveDiagnosis,
    _reconcile_pending_save_locked,
    create_pending_save,
    diagnose_pending_save,
    write_journal,
)


class ManifestRepository:
    def __init__(
        self,
        workspace_root: Path,
        lock_factory: LockFactory = AssetLock,
    ) -> None:
        self.workspace_root = workspace_root
        self.lock_factory = lock_factory

    def asset_directory(self, asset_id: str) -> Path:
        return self.workspace_root / "assets" / asset_id

    def load(self, asset_id: str) -> AssetManifest:
        path = self.asset_directory(asset_id) / "manifest.json"
        try:
            return AssetManifest.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise AssetNotFoundError(f"Asset not found: {asset_id}") from exc
        except (OSError, ValidationError) as exc:
            raise FoundryError(f"Invalid manifest for {asset_id}: {exc}") from exc

    def diagnose_pending_save(self, asset_id: str) -> SaveDiagnosis:
        directory = self.asset_directory(asset_id)
        if not directory.is_dir():
            raise AssetNotFoundError(f"Asset directory not found: {asset_id}")
        return diagnose_pending_save(directory, asset_id)

    def reconcile_pending_save(self, asset_id: str) -> SaveDiagnosis:
        directory = self.asset_directory(asset_id)
        if not directory.is_dir():
            raise AssetNotFoundError(f"Asset directory not found: {asset_id}")
        lock_path = self.workspace_root / "locks" / f"{asset_id}.lock"
        try:
            with self.lock_factory(lock_path):
                return _reconcile_pending_save_locked(directory, asset_id)
        except OSError as exc:
            raise FoundryError(
                f"Could not reconcile pending manifest save for {asset_id}: {exc}"
            ) from exc

    def save(
        self,
        manifest: AssetManifest,
        event_type: str = "manifest.updated",
        expected_revision: int | None = None,
    ) -> None:
        asset_id = manifest.asset.asset_id
        directory = self.asset_directory(asset_id)
        if not directory.is_dir():
            raise AssetNotFoundError(f"Asset directory not found: {asset_id}")
        lock_path = self.workspace_root / "locks" / f"{asset_id}.lock"
        try:
            with self.lock_factory(lock_path):
                _reconcile_pending_save_locked(directory, asset_id)
                validated = AssetManifest.model_validate(manifest.model_dump(mode="python"))
                destination = directory / "manifest.json"
                source_bytes: bytes | None = None
                source_revision: int | None = None
                if destination.exists():
                    try:
                        source_bytes = destination.read_bytes()
                        current = AssetManifest.model_validate_json(source_bytes)
                        source_revision = current.revision
                    except (OSError, ValidationError) as exc:
                        raise FoundryError(
                            f"Could not verify current manifest for {asset_id}: {exc}"
                        ) from exc
                if expected_revision is not None:
                    if source_revision is None:
                        raise FoundryError(f"Manifest disappeared while saving {asset_id}")
                    if source_revision != expected_revision:
                        raise FoundryError(
                            f"Manifest revision conflict for {asset_id}: expected "
                            f"{expected_revision}, found {source_revision}"
                        )
                previous = directory / "manifest.previous.json"
                target_bytes = json_bytes(validated.model_dump(mode="json"))
                event_bytes = build_event_bytes(event_type, asset_id, validated.revision)
                event_path = directory / "events.jsonl"
                try:
                    existing_events = event_path.read_bytes()
                except FileNotFoundError:
                    existing_events = b""
                pending = create_pending_save(
                    asset_id=asset_id,
                    source_revision=source_revision,
                    target_revision=validated.revision,
                    source_manifest_bytes=source_bytes,
                    target_manifest_bytes=target_bytes,
                    event_log_bytes=existing_events,
                    event_type=event_type,
                    event_bytes=event_bytes,
                )
                write_journal(directory / JOURNAL_NAME, pending)
                temporary = write_bytes_temp(directory, target_bytes)
                try:
                    if destination.exists():
                        shutil.copy2(destination, previous)
                    os.replace(temporary, destination)
                    append_event_bytes(event_path, event_bytes)
                    write_journal(directory / JOURNAL_NAME, replace(pending, state="complete"))
                finally:
                    temporary.unlink(missing_ok=True)
        except OSError as exc:
            raise FoundryError(f"Could not save manifest for {asset_id}: {exc}") from exc
