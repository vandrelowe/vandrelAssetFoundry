from pathlib import Path

from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import AssetManifest


def discover_assets(workspace_root: Path) -> tuple[list[AssetManifest], list[str]]:
    assets: list[AssetManifest] = []
    warnings: list[str] = []
    root = workspace_root / "assets"
    if not root.exists():
        return assets, warnings
    try:
        directories = sorted(path for path in root.iterdir() if path.is_dir())
    except OSError as exc:
        raise FoundryError(f"Could not inspect assets in {root}: {exc}") from exc
    for directory in directories:
        manifest_path = directory / "manifest.json"
        try:
            manifest = AssetManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
            if manifest.asset.asset_id != directory.name:
                raise ValueError("directory name does not match asset ID")
            assets.append(manifest)
        except (OSError, ValueError) as exc:
            warnings.append(f"{directory.name}: {exc}")
    return assets, warnings


def initialize_workspace(workspace_root: Path) -> None:
    if workspace_root.exists() and not workspace_root.is_dir():
        raise FoundryError(f"Workspace root is not a directory: {workspace_root}")
    try:
        for name in ("assets", "temp", "cache", "locks", "backups"):
            path = workspace_root / name
            if path.exists() and not path.is_dir():
                raise FoundryError(f"Workspace path is not a directory: {path}")
            path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise FoundryError(f"Could not initialize workspace {workspace_root}: {exc}") from exc
