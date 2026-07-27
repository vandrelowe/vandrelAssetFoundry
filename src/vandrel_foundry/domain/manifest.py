from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from vandrel_foundry.domain.ids import validate_asset_id
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.storage.paths import RelativeManifestPath


def utc_now() -> datetime:
    return datetime.now(UTC)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssetIdentity(StrictModel):
    asset_id: str
    display_name: str = Field(min_length=1)
    lane: str = Field(min_length=1)
    created_at: datetime
    updated_at: datetime

    def model_post_init(self, __context: Any, /) -> None:
        validate_asset_id(self.asset_id)


class Workflow(StrictModel):
    state: WorkflowState = WorkflowState.DRAFT
    blocked_reason: str | None = None
    last_error: str | None = None


class Input(StrictModel):
    kind: Literal["text"] = "text"
    prompt_file: RelativeManifestPath = RelativeManifestPath("input/prompt.txt")
    reference_images: list[RelativeManifestPath] = Field(default_factory=list)


class Generation(StrictModel):
    provider: str
    selected_task_key: str | None = None
    tasks: list["ProviderTask"] = Field(default_factory=list)


class ProviderTask(StrictModel):
    task_key: str
    provider: str
    operation: str
    provider_task_id: str | None = None
    attempt: int = Field(ge=1)
    status: str
    progress: int | None = Field(default=None, ge=0, le=100)
    request_path: RelativeManifestPath | None = None
    response_path: RelativeManifestPath | None = None
    submitted_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None


class Processor(StrictModel):
    name: str
    version: str


class Artifact(StrictModel):
    artifact_id: str
    role: str
    stage: str
    format: str
    path: RelativeManifestPath
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=0)
    derived_from: list[str] = Field(default_factory=list)
    processor: Processor | None = None


class Quality(StrictModel):
    targets: dict[str, Any] = Field(default_factory=dict)
    observed: dict[str, Any] = Field(default_factory=dict)


class Validation(StrictModel):
    result: Literal["not_run", "passed", "failed"] = "not_run"
    checks: list[dict[str, Any]] = Field(default_factory=list)


class Approval(StrictModel):
    approved: bool = False
    approved_at: datetime | None = None
    approved_artifact_hashes: dict[str, str] = Field(default_factory=dict)
    reviewer: str | None = None
    notes: str = ""


class Release(StrictModel):
    released: bool = False
    release_revision: int | None = None
    released_at: datetime | None = None


class AssetManifest(StrictModel):
    schema_version: Literal[1] = 1
    revision: int = Field(default=1, ge=1)
    asset: AssetIdentity
    workflow: Workflow = Field(default_factory=Workflow)
    input: Input = Field(default_factory=Input)
    generation: Generation
    artifacts: list[Artifact] = Field(default_factory=list)
    vandrel_technical: dict[str, Any] = Field(default_factory=dict)
    quality: Quality = Field(default_factory=Quality)
    validation: Validation = Field(default_factory=Validation)
    approval: Approval = Field(default_factory=Approval)
    release: Release = Field(default_factory=Release)
    notes: str = ""

    @classmethod
    def initial(cls, asset_id: str, display_name: str, lane: str, provider: str) -> "AssetManifest":
        now = utc_now()
        return cls(
            asset=AssetIdentity(
                asset_id=asset_id,
                display_name=display_name,
                lane=lane,
                created_at=now,
                updated_at=now,
            ),
            generation=Generation(provider=provider),
        )
