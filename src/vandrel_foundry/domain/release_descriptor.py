"""Versioned executable contracts for historical and planned release descriptors."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from vandrel_foundry.domain.custody import LogicalRoot, PortableCustodyPath
from vandrel_foundry.domain.custody_assertion import evidence_freshness_sha256
from vandrel_foundry.domain.errors import FoundryError
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
    "godot_wrapper_scene",
    "godot_animation_loader_script",
    "animation_walk",
    "animation_run",
    "custody_license_evidence",
    "humanoid_compatibility_report",
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
    inspected_processed_artifact_id: Annotated[
        str,
        Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"),
    ] | None = None
    inspected_processed_sha256: Sha256 | None = None
    animation_source: Literal["meshy_same_rigging_task"] | None = None
    recommended_fbx_embedded_texture_handling: (
        Literal["embed_basis_universal"] | None
    ) = None
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
    schema_version: Literal["vandrel_foundry_custody_register/1.1"]
    sha256: Sha256
    root_fingerprints: Annotated[
        dict[LogicalRoot, Sha256],
        Field(min_length=3, max_length=3),
    ]

    @model_validator(mode="after")
    def complete_root_set(self) -> ReleaseCustodyRegisterV2:
        if set(self.root_fingerprints) != {
            "outside_assets",
            "foundry_workspace",
            "asset_library",
        }:
            raise ValueError("Release custody requires all three root fingerprints.")
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
    schema_version: Literal["vandrel_foundry_candidate_custody/1.1"]
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


HumanoidCompatibilityV2 = (
    RetargetHumanoidCompatibilityV2 | NativeHumanoidCompatibilityV2
)


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
    godot: ReleaseGodotV2
    technical: ReleaseTechnicalV2
    custody: ReleaseCustodyV2
    humanoid_compatibility: HumanoidCompatibilityV2 | None = None
    provenance: ReleaseProvenanceV2

    @model_validator(mode="after")
    def reconcile_packaged_evidence(self) -> ReleaseDescriptorV2:
        paths = [item.path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("Release file paths must be unique.")
        if sum(item.role == "model" for item in self.files) != 1:
            raise ValueError("Release descriptor requires exactly one model file.")
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
        return self


ReleaseDescriptor = ReleaseDescriptorV1 | ReleaseDescriptorV2
RELEASE_DESCRIPTOR_ADAPTER = TypeAdapter(ReleaseDescriptor)


def validate_release_descriptor(value: object) -> ReleaseDescriptor:
    return RELEASE_DESCRIPTOR_ADAPTER.validate_python(value)


def format_release_revision(revision: int) -> str:
    if isinstance(revision, bool) or not 1 <= revision <= 999:
        raise FoundryError("Release revision must be in the range 1..999.")
    return f"r{revision:03d}"
