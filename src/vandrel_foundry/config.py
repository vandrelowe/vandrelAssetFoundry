import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from vandrel_foundry.domain.errors import ConfigurationError
from vandrel_foundry.domain.lanes import LaneConfiguration


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FoundrySettings(ConfigModel):
    workspace_root: Path
    asset_library_root: Path
    default_provider: str


class VandrelSettings(ConfigModel):
    reference_repo_root: Path
    required_marker: str
    write_enabled: bool = False


class MeshySettings(ConfigModel):
    model_config = ConfigDict(extra="allow")
    api_base: str
    api_key_environment_variable: str = Field(min_length=1)
    request_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    poll_interval_seconds: float = Field(default=10.0, gt=0, le=300)
    maximum_download_bytes: int = Field(default=4_000_000_000, gt=0)


class Providers(ConfigModel):
    meshy: MeshySettings


class ReleaseSettings(ConfigModel):
    model_config = ConfigDict(extra="allow")
    default_dry_run: bool = True
    allow_overwrite: bool = False


class ToolSettings(ConfigModel):
    godot_executable: Path | None = None
    blender_executable: Path | None = None
    godot_timeout_seconds: float = Field(default=120.0, gt=0, le=900)
    blender_timeout_seconds: float = Field(default=300.0, gt=0, le=1800)
    maximum_output_bytes: int = Field(default=1_000_000, gt=0, le=50_000_000)


class FoundryConfig(ConfigModel):
    schema_version: Literal[1]
    foundry: FoundrySettings
    vandrel: VandrelSettings
    providers: Providers
    release: ReleaseSettings
    tools: ToolSettings = Field(default_factory=ToolSettings)

    @model_validator(mode="after")
    def phase_one_safety(self) -> "FoundryConfig":
        if self.vandrel.write_enabled:
            raise ValueError("vandrel.write_enabled must be false in Phase 1")
        return self


def default_config_path() -> Path:
    configured = os.environ.get("VANDREL_FOUNDRY_CONFIG")
    return Path(configured) if configured else Path.cwd() / "foundry.toml"


def load_config(path: Path | None = None) -> FoundryConfig:
    config_path = path or default_config_path()
    try:
        with config_path.open("rb") as stream:
            return FoundryConfig.model_validate(tomllib.load(stream))
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as exc:
        raise ConfigurationError(f"Could not load configuration {config_path}: {exc}") from exc


def load_lanes(path: Path | None = None) -> LaneConfiguration:
    lanes_path = path or _default_lanes_path()
    try:
        with lanes_path.open("rb") as stream:
            return LaneConfiguration.model_validate(tomllib.load(stream))
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as exc:
        raise ConfigurationError(f"Could not load lane configuration {lanes_path}: {exc}") from exc


def _default_lanes_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "lanes.toml"
