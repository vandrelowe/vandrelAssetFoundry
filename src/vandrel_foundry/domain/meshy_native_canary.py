from typing import Literal

from pydantic import Field, model_validator

from vandrel_foundry.domain.manifest import StrictModel
from vandrel_foundry.storage.paths import RelativeManifestPath

EXPECTED_ACTION_COUNT = 10
EXPECTED_JOINT_COUNT = 24


class MeshyNativeSource(StrictModel):
    artifact_id: str = Field(min_length=1)
    role: Literal["meshy_native_archive", "meshy_native_animation_fbx"]
    path: RelativeManifestPath
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=1)


class MeshyNativeClip(StrictModel):
    exact_name: str = Field(min_length=1)
    frame_range: list[int] = Field(min_length=2, max_length=2)
    duration_seconds: float = Field(gt=0)
    root_baseline: list[float] = Field(min_length=3, max_length=3)
    root_displacement: float = Field(ge=0)
    sampled_ground_minimum_range: list[float] = Field(min_length=2, max_length=2)
    maximum_sampled_vertex_displacement: float = Field(gt=0)
    endpoint_loop_match: bool
    endpoint_matrix_max_delta: float = Field(ge=0)
    semantic_status: Literal["provider_named", "unresolved_uuid"]
    semantic_assessment: Literal[
        "locomotion_running",
        "locomotion_walking",
        "foraging_not_eating",
        "not_butchery",
        "unresolved",
        "other",
    ]


class MeshyNativeOutput(StrictModel):
    artifact_id: str
    path: RelativeManifestPath
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=1)


class MeshyNativeCanaryReport(StrictModel):
    schema_name: Literal["vandrel_foundry_meshy_native_canary/1.0"] = Field(alias="schema")
    processor_name: Literal["blender_meshy_native_normalization"]
    processor_version: str
    tool_version: str
    arguments: list[str]
    process: dict[str, object]
    process_log: MeshyNativeOutput
    sources: list[MeshyNativeSource]
    source_union: list[str]
    transformation_facts: dict[str, object]
    clips: list[MeshyNativeClip]
    combined_output: MeshyNativeOutput
    split_outputs: list[MeshyNativeOutput]

    @model_validator(mode="after")
    def validate_exact_shape(self) -> "MeshyNativeCanaryReport":
        source_ids = [item.artifact_id for item in self.sources]
        if len(source_ids) != 2 or sorted(source_ids) != self.source_union:
            raise ValueError("source_union must equal the two exact source roots")
        if {item.role for item in self.sources} != {
            "meshy_native_archive",
            "meshy_native_animation_fbx",
        }:
            raise ValueError("Meshy native report requires archive and FBX roots")
        clip_names = [item.exact_name for item in self.clips]
        if len(clip_names) != EXPECTED_ACTION_COUNT or len(set(clip_names)) != len(clip_names):
            raise ValueError("Meshy native report requires ten unique exact actions")
        if len(self.split_outputs) != EXPECTED_ACTION_COUNT:
            raise ValueError("Meshy native report requires one output for every action")
        return self


class MeshyNativeIntakeProvenanceCorrection(StrictModel):
    schema_name: Literal["vandrel_foundry_meshy_native_intake_provenance/1.0"] = Field(
        alias="schema"
    )
    supersedes_artifact_id: str = Field(min_length=1)
    source_union: list[str] = Field(min_length=2, max_length=2)
    provider_task_metadata: Literal["not_inspected"]
    license_metadata: Literal["not_inspected"]
    external_provider_lookup: Literal["not_performed_by_intake_service"]
    provider_download: Literal["not_performed_by_intake_service"]

    @model_validator(mode="after")
    def validate_roots(self) -> "MeshyNativeIntakeProvenanceCorrection":
        if sorted(self.source_union) != [
            "meshy_native_animation_fbx_root_001",
            "meshy_native_archive_root_001",
        ]:
            raise ValueError("Meshy native provenance correction requires the exact root union")
        return self
