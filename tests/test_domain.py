import pytest
from pydantic import BaseModel, ValidationError

from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.ids import validate_asset_id
from vandrel_foundry.domain.manifest import Artifact
from vandrel_foundry.storage.paths import RelativeManifestPath


@pytest.mark.parametrize("value", ["abc", "stone_knife_001", "1_x"])
def test_valid_asset_ids(value: str) -> None:
    assert validate_asset_id(value) == value


@pytest.mark.parametrize("value", ["ab", "_abc", "Upper", "has-dash", "a" * 65])
def test_invalid_asset_ids(value: str) -> None:
    with pytest.raises(FoundryError):
        validate_asset_id(value)


class PathHolder(BaseModel):
    path: RelativeManifestPath


@pytest.mark.parametrize("value", ["input/prompt.txt", "preview/image.png"])
def test_relative_manifest_paths(value: str) -> None:
    assert PathHolder(path=value).path == value


@pytest.mark.parametrize("value", ["../escape", "input/../escape", "/absolute", "C:/drive", r"a\b"])
def test_manifest_path_traversal_rejected(value: str) -> None:
    with pytest.raises(ValidationError):
        PathHolder(path=value)


def test_artifact_path_is_validated() -> None:
    with pytest.raises(ValidationError):
        Artifact(
            artifact_id="processed_glb_001",
            role="processed_model",
            stage="processed",
            format="glb",
            path="../model.glb",
            sha256="a" * 64,
            size_bytes=1,
        )
