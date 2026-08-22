"""Strict request and evidence shapes for animation-library visual capture."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from vandrel_foundry.domain.animation_library import FIXED_PHASES, AnimationVisualBody

Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Semantic = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")]

CAMERA_POLICY = "vandrel_fixed_animation_review_camera_v1"
HORIZONTAL_ROOT_MOTION_TOLERANCE = 0.0001


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ExactCaptureInput(ContractModel):
    path: str = Field(min_length=1)
    sha256: Sha256
    size_bytes: int = Field(gt=0)


class ExactCaptureResource(ExactCaptureInput):
    resource_path: str = Field(pattern=r"^res://[A-Za-z0-9_./-]+$")

    @model_validator(mode="after")
    def safe_resource_path(self) -> ExactCaptureResource:
        relative = self.resource_path.removeprefix("res://")
        if not relative or ".." in relative.split("/"):
            raise ValueError("Capture resource path is not sandbox-relative.")
        return self


class ExactCaptureBody(ExactCaptureResource):
    body_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_]{2,63}$")
    import_sidecar: ExactCaptureResource
    bone_map: ExactCaptureResource

    @model_validator(mode="after")
    def exact_import_resources(self) -> ExactCaptureBody:
        if self.import_sidecar.resource_path != f"{self.resource_path}.import":
            raise ValueError("Body import sidecar resource path does not match its FBX.")
        if not self.resource_path.casefold().endswith(".fbx"):
            raise ValueError("Capture body resource path must name an FBX.")
        if not self.bone_map.resource_path.casefold().endswith(".tres"):
            raise ValueError("Capture BoneMap resource path must name a TRES resource.")
        return self


class AnimationVisualCaptureRequest(ContractModel):
    schema_version: Literal["vandrel_foundry_animation_visual_capture_request/1.0"]
    asset_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_]{2,63}$")
    animation_library: ExactCaptureInput
    technical_report: ExactCaptureInput
    bodies: list[ExactCaptureBody] = Field(min_length=3, max_length=3)
    camera_policy: Literal["vandrel_fixed_animation_review_camera_v1"]
    camera_config_sha256: Sha256

    @model_validator(mode="after")
    def exact_three_bodies(self) -> AnimationVisualCaptureRequest:
        body_ids = [body.body_id for body in self.bodies]
        body_hashes = [body.sha256 for body in self.bodies]
        body_paths = [body.resource_path for body in self.bodies]
        if (
            len(set(body_ids)) != 3
            or len(set(body_hashes)) != 3
            or len(set(body_paths)) != 3
        ):
            raise ValueError("Visual capture requires three distinct body payloads.")
        return self


class CaptureEvidence(ContractModel):
    path: str = Field(pattern=r"^cells/[A-Za-z0-9_.-]+\.png$")
    sha256: Sha256
    size_bytes: int = Field(gt=0)


class AnimationVisualCaptureCell(ContractModel):
    semantic: Semantic
    body_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_]{2,63}$")
    observed_phases: list[float] = Field(min_length=8, max_length=8)
    evidence: CaptureEvidence
    horizontal_root_motion_span_x: float = Field(ge=0.0)
    horizontal_root_motion_span_z: float = Field(ge=0.0)
    horizontal_root_motion_initial_offset_x: float
    horizontal_root_motion_initial_offset_z: float
    horizontal_root_motion_max_delta_from_first: float = Field(ge=0.0)
    camera_follow_enabled: Literal[False]
    per_phase_reframing: Literal[False]

    @model_validator(mode="after")
    def exact_capture_policy(self) -> AnimationVisualCaptureCell:
        if tuple(self.observed_phases) != FIXED_PHASES:
            raise ValueError("Capture cell does not contain the exact fixed phases.")
        if max(
            self.horizontal_root_motion_span_x,
            self.horizontal_root_motion_span_z,
            self.horizontal_root_motion_max_delta_from_first,
        ) > HORIZONTAL_ROOT_MOTION_TOLERANCE:
            raise ValueError("Capture cell contains horizontal root motion.")
        return self


class AnimationVisualCaptureManifest(ContractModel):
    schema_version: Literal["vandrel_foundry_animation_visual_capture_manifest/1.0"]
    target_import_schema_version: Literal["vandrel_foundry_animation_visual_matrix/1.0"]
    asset_id: str
    animation_library_sha256: Sha256
    technical_report_sha256: Sha256
    selected_semantics: list[Semantic] = Field(min_length=1)
    bodies: list[AnimationVisualBody] = Field(min_length=3, max_length=3)
    camera_policy: Literal["vandrel_fixed_animation_review_camera_v1"]
    camera_config_sha256: Sha256
    observed_phases: list[float] = Field(min_length=8, max_length=8)
    cells: list[AnimationVisualCaptureCell] = Field(min_length=3)
    capture_report_path: Literal["capture-report.json"]
    capture_report_sha256: Sha256
    monitor_report_path: Literal["godot-monitor.json"]
    monitor_report_sha256: Sha256
    review_status: Literal["manual_review_required"]
    anatomy_acceptance: Literal["not_assessed"]
    reviewer: None = None
    reviewed_at: None = None

    @model_validator(mode="after")
    def exact_grid_and_unique_evidence(self) -> AnimationVisualCaptureManifest:
        if tuple(self.observed_phases) != FIXED_PHASES:
            raise ValueError("Capture manifest does not use the exact fixed phases.")
        body_ids = [body.body_id for body in self.bodies]
        body_hashes = [body.payload_sha256 for body in self.bodies]
        if len(set(body_ids)) != 3 or len(set(body_hashes)) != 3:
            raise ValueError("Capture manifest body bindings are not exact and distinct.")
        expected = {
            (semantic, body_id)
            for semantic in self.selected_semantics
            for body_id in body_ids
        }
        actual = {(cell.semantic, cell.body_id) for cell in self.cells}
        if actual != expected or len(actual) != len(self.cells):
            raise ValueError("Capture manifest does not contain the exact semantic/body grid.")
        hashes = [cell.evidence.sha256 for cell in self.cells]
        if len(hashes) != len(set(hashes)):
            raise ValueError("Capture evidence must be unique per semantic/body cell.")
        return self
