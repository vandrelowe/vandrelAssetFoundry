from pydantic import BaseModel, ConfigDict, Field, model_validator


class LanePolicy(BaseModel):
    model_config = ConfigDict(extra="allow")

    wrapper_template: str
    target_triangles: int | None = None
    maximum_triangles: int | None = None
    collision_policy: str
    requires_materials: bool = True
    requires_skeleton: bool = False
    release_enabled: bool = True


class MeshBudgetProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_triangles: int = Field(gt=0)
    maximum_triangles: int = Field(gt=0)
    description: str = Field(min_length=1)

    @model_validator(mode="after")
    def target_must_not_exceed_maximum(self) -> "MeshBudgetProfile":
        if self.target_triangles > self.maximum_triangles:
            raise ValueError("mesh budget target_triangles must not exceed maximum_triangles")
        return self


class LaneConfiguration(BaseModel):
    lanes: dict[str, LanePolicy]
    mesh_budgets: dict[str, MeshBudgetProfile] = Field(default_factory=dict)
