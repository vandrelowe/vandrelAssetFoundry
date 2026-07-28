from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class FitnessModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArtifactIdentity(FitnessModel):
    artifact_id: str
    sha256: str


class IntegrityView(FitnessModel):
    status: Literal["passing", "failed"]
    artifact_checks: int
    failed_checks: list[str]


class TechnicalCheckView(FitnessModel):
    name: str
    status: Literal["passing", "failed", "unknown"]
    binding_status: Literal["exact", "stale", "unbound", "not_applicable"]
    bound_hashes: dict[str, str] = Field(default_factory=dict)
    detail: dict[str, Any] = Field(default_factory=dict)


class ApprovalView(FitnessModel):
    status: Literal["approved", "unapproved", "rejected"]
    binding_status: Literal["exact", "stale", "unbound"]
    matches_current_artifact_set: bool | None
    reviewer: str | None
    approved_at: str | None
    bound_hashes: dict[str, str]


class LibraryRevisionView(FitnessModel):
    revision: int
    descriptor_sha256: str
    integrity_status: Literal["passing", "failed", "unknown"]


class LibraryView(FitnessModel):
    status: Literal["absent", "historical_only", "current_set", "mismatched", "unknown"]
    latest_revision: LibraryRevisionView | None
    matches_current_approved_set: bool | None
    historical_releases: list[LibraryRevisionView]


class ConsumerResultView(FitnessModel):
    consumer_status: str
    acceptance_status: Literal["passing", "rejected", "blocked", "not_tested"]
    report_artifact_id: str
    report_sha256: str
    bound_model_sha256: str


class ConsumerView(FitnessModel):
    evidence_status: Literal["absent", "exact", "stale", "unbound"]
    consumer_status: str | None
    acceptance_status: Literal["passing", "rejected", "blocked", "not_tested", "unknown"]
    report_artifact_id: str | None
    report_sha256: str | None
    bound_model_sha256: str | None
    latest_exact_current_result: ConsumerResultView | None


class EligibilityView(FitnessModel):
    eligible: bool
    blockers: list[str]
    proposed_revision: int | None


class ReleaseFitnessView(FitnessModel):
    schema_version: Literal[1] = 1
    asset_id: str
    display_name: str
    lane: str
    manifest_revision: int
    workflow_state: str
    selected_source: ArtifactIdentity | None
    current_processed: ArtifactIdentity | None
    integrity: IntegrityView
    technical_validation_result: str
    technical_checks: list[TechnicalCheckView]
    approval: ApprovalView
    library: LibraryView
    vandrel_consumer: ConsumerView
    release_eligibility: EligibilityView
