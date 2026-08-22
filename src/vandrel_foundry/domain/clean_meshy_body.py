"""Executable contracts for clean Meshy bodies using shared animation libraries."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
AssetId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_]{2,63}$")]
Semantic = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")]

CLEAN_BODY_PROCESSOR = "blender_clean_meshy_body"
CLEAN_BODY_PROCESSOR_VERSION = "1"
CLEAN_BODY_ROUTE = "clean_body_shared_animation"
CLEAN_BODY_IMPORT_POLICY = "godot_clean_body_humanoid_bone_map_rest_fixer_v1"
CLEAN_BODY_MEMBER_ROLES = (
    "running_evidence",
    "walking_evidence",
    "body",
    "albedo",
)
CLEAN_BODY_REST_VIEWS = ("front", "side", "back")
CLEAN_BODY_SHARED_PHASES = (0.0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875)
CLEAN_BODY_CAMERA_POLICY = "vandrel_fixed_clean_body_review_camera_v1"
CLEAN_BODY_CAMERA_CONFIG = {
    "resolution": [1280, 720],
    "position": [0.0, 0.9, 4.8],
    "target": [0.0, 0.95, 0.0],
    "up": [0.0, 1.0, 0.0],
    "fov_degrees": 38.0,
    "rest_views": list(CLEAN_BODY_REST_VIEWS),
    "shared_motion_phases": list(CLEAN_BODY_SHARED_PHASES),
}
CLEAN_BODY_CAMERA_CONFIG_SHA256 = hashlib.sha256(
    json.dumps(
        CLEAN_BODY_CAMERA_CONFIG,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
).hexdigest()


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExactLocalFile(ContractModel):
    path: str = Field(min_length=1)
    sha256: Sha256
    size_bytes: int = Field(gt=0)


class CleanBodyArchiveMember(ContractModel):
    role: Literal["running_evidence", "walking_evidence", "body", "albedo"]
    archive_member: str = Field(min_length=1)
    sha256: Sha256
    size_bytes: int = Field(gt=0)

    @model_validator(mode="after")
    def safe_member(self) -> CleanBodyArchiveMember:
        value = self.archive_member.replace("\\", "/")
        parts = value.split("/")
        if (
            value.startswith("/")
            or ":" in parts[0]
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise ValueError("Archive member path must be safe and portable.")
        return self


class CleanBodyPackagePolicy(ContractModel):
    schema_version: Literal["vandrel_foundry_clean_meshy_body_package_policy/1.0"]
    exact_ordered_members: list[CleanBodyArchiveMember] = Field(
        min_length=4, max_length=4
    )
    forbidden_output_sha256s: list[Sha256] = Field(min_length=1)
    forbidden_route_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def exact_inventory(self) -> CleanBodyPackagePolicy:
        if tuple(item.role for item in self.exact_ordered_members) != CLEAN_BODY_MEMBER_ROLES:
            raise ValueError("Clean-body archive roles must use the exact ordered inventory.")
        paths = [item.archive_member for item in self.exact_ordered_members]
        if len(paths) != len(set(paths)):
            raise ValueError("Clean-body archive member paths must be unique.")
        if len(self.forbidden_output_sha256s) != len(set(self.forbidden_output_sha256s)):
            raise ValueError("Forbidden output hashes must be unique.")
        if len(self.forbidden_route_ids) != len(set(self.forbidden_route_ids)):
            raise ValueError("Forbidden route identities must be unique.")
        if "meshy_native" not in self.forbidden_route_ids:
            raise ValueError("Clean-body package policy must forbid the Meshy-native route.")
        return self


class CleanMeshyBodyIntakeRequest(ContractModel):
    schema_version: Literal["vandrel_foundry_clean_meshy_body_intake/1.0"]
    asset_id: AssetId
    archive: ExactLocalFile
    provider_rig_task_id: str | None = Field(default=None, min_length=1)
    selected_body_sha256: Sha256
    selected_albedo_sha256: Sha256
    accepted_bone_map: ExactLocalFile
    accepted_import_sidecar_policy: ExactLocalFile
    package_policy: CleanBodyPackagePolicy
    package_policy_sha256: Sha256

    @model_validator(mode="after")
    def exact_selected_members(self) -> CleanMeshyBodyIntakeRequest:
        members = {item.role: item for item in self.package_policy.exact_ordered_members}
        if members["body"].sha256 != self.selected_body_sha256:
            raise ValueError("Selected body differs from the exact archive inventory.")
        if members["albedo"].sha256 != self.selected_albedo_sha256:
            raise ValueError("Selected albedo differs from the exact archive inventory.")
        selected = {self.selected_body_sha256, self.selected_albedo_sha256}
        if selected & set(self.package_policy.forbidden_output_sha256s):
            raise ValueError("Selected clean-body bytes are forbidden historical outputs.")
        return self


class CleanBodyValidationRequest(ContractModel):
    schema_version: Literal["vandrel_foundry_clean_meshy_body_validation/1.0"]
    asset_id: AssetId
    accepted_bone_map: ExactLocalFile
    accepted_import_sidecar_policy: ExactLocalFile
    shared_animation_library_asset_id: AssetId
    shared_animation_library_release_revision: int = Field(ge=1, le=999)
    shared_animation_library_sha256: Sha256
    shared_semantics: list[Semantic] = Field(min_length=1, max_length=64)
    import_policy: Literal["godot_clean_body_humanoid_bone_map_rest_fixer_v1"]
    camera_policy: Literal["vandrel_fixed_clean_body_review_camera_v1"]
    camera_config_sha256: Sha256

    @model_validator(mode="after")
    def unique_semantics_and_camera(self) -> CleanBodyValidationRequest:
        if len(self.shared_semantics) != len(set(self.shared_semantics)):
            raise ValueError("Shared animation semantics must be unique.")
        if self.camera_config_sha256 != CLEAN_BODY_CAMERA_CONFIG_SHA256:
            raise ValueError("Clean-body camera configuration is not canonical.")
        return self


class CleanBodyVisualEvidence(ContractModel):
    path: str = Field(min_length=1)
    sha256: Sha256
    size_bytes: int = Field(gt=0)


class CleanBodyRestReviewCell(ContractModel):
    view: Literal["front", "side", "back"]
    result: Literal["PASS", "FAIL"]
    evidence: CleanBodyVisualEvidence
    notes: str = ""


class CleanBodyMotionReviewCell(ContractModel):
    semantic: Semantic
    result: Literal["PASS", "FAIL"]
    observed_phases: list[float] = Field(min_length=8, max_length=8)
    evidence: CleanBodyVisualEvidence
    notes: str = ""

    @model_validator(mode="after")
    def exact_phases(self) -> CleanBodyMotionReviewCell:
        if tuple(self.observed_phases) != CLEAN_BODY_SHARED_PHASES:
            raise ValueError("Shared-motion evidence must use the exact fixed phases.")
        return self


class CleanBodyVisualReviewRequest(ContractModel):
    schema_version: Literal["vandrel_foundry_clean_meshy_body_visual_review/1.0"]
    asset_id: AssetId
    processed_body_sha256: Sha256
    technical_report_sha256: Sha256
    monitor_report_sha256: Sha256
    shared_animation_library_sha256: Sha256
    camera_policy: Literal["vandrel_fixed_clean_body_review_camera_v1"]
    camera_config_sha256: Sha256
    reviewer: str = Field(min_length=1)
    reviewed_at: str = Field(min_length=1)
    rest_cells: list[CleanBodyRestReviewCell] = Field(min_length=3, max_length=3)
    motion_cells: list[CleanBodyMotionReviewCell] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def exact_review_membership(self) -> CleanBodyVisualReviewRequest:
        if tuple(item.view for item in self.rest_cells) != CLEAN_BODY_REST_VIEWS:
            raise ValueError("Rest review must contain front, side, and back in order.")
        semantics = [item.semantic for item in self.motion_cells]
        if len(semantics) != len(set(semantics)):
            raise ValueError("Shared-motion visual semantics must be unique.")
        hashes = [item.evidence.sha256 for item in [*self.rest_cells, *self.motion_cells]]
        if len(hashes) != len(set(hashes)):
            raise ValueError("Every clean-body visual cell requires unique evidence bytes.")
        if self.camera_config_sha256 != CLEAN_BODY_CAMERA_CONFIG_SHA256:
            raise ValueError("Clean-body visual review camera is not canonical.")
        return self


def canonical_policy_sha256(policy: CleanBodyPackagePolicy) -> str:
    payload = (
        json.dumps(policy.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
