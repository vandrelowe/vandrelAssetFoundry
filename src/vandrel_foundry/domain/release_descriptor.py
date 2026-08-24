"""Versioned executable contracts for historical and planned release descriptors."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from vandrel_foundry.domain.custody import LogicalRoot, PortableCustodyPath
from vandrel_foundry.domain.custody_assertion import evidence_freshness_sha256
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import validate_scale_measurements
from vandrel_foundry.storage.paths import RelativeManifestPath

Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
ReleaseRevision = Annotated[int, Field(ge=1, le=999)]
AssetId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_]{2,63}$")]


class HistoricalModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class ReleaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReleaseFileV1(HistoricalModel):
    role: str
    path: str
    sha256: Sha256
    size_bytes: int = Field(ge=0)
    source_artifact_id: str


class ReleaseDescriptorV1(HistoricalModel):
    schema_version: Literal[1]
    asset_id: AssetId
    release_revision: ReleaseRevision
    files: list[ReleaseFileV1]


ReleaseFileRole = Literal[
    "model",
    "animation_library",
    "animation_library_technical_report",
    "animation_library_visual_matrix_report",
    "animation_library_godot_monitor_report",
    "animation_library_isolation_report",
    "animation_visual_evidence",
    "godot_wrapper_scene",
    "godot_animation_loader_script",
    "animation_walk",
    "animation_run",
    "custody_license_evidence",
    "humanoid_compatibility_report",
    "creature_playback_report",
    "clean_body_buffer",
    "clean_body_albedo",
    "clean_body_processing_report",
    "clean_body_technical_report",
    "clean_body_godot_monitor_report",
    "clean_body_visual_review_report",
    "clean_body_visual_evidence",
]


class ReleaseFileV2(ReleaseModel):
    role: ReleaseFileRole
    path: str
    sha256: Sha256
    size_bytes: int = Field(ge=0)
    source_artifact_id: str = Field(min_length=1)

    @field_validator("path")
    @classmethod
    def portable_release_path(cls, value: str) -> str:
        return str(RelativeManifestPath.validate(value))


class ReleaseGodotV2(ReleaseModel):
    import_validated: bool
    wrapper_template: str = Field(min_length=1)


class ReleaseTechnicalV2(ReleaseModel):
    triangle_count: int | None = Field(default=None, ge=0)
    mesh_count: int | None = Field(default=None, ge=0)
    primitive_count: int | None = Field(default=None, ge=0)
    material_count: int | None = Field(default=None, ge=0)
    texture_count: int | None = Field(default=None, ge=0)
    image_count: int | None = Field(default=None, ge=0)
    skin_count: int | None = Field(default=None, ge=0)
    joint_count: int | None = Field(default=None, ge=0)
    animation_count: int | None = Field(default=None, ge=0)
    visible_mesh_count: int | None = Field(default=None, ge=0)
    visible_skinned_mesh_count: int | None = Field(default=None, ge=0)
    visible_unskinned_mesh_count: int | None = Field(default=None, ge=0)
    visible_skinned_triangle_count: int | None = Field(default=None, ge=0)
    inspected_processed_artifact_id: (
        Annotated[
            str,
            Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"),
        ]
        | None
    ) = None
    inspected_processed_sha256: Sha256 | None = None
    animation_source: Literal["meshy_same_rigging_task"] | None = None
    recommended_fbx_embedded_texture_handling: Literal["embed_basis_universal"] | None = None
    collision_recommendation: Literal[
        "manual",
        "manual_review",
        "manual_simple_convex",
        "none",
    ]


class ReleaseCustodyPolicyV2(ReleaseModel):
    schema_version: str = Field(min_length=1)
    sha256: Sha256


class ReleaseCustodyRegisterV2(ReleaseModel):
    schema_version: Literal[
        "vandrel_foundry_custody_register/1.1",
        "vandrel_foundry_provider_provenance/1.0",
        "vandrel_foundry_user_local_use_declaration/1.0",
    ]
    sha256: Sha256
    root_fingerprints: (
        Annotated[dict[LogicalRoot, Sha256], Field(min_length=3, max_length=3)]
        | Annotated[dict[LogicalRoot, Sha256], Field(min_length=1, max_length=1)]
    )

    @model_validator(mode="after")
    def complete_root_set(self) -> ReleaseCustodyRegisterV2:
        expected = (
            {"outside_assets", "foundry_workspace", "asset_library"}
            if self.schema_version == "vandrel_foundry_custody_register/1.1"
            else {"foundry_workspace"}
        )
        if set(self.root_fingerprints) != expected:
            raise ValueError("Release custody roots do not match its evidence authority.")
        return self


class ReleaseCustodySourceInputV2(ReleaseModel):
    artifact_id: str = Field(min_length=1)
    role: str = Field(min_length=1)
    sha256: Sha256
    size_bytes: int = Field(ge=0)


class ReleaseCustodyEvidenceV2(ReleaseModel):
    binding_id: str = Field(min_length=1)
    original_evidence_path: PortableCustodyPath
    release_path: str
    sha256: Sha256
    size_bytes: int = Field(ge=0)
    source_artifact_id: str = Field(min_length=1)
    scope_root: PortableCustodyPath
    rights_semantics: Literal["documented"]

    @field_validator("release_path")
    @classmethod
    def portable_release_path(cls, value: str) -> str:
        return str(RelativeManifestPath.validate(value))


class ReleaseCustodyContributionV2(ReleaseModel):
    contribution_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    package_id: str = Field(min_length=1)
    package_root: PortableCustodyPath
    rights_status: Literal["documented"]
    source_inputs: list[ReleaseCustodySourceInputV2] = Field(min_length=1)
    license_evidence: list[ReleaseCustodyEvidenceV2] = Field(min_length=1)


class ReleaseCustodyV2(ReleaseModel):
    schema_version: Literal[
        "vandrel_foundry_candidate_custody/1.1",
        "vandrel_foundry_candidate_custody/1.2",
        "vandrel_foundry_candidate_custody/1.3",
    ]
    assessment_status: Literal["evaluated"]
    effective_rights_status: Literal["documented"]
    semantic_assertion_sha256: Sha256
    policy: ReleaseCustodyPolicyV2
    custody_register: ReleaseCustodyRegisterV2 = Field(
        alias="register",
        serialization_alias="register",
    )
    evidence_fingerprint_sha256: Sha256
    evaluated_manifest_revision: int = Field(ge=1)
    source_contributions: list[ReleaseCustodyContributionV2] = Field(min_length=1)

    @model_validator(mode="after")
    def freshness_binding_matches(self) -> ReleaseCustodyV2:
        expected = evidence_freshness_sha256(
            policy_schema_version=self.policy.schema_version,
            policy_sha256=self.policy.sha256,
            register_schema_version=self.custody_register.schema_version,
            register_sha256=self.custody_register.sha256,
            root_fingerprints=self.custody_register.root_fingerprints,
        )
        if self.evidence_fingerprint_sha256 != expected:
            raise ValueError("Release custody evidence freshness fingerprint is stale.")
        return self


class PackagedHumanoidReportV2(ReleaseModel):
    release_path: str
    sha256: Sha256
    size_bytes: int = Field(ge=0)
    source_artifact_id: str = Field(min_length=1)

    @field_validator("release_path")
    @classmethod
    def portable_release_path(cls, value: str) -> str:
        return str(RelativeManifestPath.validate(value))


class ReleaseAnimationSourceV2(ReleaseModel):
    semantic: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
    source_sha256: Sha256
    source_size_bytes: int = Field(gt=0)


class ReleaseAnimationLibraryV2(ReleaseModel):
    import_policy: Literal[
        "godot_skeleton_profile_humanoid_meshy_bone_map_rest_fixer_v1",
        "godot_skeleton_profile_humanoid_meshy_bone_map_rest_fixer_carrier_bake_v2",
    ]
    # This field was added after schema_version 2 releases already existed.
    # Absence therefore means "not recorded by that descriptor revision", not
    # an inferred processor version and not an invalid immutable release.
    processor_version: Literal["4", "5"] | None = None
    selected_sources: list[ReleaseAnimationSourceV2] = Field(min_length=1, max_length=64)
    excluded_source_sha256s: list[Sha256] = Field(default_factory=list)
    output_sha256: Sha256
    technical_report: PackagedHumanoidReportV2
    monitor_report: PackagedHumanoidReportV2
    isolation_report: PackagedHumanoidReportV2
    visual_matrix_report: PackagedHumanoidReportV2

    @model_validator(mode="after")
    def exact_unique_membership(self) -> ReleaseAnimationLibraryV2:
        semantics = [item.semantic for item in self.selected_sources]
        source_hashes = [item.source_sha256 for item in self.selected_sources]
        if len(semantics) != len(set(semantics)) or len(source_hashes) != len(set(source_hashes)):
            raise ValueError("Release animation-library membership must be unique.")
        if set(source_hashes) & set(self.excluded_source_sha256s):
            raise ValueError("Selected and excluded animation sources overlap.")
        expected_version = (
            "5"
            if self.import_policy
            == "godot_skeleton_profile_humanoid_meshy_bone_map_rest_fixer_carrier_bake_v2"
            else "4"
        )
        if self.processor_version is not None and self.processor_version != expected_version:
            raise ValueError("Animation-library processor version differs from import policy.")
        return self


class ReleaseSharedAnimationReferenceV2(ReleaseModel):
    asset_id: AssetId
    release_revision: ReleaseRevision
    output_sha256: Sha256


class ReleaseCleanBodyV2(ReleaseModel):
    evidence_route: Literal["clean_body_shared_animation"]
    candidate_only: Literal[True]
    vandrel_runtime_accepted: Literal[False]
    shared_animation_pool_compatible: Literal[True]
    embedded_animations_disabled: Literal[True]
    import_policy: Literal["godot_clean_body_humanoid_bone_map_rest_fixer_v1"]
    material_policy: Literal["external_lit_principled_albedo_v1"]
    output_sha256: Sha256
    dependency_sha256s: list[Sha256] = Field(min_length=2, max_length=2)
    shared_animation_library: ReleaseSharedAnimationReferenceV2
    processing_report: PackagedHumanoidReportV2
    technical_report: PackagedHumanoidReportV2
    monitor_report: PackagedHumanoidReportV2
    visual_review_report: PackagedHumanoidReportV2


class RetargetHumanoidCompatibilityV2(ReleaseModel):
    evidence_route: Literal["retarget_mapping"]
    candidate_only: Literal[True]
    vandrel_runtime_accepted: Literal[False]
    mapping_profile: str = Field(min_length=1)
    report: PackagedHumanoidReportV2
    animation_donor_asset_id: AssetId
    direct_skeleton_match: bool
    direct_rest_transform_match: bool
    humanoid_retarget_candidate: Literal[True]


class NativeHumanoidCompatibilityV2(ReleaseModel):
    evidence_route: Literal["provider_native_same_task"]
    candidate_only: Literal[True]
    vandrel_runtime_accepted: Literal[False]
    provider_native_same_task: Literal[True]
    shared_animation_pool_compatible: Literal[False]
    report: PackagedHumanoidReportV2


class MeshyNativeAssemblyCompatibilityV2(ReleaseModel):
    evidence_route: Literal["meshy_native_motion_assembly"]
    candidate_only: Literal[True]
    vandrel_runtime_accepted: Literal[False]
    provider_native_rig: Literal[True]
    shared_animation_pool_compatible: Literal[False]
    clip_count: int = Field(ge=29)
    embedded_texture_sha256s: list[Sha256] = Field(min_length=1)
    known_hand_visual_debt: Literal[
        "accepted_bounded_debt", "pending_consumer_review"
    ]
    h4_additional_hand_corruption: Literal[False]
    report: PackagedHumanoidReportV2


HumanoidCompatibilityV2 = (
    RetargetHumanoidCompatibilityV2
    | NativeHumanoidCompatibilityV2
    | MeshyNativeAssemblyCompatibilityV2
)


class ReleaseScaleCalibrationV2(ReleaseModel):
    processed_model_sha256: Sha256
    preview_report_sha256: Sha256
    source_bounds_min: Annotated[list[float], Field(min_length=3, max_length=3)] | None = None
    source_bounds_max: Annotated[list[float], Field(min_length=3, max_length=3)] | None = None
    source_dimensions: Annotated[list[float], Field(min_length=3, max_length=3)]
    target_height_meters: float = Field(gt=0)
    baseline_uniform_scale: float = Field(gt=0)
    variation_min_multiplier: float = Field(gt=0)
    variation_max_multiplier: float = Field(gt=0)
    reference_standard: Literal["meter_grid_and_human_1_8m"]
    reviewer: str = Field(min_length=1)
    approved_at: datetime
    notes: str = ""

    @model_validator(mode="after")
    def valid_scale_range(self) -> ReleaseScaleCalibrationV2:
        validate_scale_measurements(
            self.source_bounds_min,
            self.source_bounds_max,
            self.source_dimensions,
            require_bounds=False,
        )
        scalars = (
            self.target_height_meters,
            self.baseline_uniform_scale,
            self.variation_min_multiplier,
            self.variation_max_multiplier,
        )
        if any(not math.isfinite(value) or value <= 0 for value in scalars):
            raise ValueError("Release scale values must be finite and positive.")
        if self.variation_min_multiplier > self.variation_max_multiplier:
            raise ValueError("Release scale variation minimum cannot exceed maximum.")
        return self


class ReleaseProvenanceV2(ReleaseModel):
    foundry_manifest_revision: int = Field(ge=1)
    approval_reviewer: str = Field(min_length=1)
    approved_at: datetime


class ReleaseDescriptorV2(ReleaseModel):
    schema_version: Literal[2]
    asset_id: AssetId
    release_revision: ReleaseRevision
    display_name: str = Field(min_length=1)
    lane: str = Field(min_length=1)
    files: list[ReleaseFileV2] = Field(min_length=1)
    primary_payload: Literal["model", "animation_library", "clean_body"] | None = None
    godot: ReleaseGodotV2
    technical: ReleaseTechnicalV2
    custody: ReleaseCustodyV2
    animation_library: ReleaseAnimationLibraryV2 | None = None
    clean_body: ReleaseCleanBodyV2 | None = None
    humanoid_compatibility: HumanoidCompatibilityV2 | None = None
    scale_calibration: ReleaseScaleCalibrationV2 | None = None
    provenance: ReleaseProvenanceV2

    @model_validator(mode="after")
    def reconcile_packaged_evidence(self) -> ReleaseDescriptorV2:
        paths = [item.path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("Release file paths must be unique.")
        model_count = sum(item.role == "model" for item in self.files)
        library_files = [item for item in self.files if item.role == "animation_library"]
        effective_primary = self.primary_payload or "model"
        if effective_primary == "model":
            if model_count != 1 or library_files or self.animation_library is not None or self.clean_body is not None:
                raise ValueError("Model-primary release requires exactly one model file.")
        elif effective_primary == "animation_library" and (
            model_count != 0
            or len(library_files) != 1
            or self.animation_library is None
            or library_files[0].sha256 != self.animation_library.output_sha256
        ):
            raise ValueError(
                "Animation-library-primary release requires one exact library and no model."
            )
        elif effective_primary == "clean_body":
            allowed_roles = {
                "model",
                "clean_body_buffer",
                "clean_body_albedo",
                "clean_body_processing_report",
                "clean_body_technical_report",
                "clean_body_godot_monitor_report",
                "clean_body_visual_review_report",
                "clean_body_visual_evidence",
                "custody_license_evidence",
            }
            if (
                model_count != 1
                or library_files
                or self.animation_library is not None
                or self.clean_body is None
                or self.humanoid_compatibility is not None
                or any(item.role not in allowed_roles for item in self.files)
                or any(item.path.casefold().endswith((".import", ".tscn", ".fbx", ".res")) for item in self.files)
                or sum(item.role == "clean_body_buffer" for item in self.files) != 1
                or sum(item.role == "clean_body_albedo" for item in self.files) != 1
                or sum(item.role == "clean_body_visual_evidence" for item in self.files) < 4
                or next(item for item in self.files if item.role == "model").sha256
                != self.clean_body.output_sha256
            ):
                raise ValueError("Clean-body-primary release requires one exact body model.")
        file_bindings = {
            (
                item.role,
                item.path,
                item.sha256,
                item.size_bytes,
                item.source_artifact_id,
            )
            for item in self.files
        }
        for contribution in self.custody.source_contributions:
            for evidence in contribution.license_evidence:
                if (
                    "custody_license_evidence",
                    evidence.release_path,
                    evidence.sha256,
                    evidence.size_bytes,
                    evidence.source_artifact_id,
                ) not in file_bindings:
                    raise ValueError(
                        "Custody evidence role and source are not bound to "
                        "the exact packaged release file."
                    )
        if self.humanoid_compatibility is not None:
            report = self.humanoid_compatibility.report
            if (
                "humanoid_compatibility_report",
                report.release_path,
                report.sha256,
                report.size_bytes,
                report.source_artifact_id,
            ) not in file_bindings:
                raise ValueError(
                    "Humanoid report role and source are not bound to "
                    "the exact packaged release file."
                )
        if self.animation_library is not None:
            for role, report in (
                (
                    "animation_library_technical_report",
                    self.animation_library.technical_report,
                ),
                (
                    "animation_library_godot_monitor_report",
                    self.animation_library.monitor_report,
                ),
                (
                    "animation_library_isolation_report",
                    self.animation_library.isolation_report,
                ),
                (
                    "animation_library_visual_matrix_report",
                    self.animation_library.visual_matrix_report,
                ),
            ):
                if (
                    role,
                    report.release_path,
                    report.sha256,
                    report.size_bytes,
                    report.source_artifact_id,
                ) not in file_bindings:
                    raise ValueError(
                        "Animation-library evidence is not bound to its exact release file."
                    )
        if self.clean_body is not None:
            for role, report in (
                ("clean_body_processing_report", self.clean_body.processing_report),
                ("clean_body_technical_report", self.clean_body.technical_report),
                ("clean_body_godot_monitor_report", self.clean_body.monitor_report),
                ("clean_body_visual_review_report", self.clean_body.visual_review_report),
            ):
                if (role, report.release_path, report.sha256, report.size_bytes, report.source_artifact_id) not in file_bindings:
                    raise ValueError("Clean-body evidence is not bound to its exact release file.")
            dependencies = {item.sha256 for item in self.files if item.role in {"clean_body_buffer", "clean_body_albedo"}}
            if dependencies != set(self.clean_body.dependency_sha256s):
                raise ValueError("Clean-body dependencies do not bind the packaged buffer and albedo.")
        return self


ReleaseDescriptor = ReleaseDescriptorV1 | ReleaseDescriptorV2
RELEASE_DESCRIPTOR_ADAPTER = TypeAdapter(ReleaseDescriptor)


def validate_release_descriptor(value: object) -> ReleaseDescriptor:
    return RELEASE_DESCRIPTOR_ADAPTER.validate_python(value)


def format_release_revision(revision: int) -> str:
    if isinstance(revision, bool) or not 1 <= revision <= 999:
        raise FoundryError("Release revision must be in the range 1..999.")
    return f"r{revision:03d}"
