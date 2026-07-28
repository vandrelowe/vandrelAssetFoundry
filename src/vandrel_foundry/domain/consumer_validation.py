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
    model_sha256: str = Field(pattern=r"^[A-Fa-f0-9]{64}$")


class ConsumerAssetEvidence(ConsumerEvidenceModel):
    character_id: str = Field(min_length=1)
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
    foundry_ingestion_policy: str | None = None
    assets: dict[str, ConsumerAssetEvidence]
