"""Executable contracts for selective animation-only Asset Foundry releases."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Semantic = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")]

FIXED_PHASES = (0.0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875)
ANIMATION_IMPORT_POLICY = (
    "godot_skeleton_profile_humanoid_meshy_bone_map_rest_fixer_v1"
)


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnimationSourceRequest(ContractModel):
    semantic: Semantic
    source_path: str = Field(min_length=1)
    source_sha256: Sha256
    source_size_bytes: int = Field(gt=0)
    loop_mode: Literal["none", "linear"] = "none"


class ExcludedAnimationSource(ContractModel):
    semantic: Semantic
    source_sha256: Sha256
    reason: str = Field(min_length=1)


class AnimationPackagePolicy(ContractModel):
    schema_version: Literal["vandrel_foundry_animation_package_policy/1.0"]
    policy_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{2,127}$")
    exact_selected_source_sha256s: list[Sha256] = Field(min_length=1, max_length=64)
    exact_excluded_source_sha256s: list[Sha256] = Field(default_factory=list)
    forbidden_aggregate_payload_sha256s: list[Sha256] = Field(default_factory=list)
    superseded_route_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_disjoint_sets(self) -> AnimationPackagePolicy:
        if len(self.exact_selected_source_sha256s) != len(
            set(self.exact_selected_source_sha256s)
        ):
            raise ValueError("Package policy selected hashes must be unique.")
        if len(self.exact_excluded_source_sha256s) != len(
            set(self.exact_excluded_source_sha256s)
        ):
            raise ValueError("Package policy excluded hashes must be unique.")
        if set(self.exact_selected_source_sha256s) & set(
            self.exact_excluded_source_sha256s
        ):
            raise ValueError("Package policy selected and excluded hashes overlap.")
        return self


class AnimationLibraryIntakeRequest(ContractModel):
    schema_version: Literal["vandrel_foundry_animation_library_intake/1.0"]
    asset_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_]{2,63}$")
    motions: list[AnimationSourceRequest] = Field(min_length=1, max_length=64)
    explicit_exclusions: list[ExcludedAnimationSource] = Field(default_factory=list)
    import_policy: Literal[
        "godot_skeleton_profile_humanoid_meshy_bone_map_rest_fixer_v1"
    ]
    package_policy: AnimationPackagePolicy
    package_policy_sha256: Sha256

    @model_validator(mode="after")
    def exact_unique_membership(self) -> AnimationLibraryIntakeRequest:
        semantics = [item.semantic for item in self.motions]
        hashes = [item.source_sha256 for item in self.motions]
        excluded_semantics = [item.semantic for item in self.explicit_exclusions]
        excluded_hashes = [item.source_sha256 for item in self.explicit_exclusions]
        if len(semantics) != len(set(semantics)):
            raise ValueError("Animation semantics must be unique.")
        if len(hashes) != len(set(hashes)):
            raise ValueError("Animation source bytes must be unique.")
        if len(excluded_semantics) != len(set(excluded_semantics)):
            raise ValueError("Excluded animation semantics must be unique.")
        if len(excluded_hashes) != len(set(excluded_hashes)):
            raise ValueError("Excluded animation hashes must be unique.")
        if set(semantics) & set(excluded_semantics):
            raise ValueError("Selected and excluded semantics overlap.")
        if set(hashes) & set(excluded_hashes):
            raise ValueError("Selected and excluded source hashes overlap.")
        if hashes != self.package_policy.exact_selected_source_sha256s:
            raise ValueError("Selected sources differ from exact package policy order.")
        if excluded_hashes != self.package_policy.exact_excluded_source_sha256s:
            raise ValueError("Excluded sources differ from exact package policy order.")
        return self


class VisualEvidenceArtifact(ContractModel):
    path: str = Field(min_length=1)
    sha256: Sha256
    size_bytes: int = Field(gt=0)


class AnimationVisualCell(ContractModel):
    semantic: Semantic
    body_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_]{2,63}$")
    result: Literal["PASS", "FAIL"]
    observed_phases: list[float] = Field(min_length=8, max_length=8)
    evidence: list[VisualEvidenceArtifact] = Field(min_length=1)
    notes: str = ""

    @model_validator(mode="after")
    def exact_fixed_phases(self) -> AnimationVisualCell:
        if tuple(self.observed_phases) != FIXED_PHASES:
            raise ValueError("Visual evidence must use the exact eight fixed phases.")
        return self


class AnimationVisualBody(ContractModel):
    body_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_]{2,63}$")
    payload_sha256: Sha256


class AnimationVisualMatrixRequest(ContractModel):
    schema_version: Literal["vandrel_foundry_animation_visual_matrix/1.0"]
    asset_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_]{2,63}$")
    animation_library_sha256: Sha256
    technical_report_sha256: Sha256
    bodies: list[AnimationVisualBody] = Field(min_length=3, max_length=3)
    camera_policy: Literal["vandrel_fixed_animation_review_camera_v1"]
    camera_config_sha256: Sha256
    cells: list[AnimationVisualCell] = Field(min_length=3)
    reviewer: str = Field(min_length=1)
    reviewed_at: str = Field(min_length=1)

    @model_validator(mode="after")
    def unique_three_body_grid(self) -> AnimationVisualMatrixRequest:
        body_ids = [body.body_id for body in self.bodies]
        body_hashes = [body.payload_sha256 for body in self.bodies]
        if len(set(body_ids)) != 3 or len(set(body_hashes)) != 3:
            raise ValueError("Visual matrix requires three distinct body identities.")
        keys = [(cell.semantic, cell.body_id) for cell in self.cells]
        if len(keys) != len(set(keys)):
            raise ValueError("Visual matrix contains duplicate body-payload cells.")
        if any(cell.body_id not in body_ids for cell in self.cells):
            raise ValueError("Visual matrix cell references an undeclared body.")
        evidence_hashes = [
            evidence.sha256 for cell in self.cells for evidence in cell.evidence
        ]
        if len(evidence_hashes) != len(set(evidence_hashes)):
            raise ValueError(
                "Visual evidence SHA-256 values must be unique across semantic/body cells."
            )
        return self
