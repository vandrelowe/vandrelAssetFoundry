from pathlib import Path

import pytest

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.lanes import LaneConfiguration


@pytest.fixture
def config_data(tmp_path: Path) -> dict:
    return {
        "schema_version": 1,
        "foundry": {
            "workspace_root": str(tmp_path / "workspace"),
            "asset_library_root": str(tmp_path / "library"),
            "default_provider": "meshy",
        },
        "vandrel": {
            "reference_repo_root": str(tmp_path / "vandrel"),
            "required_marker": "project.godot",
            "write_enabled": False,
        },
        "providers": {
            "meshy": {
                "api_base": "https://api.meshy.ai",
                "api_key_environment_variable": "MESHY_API_KEY",
            }
        },
        "release": {"default_dry_run": True, "allow_overwrite": False},
    }


@pytest.fixture
def config(config_data: dict) -> FoundryConfig:
    return FoundryConfig.model_validate(config_data)


@pytest.fixture
def lanes() -> LaneConfiguration:
    return LaneConfiguration.model_validate(
        {
            "lanes": {
                "static_prop": {
                    "wrapper_template": "static_prop",
                    "target_triangles": 2500,
                    "maximum_triangles": 5000,
                    "collision_policy": "manual",
                }
            }
        }
    )


@pytest.fixture
def humanoid_lanes() -> LaneConfiguration:
    return LaneConfiguration.model_validate(
        {
            "lanes": {
                "humanoid": {
                    "wrapper_template": "humanoid_candidate",
                    "collision_policy": "manual_review",
                    "requires_materials": True,
                    "requires_skeleton": True,
                    "release_enabled": True,
                }
            }
        }
    )


@pytest.fixture
def prompt(tmp_path: Path) -> Path:
    path = tmp_path / "prompt.txt"
    path.write_text("a rough stone knife", encoding="utf-8")
    return path


def write_config(path: Path, data: dict) -> None:
    foundry = data["foundry"]
    vandrel = data["vandrel"]
    meshy = data["providers"]["meshy"]
    release = data["release"]
    path.write_text(
        "\n".join(
            [
                "schema_version = 1",
                "[foundry]",
                f'workspace_root = "{Path(foundry["workspace_root"]).as_posix()}"',
                f'asset_library_root = "{Path(foundry["asset_library_root"]).as_posix()}"',
                f'default_provider = "{foundry["default_provider"]}"',
                "[vandrel]",
                f'reference_repo_root = "{Path(vandrel["reference_repo_root"]).as_posix()}"',
                f'required_marker = "{vandrel["required_marker"]}"',
                f"write_enabled = {str(vandrel['write_enabled']).lower()}",
                "[providers.meshy]",
                f'api_base = "{meshy["api_base"]}"',
                f'api_key_environment_variable = "{meshy["api_key_environment_variable"]}"',
                "[release]",
                f"default_dry_run = {str(release['default_dry_run']).lower()}",
                f"allow_overwrite = {str(release['allow_overwrite']).lower()}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
