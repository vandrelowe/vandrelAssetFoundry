from pydantic import BaseModel, ConfigDict


class LanePolicy(BaseModel):
    model_config = ConfigDict(extra="allow")

    wrapper_template: str
    target_triangles: int | None = None
    maximum_triangles: int | None = None
    collision_policy: str
    requires_materials: bool = True
    requires_skeleton: bool = False
    release_enabled: bool = True


class LaneConfiguration(BaseModel):
    lanes: dict[str, LanePolicy]
