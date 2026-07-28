from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BatchModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


BatchStage = Literal[
    "create",
    "add-source",
    "process",
    "inspect",
    "prepare-godot",
    "validate-godot",
    "render-preview",
    "render-multi-angle-preview",
    "audit",
]


class BatchCandidate(BatchModel):
    asset_id: str
    lane: str
    display_name: str | None = None
    prompt_file: Path | None = None
    source: Path | None = None
    stages: list[BatchStage] = Field(min_length=1)

    @model_validator(mode="after")
    def source_required_for_intake(self) -> "BatchCandidate":
        if "create" in self.stages and (self.display_name is None or self.prompt_file is None):
            raise ValueError("display_name and prompt_file are required when create is requested")
        if "add-source" in self.stages and self.source is None:
            raise ValueError("source is required when add-source is requested")
        if len(self.stages) != len(set(self.stages)):
            raise ValueError("candidate stages must be unique")
        return self


class BatchPlan(BatchModel):
    schema_version: Literal[1]
    failure_policy: Literal["continue", "stop"] = "continue"
    rerun_policy: Literal["resume", "fail"] = "resume"
    candidates: list[BatchCandidate] = Field(min_length=1)

    @model_validator(mode="after")
    def candidate_ids_are_unique(self) -> "BatchPlan":
        ids = [candidate.asset_id for candidate in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate asset IDs must be unique")
        return self


class ForegroundCoverage(BatchModel):
    artifact_id: str
    path: str
    width: int
    height: int
    bounding_box_fraction: float
    nonzero_alpha_pixel_fraction: float
    excessive_empty_canvas: bool


class BatchStageRecord(BatchModel):
    candidate: str
    stage: BatchStage
    started_at: datetime
    ended_at: datetime
    duration_seconds: float = Field(ge=0)
    result: Literal["completed", "skipped", "failed"]
    error_category: str | None = None
    detail: str | None = None
    manifest_revision_before: int | None
    manifest_revision_after: int | None
    artifact_count_delta: int
    artifact_bytes_delta: int
    operator_required_next_action: list[str]
    foreground_coverage: list[ForegroundCoverage] = Field(default_factory=list)


class BatchLedger(BatchModel):
    schema_version: Literal[1] = 1
    plan_schema_version: int
    started_at: datetime
    ended_at: datetime
    failure_policy: str
    rerun_policy: str
    records: list[BatchStageRecord]
    planned_candidates: int
    completed_candidates: int
    failed_candidates: int
    not_run_candidates: list[str]
