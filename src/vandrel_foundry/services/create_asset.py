import os
import shutil
import tempfile
from pathlib import Path

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import AssetExistsError, FoundryError, UnknownLaneError
from vandrel_foundry.domain.ids import validate_asset_id
from vandrel_foundry.domain.lanes import LaneConfiguration
from vandrel_foundry.domain.manifest import AssetManifest
from vandrel_foundry.services.windows_acl_policy import apply_candidate_acl
from vandrel_foundry.storage.manifests import ManifestRepository

ASSET_DIRECTORIES = (
    "input/references",
    "provider",
    "source",
    "processed",
    "preview",
    "reports",
    "godot_staging",
    "release_staging",
)


def create_asset(
    config: FoundryConfig,
    lanes: LaneConfiguration,
    asset_id: str,
    lane: str,
    display_name: str,
    prompt_file: Path,
) -> AssetManifest:
    validate_asset_id(asset_id)
    if lane not in lanes.lanes:
        raise UnknownLaneError(f"Unknown lane: {lane}")
    if not display_name.strip():
        raise FoundryError("Display name must not be empty.")
    if not prompt_file.is_file():
        raise FoundryError(f"Prompt file does not exist: {prompt_file}")

    assets_root = config.foundry.workspace_root / "assets"
    destination = assets_root / asset_id
    if destination.exists():
        raise AssetExistsError(f"Asset already exists: {asset_id}")
    assets_root.mkdir(parents=True, exist_ok=True)

    temporary = Path(tempfile.mkdtemp(prefix=f".{asset_id}-", dir=assets_root))
    try:
        for relative in ASSET_DIRECTORIES:
            (temporary / relative).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(prompt_file, temporary / "input" / "prompt.txt")
        try:
            os.rename(temporary, destination)
        except FileExistsError as exc:
            raise AssetExistsError(f"Asset already exists: {asset_id}") from exc
        apply_candidate_acl(config, destination)
        manifest = AssetManifest.initial(
            asset_id,
            display_name.strip(),
            lane,
            config.foundry.default_provider,
        )
        ManifestRepository(config.foundry.workspace_root).save(manifest, "asset.created")
        return manifest
    except BaseException as exc:
        if temporary.exists():
            shutil.rmtree(temporary)
        if destination.exists() and not (destination / "manifest.json").exists():
            shutil.rmtree(destination)
        if isinstance(exc, OSError):
            raise FoundryError(f"Could not create asset {asset_id}: {exc}") from exc
        raise
