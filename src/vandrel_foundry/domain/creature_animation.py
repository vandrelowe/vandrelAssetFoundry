import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from vandrel_foundry.storage.paths import RelativeManifestPath


class CreatureAnimationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreatureClipEvidence(CreatureAnimationModel):
    semantic: Literal["idle", "walk", "run"]
    member_path: RelativeManifestPath
    animation_name: str = Field(min_length=1)
    duration_seconds: float = Field(gt=0)
    joint_count: int = Field(gt=0)

    @field_validator("duration_seconds")
    @classmethod
    def finite_duration(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("Clip duration must be finite.")
        return value


class CreatureAnimationProfile(CreatureAnimationModel):
    schema_version: Literal["vandrel_foundry_creature_animation_profile/1.0"]
    archive_name: str = Field(min_length=1)
    archive_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    creature_family: str = Field(pattern=r"^[a-z0-9][a-z0-9_]{1,63}$")
    animation_provider: str = Field(pattern=r"^[a-z0-9][a-z0-9_]{1,63}$")
    rig_family: str = Field(pattern=r"^[a-z0-9][a-z0-9_]{1,63}$")
    base_member_path: RelativeManifestPath
    base_joint_count: int = Field(gt=0)
    animated_joint_count: int = Field(gt=0)
    shared_joint_names: list[str] = Field(min_length=1)
    base_extra_joint_names: list[str]
    clips: list[CreatureClipEvidence] = Field(min_length=3, max_length=3)
    animated_names_match: bool
    animated_hierarchy_matches: bool
    animated_rest_transforms_match: bool
    base_contains_animated_rig: bool
    base_shared_hierarchy_matches: bool
    base_shared_rest_transforms_match: bool
    coherent_animation_set: bool
    direct_original_rig_transfer_compatible: bool
    classification_authority: Literal["foundry_technical_suggestion_only"]
