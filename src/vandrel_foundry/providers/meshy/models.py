from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from vandrel_foundry.domain.provider import ProviderTaskStatus


class MeshyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TextTo3DPreviewRequest(MeshyModel):
    mode: Literal["preview"] = "preview"
    prompt: str = Field(min_length=1, max_length=600)
    target_formats: list[Literal["glb"]] = Field(default_factory=lambda: ["glb"])


class TextTo3DRefineRequest(MeshyModel):
    mode: Literal["refine"] = "refine"
    preview_task_id: str = Field(min_length=1, max_length=1024)
    enable_pbr: bool = True
    target_formats: list[Literal["glb"]] = Field(default_factory=lambda: ["glb"])


class ImageTo3DRequest(MeshyModel):
    image_url: str = Field(min_length=1)
    target_formats: list[Literal["glb"]] = Field(default_factory=lambda: ["glb"])


class RemeshRequest(MeshyModel):
    input_task_id: str = Field(min_length=1, max_length=1024)
    target_formats: list[Literal["glb"]] = Field(default_factory=lambda: ["glb"])
    topology: Literal["triangle", "quad"] = "triangle"
    target_polycount: int = Field(ge=1)


class CreateTaskResponse(MeshyModel):
    result: str = Field(min_length=1, max_length=1024)


class TaskError(MeshyModel):
    type: str | None = None
    code: str | None = None
    message: str
    doc_url: str | None = None


class TextTo3DTaskResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1, max_length=1024)
    type: str | None = None
    status: ProviderTaskStatus
    progress: int = Field(ge=0, le=100)
    model_urls: dict[str, str] = Field(default_factory=dict)
    thumbnail_url: str | None = None
    task_error: TaskError | dict[str, Any] | None = None


class ImageTo3DTaskResponse(TextTo3DTaskResponse):
    pass


class RemeshTaskResponse(TextTo3DTaskResponse):
    pass
