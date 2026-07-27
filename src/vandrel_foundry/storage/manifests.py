import os
import shutil
from pathlib import Path

from pydantic import ValidationError

from vandrel_foundry.domain.errors import AssetNotFoundError, FoundryError
from vandrel_foundry.domain.manifest import AssetManifest
from vandrel_foundry.storage.atomic import write_json_temp
from vandrel_foundry.storage.events import append_event
from vandrel_foundry.storage.locks import AssetLock, LockFactory


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
                validated = AssetManifest.model_validate(manifest.model_dump(mode="python"))
                destination = directory / "manifest.json"
                if expected_revision is not None:
                    try:
                        current = AssetManifest.model_validate_json(
                            destination.read_text(encoding="utf-8")
                        )
                    except FileNotFoundError as exc:
                        raise FoundryError(f"Manifest disappeared while saving {asset_id}") from exc
                    except (OSError, ValidationError) as exc:
                        raise FoundryError(
                            f"Could not verify current revision for {asset_id}: {exc}"
                        ) from exc
                    if current.revision != expected_revision:
                        raise FoundryError(
                            f"Manifest revision conflict for {asset_id}: expected "
                            f"{expected_revision}, found {current.revision}"
                        )
                previous = directory / "manifest.previous.json"
                temporary = write_json_temp(
                    directory,
                    validated.model_dump(mode="json"),
                )
                try:
                    if destination.exists():
                        shutil.copy2(destination, previous)
                    os.replace(temporary, destination)
                    append_event(
                        directory / "events.jsonl",
                        event_type,
                        asset_id,
                        validated.revision,
                    )
                finally:
                    temporary.unlink(missing_ok=True)
        except OSError as exc:
            raise FoundryError(f"Could not save manifest for {asset_id}: {exc}") from exc
