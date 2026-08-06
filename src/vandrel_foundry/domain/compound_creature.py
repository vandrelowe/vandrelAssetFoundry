from typing import Literal

from pydantic import Field, model_validator

from vandrel_foundry.domain.manifest import StrictModel
from vandrel_foundry.storage.paths import RelativeManifestPath

ContributionRole = Literal[
    "mesh_material_source", "material_dependency", "rig_animation_donor"
]


class CompoundContribution(StrictModel):
    artifact_id: str = Field(min_length=1)
    path: RelativeManifestPath
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=0)
    role: ContributionRole


class CompoundOutput(StrictModel):
    artifact_id: str
    path: RelativeManifestPath
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=0)


class CompoundCreatureReport(StrictModel):
    schema_name: Literal["vandrel_foundry_compound_creature/1.0"] = Field(alias="schema")
    processor_name: Literal["blender_compound_creature_derivation"]
    processor_version: str
    tool_version: str
    arguments: list[str]
    contributions: list[CompoundContribution]
    contribution_union: list[str]
    transformation_facts: dict[str, object]
    output: CompoundOutput

    @model_validator(mode="after")
    def validate_union(self) -> "CompoundCreatureReport":
        ids = [item.artifact_id for item in self.contributions]
        if len(ids) != len(set(ids)) or sorted(ids) != self.contribution_union:
            raise ValueError("contribution_union must exactly equal unique contribution IDs")
        roles = [item.role for item in self.contributions]
        if roles.count("mesh_material_source") != 1 or roles.count("rig_animation_donor") != 1:
            raise ValueError("compound report requires one primary mesh and one rig donor")
        if not any(item.role == "material_dependency" for item in self.contributions):
            raise ValueError("compound report requires material dependency roots")
        if not {
            "mesh_material_source",
            "material_dependency",
            "rig_animation_donor",
        }.issuperset(roles):
            raise ValueError("compound report has an unsupported contribution role")
        return self
