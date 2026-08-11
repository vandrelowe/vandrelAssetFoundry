from typing import Literal

from pydantic import Field, model_validator

from vandrel_foundry.domain.manifest import StrictModel


class MeshyNativeMultiMotionEntry(StrictModel):
    artifact_id: str = Field(min_length=1)
    role: Literal[
        "meshy_native_multi_animation_fbx",
        "meshy_native_multi_texture",
    ]
    archive_member: str = Field(min_length=1)
    archive_member_crc32: str = Field(pattern=r"^[a-f0-9]{8}$")
    exact_export_name: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=1)
    runtime_eligibility: Literal["identity_normalized", "provenance_only_legacy_outlier"]


class MeshyNativeMultiMotionIntakeReport(StrictModel):
    schema_name: Literal[
        "vandrel_foundry_meshy_native_multi_motion_intake/1.0",
        "vandrel_foundry_meshy_native_multi_motion_intake/1.1",
    ] = Field(alias="schema")
    package_number: int = Field(default=1, ge=1)
    source_qualifier: str = Field(default="fc7f5947", pattern=r"^[a-f0-9]{8}$")
    authority_basis: Literal["user_selected_local_source"]
    archive_original_name: str = Field(min_length=1)
    archive_artifact_id: str = Field(min_length=1)
    archive_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    archive_size_bytes: int = Field(ge=1)
    source_entry_count: int = Field(ge=1)
    animation_entry_count: int = Field(ge=1)
    texture_entry_count: int = Field(ge=1)
    entries: list[MeshyNativeMultiMotionEntry]
    provider_task_metadata: Literal["not_inspected"]
    license_metadata: Literal["not_inspected"]
    external_provider_lookup: Literal["not_performed_by_intake_service"]
    provider_download: Literal["not_performed_by_intake_service"]
    semantic_policy: Literal[
        "archive_names_are_provider_semantics_except_unresolved_uuids"
    ]
    gender_policy: Literal[
        "female_prefix_is_provenance_only_and_does_not_restrict_humanoid_use"
    ]
    permission_scope: Literal["local_unreleased_candidate_processing_only"]

    @model_validator(mode="after")
    def require_exact_package(self) -> "MeshyNativeMultiMotionIntakeReport":
        if self.schema_name.endswith("/1.0"):
            if (
                self.package_number != 1
                or self.source_entry_count != 21
                or self.animation_entry_count != 20
                or self.texture_entry_count != 1
                or len(self.entries) != 21
            ):
                raise ValueError("Meshy multi-motion 1.0 requires twenty FBXs and one texture")
        elif (
            self.source_entry_count != self.animation_entry_count + 1
            or self.texture_entry_count != 1
            or self.animation_entry_count < 1
            or len(self.entries) != self.source_entry_count
        ):
            raise ValueError("Meshy multi-motion 1.1 requires FBXs plus exactly one texture")
        artifact_ids = [entry.artifact_id for entry in self.entries]
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("Meshy multi-motion entry artifact IDs must be unique")
        animation_entries = [
            entry
            for entry in self.entries
            if entry.role == "meshy_native_multi_animation_fbx"
        ]
        texture_entries = [
            entry for entry in self.entries if entry.role == "meshy_native_multi_texture"
        ]
        if len(animation_entries) != self.animation_entry_count or len(texture_entries) != 1:
            raise ValueError("Meshy multi-motion entry roles do not match the exact package")
        legacy = [
            entry
            for entry in animation_entries
            if entry.runtime_eligibility == "provenance_only_legacy_outlier"
        ]
        if self.schema_name.endswith("/1.0") and (
            len(legacy) != 1
            or legacy[0].exact_export_name != "019fee70-fd9d-7b6e-914a-d6dad2a49eeb"
        ):
            raise ValueError("Meshy multi-motion 1.0 requires the exact known legacy outlier")
        if self.schema_name.endswith("/1.1") and any(
            entry.exact_export_name != "019fee70-fd9d-7b6e-914a-d6dad2a49eeb"
            for entry in legacy
        ):
            raise ValueError("Only the known legacy UUID may be provenance-only")
        return self
