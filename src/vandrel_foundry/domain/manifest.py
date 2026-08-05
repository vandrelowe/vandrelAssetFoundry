import math
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from vandrel_foundry.domain.custody import LogicalRoot, PortableCustodyPath, Sha256
from vandrel_foundry.domain.ids import validate_asset_id
from vandrel_foundry.domain.provider import ProviderTaskStatus
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.storage.paths import RelativeManifestPath


def utc_now() -> datetime:
    return datetime.now(UTC)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssetIdentity(StrictModel):
    asset_id: str
    display_name: str = Field(min_length=1)
    lane: str = Field(min_length=1)
    created_at: datetime
    updated_at: datetime

    def model_post_init(self, __context: Any, /) -> None:
        validate_asset_id(self.asset_id)


class Workflow(StrictModel):
    state: WorkflowState = WorkflowState.DRAFT
    blocked_reason: str | None = None
    last_error: str | None = None


class Input(StrictModel):
    kind: Literal["text", "image", "external"] = "text"
    prompt_file: RelativeManifestPath = RelativeManifestPath("input/prompt.txt")
    reference_images: list[RelativeManifestPath] = Field(default_factory=list)


class Generation(StrictModel):
    provider: str
    selected_task_key: str | None = None
    tasks: list["ProviderTask"] = Field(default_factory=list)


class ProviderTask(StrictModel):
    task_key: str
    provider: str
    operation: str
    provider_task_id: str | None = Field(default=None, min_length=1, max_length=1024)
    attempt: int = Field(ge=1)
    status: ProviderTaskStatus
    progress: int | None = Field(default=None, ge=0, le=100)
    consumed_credits: int | None = Field(default=None, ge=0)
    request_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    request_path: RelativeManifestPath | None = None
    response_path: RelativeManifestPath | None = None
    response_snapshots: list[RelativeManifestPath] = Field(default_factory=list)
    submitted_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None


class Processor(StrictModel):
    name: str
    version: str


class Artifact(StrictModel):
    artifact_id: str
    role: str
    stage: str
    format: str
    path: RelativeManifestPath
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=0)
    derived_from: list[str] = Field(default_factory=list)
    source_task_key: str | None = None
    processor: Processor | None = None


class Quality(StrictModel):
    targets: dict[str, Any] = Field(default_factory=dict)
    observed: dict[str, Any] = Field(default_factory=dict)


SCALE_MEASUREMENT_TOLERANCE = 1e-6


def validate_scale_measurements(
    minimum: list[float] | None,
    maximum: list[float] | None,
    dimensions: list[float],
    *,
    require_bounds: bool,
) -> None:
    """Validate finite scale geometry within 1e-6 relative/absolute tolerance."""
    if any(not math.isfinite(value) or value <= 0 for value in dimensions):
        raise ValueError("Scale dimensions must be finite and positive.")
    if (minimum is None) != (maximum is None):
        raise ValueError("Scale bounds must be present or absent together.")
    if minimum is None or maximum is None:
        if require_bounds:
            raise ValueError("Scale bounds are required.")
        return
    if any(not math.isfinite(value) for value in [*minimum, *maximum]):
        raise ValueError("Scale bounds must be finite.")
    if any(lower > upper for lower, upper in zip(minimum, maximum, strict=True)):
        raise ValueError("Scale bounds minimum cannot exceed maximum.")
    for dimension, lower, upper in zip(dimensions, minimum, maximum, strict=True):
        if not math.isclose(
            dimension,
            upper - lower,
            rel_tol=SCALE_MEASUREMENT_TOLERANCE,
            abs_tol=SCALE_MEASUREMENT_TOLERANCE,
        ):
            raise ValueError("Scale dimensions must equal bounds maximum minus minimum.")


class ScaleCalibration(StrictModel):
    status: Literal["not_calibrated", "approved"] = "not_calibrated"
    processed_model_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    preview_report_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    source_bounds_min: list[float] | None = Field(default=None, min_length=3, max_length=3)
    source_bounds_max: list[float] | None = Field(default=None, min_length=3, max_length=3)
    source_dimensions: list[float] | None = Field(default=None, min_length=3, max_length=3)
    target_height_meters: float | None = Field(default=None, gt=0)
    baseline_uniform_scale: float | None = Field(default=None, gt=0)
    variation_min_multiplier: float | None = Field(default=None, gt=0)
    variation_max_multiplier: float | None = Field(default=None, gt=0)
    reference_standard: Literal["meter_grid_and_human_1_8m"] | None = None
    reviewer: str | None = None
    approved_at: datetime | None = None
    notes: str = ""

    @model_validator(mode="after")
    def validate_approved_shape(self) -> "ScaleCalibration":
        scalars = (
            self.target_height_meters,
            self.baseline_uniform_scale,
            self.variation_min_multiplier,
            self.variation_max_multiplier,
        )
        if any(value is not None and (not math.isfinite(value) or value <= 0) for value in scalars):
            raise ValueError("Scale calibration values must be finite and positive.")
        if (self.source_bounds_min is None) != (self.source_bounds_max is None):
            raise ValueError("Scale bounds must be present or absent together.")
        has_measurements = any(
            value is not None
            for value in (
                self.source_bounds_min,
                self.source_bounds_max,
                self.source_dimensions,
            )
        )
        if has_measurements:
            if self.source_dimensions is None:
                raise ValueError("Scale bounds require dimensions.")
            validate_scale_measurements(
                self.source_bounds_min,
                self.source_bounds_max,
                self.source_dimensions,
                require_bounds=True,
            )
        if (
            self.variation_min_multiplier is not None
            and self.variation_max_multiplier is not None
            and self.variation_min_multiplier > self.variation_max_multiplier
        ):
            raise ValueError("Scale variation minimum cannot exceed maximum.")
        if self.status == "approved":
            required = (
                self.processed_model_sha256,
                self.preview_report_sha256,
                self.source_bounds_min,
                self.source_bounds_max,
                self.source_dimensions,
                self.target_height_meters,
                self.baseline_uniform_scale,
                self.variation_min_multiplier,
                self.variation_max_multiplier,
                self.reference_standard,
                self.reviewer,
                self.approved_at,
            )
            if any(value is None for value in required):
                raise ValueError("Approved scale calibration requires complete evidence.")
            assert self.source_bounds_min is not None
            assert self.source_bounds_max is not None
            assert self.source_dimensions is not None
            assert self.target_height_meters is not None
            assert self.baseline_uniform_scale is not None
            assert self.variation_min_multiplier is not None
            assert self.variation_max_multiplier is not None
        return self


class Validation(StrictModel):
    result: Literal["not_run", "passed", "failed"] = "not_run"
    checks: list[dict[str, Any]] = Field(default_factory=list)


class CustodySourceInput(StrictModel):
    artifact_id: str = Field(min_length=1)
    role: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=0)


class CustodyLicenseEvidence(StrictModel):
    binding_id: str = Field(min_length=1)
    original_evidence_path: RelativeManifestPath | PortableCustodyPath
    evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=0)
    scope_root: RelativeManifestPath | PortableCustodyPath
    rights_semantics: Literal["documented"]
    candidate_evidence_artifact_id: str = Field(min_length=1)


class CustodySourceContribution(StrictModel):
    contribution_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    package_id: str = Field(min_length=1)
    package_root: RelativeManifestPath | PortableCustodyPath
    source_inputs: list[CustodySourceInput] = Field(default_factory=list)
    rights_status: Literal["documented", "missing", "disputed"]
    license_evidence: list[CustodyLicenseEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_rights_evidence(self) -> "CustodySourceContribution":
        if not self.source_inputs:
            raise ValueError("Custody contribution requires source input bindings.")
        if self.rights_status == "documented" and not self.license_evidence:
            raise ValueError("Documented custody contribution requires license evidence.")
        if self.rights_status != "documented" and self.license_evidence:
            raise ValueError("Only documented custody contributions may bind license evidence.")
        return self


class CustodyAssertion(StrictModel):
    schema_version: Literal[
        "vandrel_foundry_candidate_custody/1.0",
        "vandrel_foundry_candidate_custody/1.1",
        "vandrel_foundry_candidate_custody/1.2",
    ]
    assessment_status: Literal["absent", "historical_unassessed", "evaluated"]
    source_contributions: list[CustodySourceContribution] = Field(default_factory=list)
    policy_schema_version: str | None = None
    policy_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    register_schema_version: str | None = None
    register_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    register_root_fingerprints: (
        Annotated[dict[LogicalRoot, Sha256], Field(min_length=3, max_length=3)]
        | Annotated[dict[LogicalRoot, Sha256], Field(min_length=1, max_length=1)]
        | None
    ) = None
    evidence_fingerprint_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    evaluated_manifest_revision: int | None = Field(default=None, ge=1)
    effective_rights_status: Literal["documented", "missing", "disputed"] | None = None
    semantic_assertion_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_assessment_shape(self) -> "CustodyAssertion":
        evaluated_fields = (
            self.policy_schema_version,
            self.policy_sha256,
            self.register_schema_version,
            self.register_sha256,
            self.evaluated_manifest_revision,
            self.effective_rights_status,
            self.semantic_assertion_sha256,
        )
        freshness_fields = (
            self.register_root_fingerprints,
            self.evidence_fingerprint_sha256,
        )
        if self.assessment_status == "evaluated":
            required_fields = (
                (*evaluated_fields, *freshness_fields)
                if not self.schema_version.endswith("/1.0")
                else evaluated_fields
            )
            if any(value is None for value in required_fields) or not self.source_contributions:
                raise ValueError(
                    "Evaluated custody requires complete identity and source bindings."
                )
            statuses = {item.rights_status for item in self.source_contributions}
            expected = (
                "disputed"
                if "disputed" in statuses
                else "missing"
                if "missing" in statuses
                else "documented"
            )
            if self.effective_rights_status != expected:
                raise ValueError("Effective custody rights do not match contributions.")
            portable_paths = [
                value
                for contribution in self.source_contributions
                for value in (
                    contribution.package_root,
                    *(
                        path
                        for evidence in contribution.license_evidence
                        for path in (evidence.original_evidence_path, evidence.scope_root)
                    ),
                )
            ]
            if self.schema_version.endswith("/1.0"):
                if self.register_root_fingerprints is not None:
                    raise ValueError("Custody assertion 1.0 cannot carry root fingerprints.")
                if self.evidence_fingerprint_sha256 is not None:
                    raise ValueError("Custody assertion 1.0 cannot carry evidence freshness.")
                if any(isinstance(value, PortableCustodyPath) for value in portable_paths):
                    raise ValueError("Custody assertion 1.0 requires legacy relative paths.")
            elif self.schema_version.endswith("/1.1"):
                expected_roots = {"outside_assets", "foundry_workspace", "asset_library"}
                if (
                    self.register_root_fingerprints is None
                    or set(self.register_root_fingerprints) != expected_roots
                ):
                    raise ValueError("Custody assertion 1.1 requires all root fingerprints.")
                if any(
                    not isinstance(value, PortableCustodyPath)
                    or value.logical_root != "outside_assets"
                    for value in portable_paths
                ):
                    raise ValueError(
                        "Custody assertion 1.1 paths require the outside_assets logical root."
                    )
            else:
                if (
                    self.register_schema_version != "vandrel_foundry_provider_provenance/1.0"
                    or self.register_root_fingerprints is None
                    or set(self.register_root_fingerprints) != {"foundry_workspace"}
                ):
                    raise ValueError(
                        "Custody assertion 1.2 requires provider provenance in foundry_workspace."
                    )
                if any(
                    not isinstance(value, PortableCustodyPath)
                    or value.logical_root != "foundry_workspace"
                    for value in portable_paths
                ):
                    raise ValueError(
                        "Custody assertion 1.2 paths require the foundry_workspace logical root."
                    )
        elif (
            any(value is not None for value in (*evaluated_fields, *freshness_fields))
            or self.source_contributions
        ):
            raise ValueError("Unevaluated custody cannot carry evaluated facts.")
        return self


class Approval(StrictModel):
    approved: bool = False
    approved_at: datetime | None = None
    approved_artifact_hashes: dict[str, str] = Field(default_factory=dict)
    custody_assertion_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    custody_source_inputs: list[CustodySourceInput] = Field(default_factory=list)
    reviewer: str | None = None
    notes: str = ""


class Release(StrictModel):
    released: bool = False
    release_revision: int | None = None
    released_at: datetime | None = None


class AssetManifest(StrictModel):
    schema_version: Literal[1, 2] = 2
    revision: int = Field(default=1, ge=1)
    asset: AssetIdentity
    workflow: Workflow = Field(default_factory=Workflow)
    input: Input = Field(default_factory=Input)
    generation: Generation
    artifacts: list[Artifact] = Field(default_factory=list)
    vandrel_technical: dict[str, Any] = Field(default_factory=dict)
    quality: Quality = Field(default_factory=Quality)
    scale_calibration: ScaleCalibration = Field(default_factory=ScaleCalibration)
    validation: Validation = Field(default_factory=Validation)
    custody: CustodyAssertion | None = None
    approval: Approval = Field(default_factory=Approval)
    release: Release = Field(default_factory=Release)
    notes: str = ""

    @classmethod
    def initial(cls, asset_id: str, display_name: str, lane: str, provider: str) -> "AssetManifest":
        now = utc_now()
        return cls(
            asset=AssetIdentity(
                asset_id=asset_id,
                display_name=display_name,
                lane=lane,
                created_at=now,
                updated_at=now,
            ),
            generation=Generation(provider=provider),
            custody=CustodyAssertion(
                schema_version="vandrel_foundry_candidate_custody/1.0",
                assessment_status="absent",
            ),
        )
