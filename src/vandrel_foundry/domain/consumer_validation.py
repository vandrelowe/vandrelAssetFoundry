from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ConsumerEvidenceModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class ConsumerFinding(ConsumerEvidenceModel):
    code: str = Field(min_length=1)
    severity: Literal["info", "warning", "error", "blocker"] | None = None
    detail: str = Field(min_length=1)
    owner: Literal["asset_foundry", "vandrel", "unknown"] | None = None


class FoundryBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(min_length=1)
    release_revision: str | None = Field(default=None, min_length=1)
    manifest_revision: int | None = Field(default=None, ge=1)
    model_artifact_id: str | None = Field(default=None, min_length=1)
    model_sha256: str = Field(pattern=r"^[A-Fa-f0-9]{64}$")
    walk_artifact_id: str | None = Field(default=None, min_length=1)
    walk_sha256: str | None = Field(default=None, pattern=r"^[A-Fa-f0-9]{64}$")
    run_artifact_id: str | None = Field(default=None, min_length=1)
    run_sha256: str | None = Field(default=None, pattern=r"^[A-Fa-f0-9]{64}$")
    provider_task_key: str | None = Field(default=None, min_length=1)
    provider_task_id: str | None = Field(default=None, min_length=1)
    matching_library_revision: str | None = Field(default=None, min_length=1)


class ConsumerAssetEvidence(ConsumerEvidenceModel):
    character_id: str = Field(min_length=1)
    affected_character_ids: list[str] = Field(default_factory=list)
    consumer_scene_path: str = Field(min_length=1)
    status: Literal["pass", "fail", "blocked", "in_progress", "not_tested"]
    generic_asset_defects: list[ConsumerFinding]
    vandrel_runtime_corrections: list[ConsumerFinding]
    evidence: dict[str, Any]
    foundry_binding: FoundryBinding | None = None


class VandrelCharacterAcceptanceLedger(ConsumerEvidenceModel):
    schema_version: Literal["1.0"]
    consumer: Literal["vandrel"]
    generated_utc: datetime | None = None
    foundry_ingestion_policy: (
        Literal[
            "generic defects are promotion-affecting only when "
            "foundry_binding.model_sha256 exactly matches the candidate; "
            "unbound legacy evidence is diagnostic-only"
        ]
        | None
    ) = None
    assets: dict[str, ConsumerAssetEvidence]


class CharacterGroundAuditEntry(ConsumerEvidenceModel):
    character_id: str = Field(min_length=1)
    scene_path: str = Field(min_length=1)
    scale: float
    current_base_offset_y: float
    sampled_animation_count: int = Field(ge=0)
    residual_min_y_m: float
    residual_max_y_m: float
    within_tolerance: int = Field(ge=0)
    recommended_base_offset_y: float
    review_directory: str = Field(min_length=1)


class CharacterGroundAudit(ConsumerEvidenceModel):
    schema_version: Literal["1.0"]
    tolerance_m: float = Field(ge=0)
    characters: list[CharacterGroundAuditEntry]
