from pathlib import Path

import pytest
from pydantic import ValidationError

from vandrel_foundry.config import FoundryConfig, load_lanes


def test_vandrel_writes_are_refused(config_data: dict) -> None:
    config_data["vandrel"]["write_enabled"] = True
    with pytest.raises(ValidationError, match="must be false"):
        FoundryConfig.model_validate(config_data)


def test_unknown_configuration_schema_is_refused(config_data: dict) -> None:
    config_data["schema_version"] = 2
    with pytest.raises(ValidationError):
        FoundryConfig.model_validate(config_data)


def test_packaged_and_checkout_lane_defaults_stay_in_sync() -> None:
    root = Path(__file__).parents[1]
    assert load_lanes(root / "lanes.toml") == load_lanes(
        root / "src" / "vandrel_foundry" / "data" / "lanes.toml"
    )
