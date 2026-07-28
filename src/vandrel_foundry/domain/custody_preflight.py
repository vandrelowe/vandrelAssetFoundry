"""Versioned evidence for the read-only custody readability preflight."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CustodyPreflightModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CustodyPrincipal(CustodyPreflightModel):
    account: str = Field(min_length=1)
    identifier: str = Field(min_length=1)
    platform: str = Field(min_length=1)
    resolution_status: Literal["exact", "unresolved"]


class CustodyPreflightSetupIssue(CustodyPreflightModel):
    code: Literal[
        "root_unavailable",
        "workspace_authority_mismatch",
        "roots_not_distinct",
        "principal_unresolved",
    ]
    logical_root: Literal["outside_assets", "foundry_workspace", "asset_library"] | None
    path: str | None
    detail: str = Field(min_length=1)


class CustodyReadabilityIssue(CustodyPreflightModel):
    logical_root: Literal["outside_assets", "foundry_workspace", "asset_library"]
    path: str = Field(min_length=1)
    operation: Literal["resolve", "enumerate", "stat", "open", "reparse"]
    error_type: str = Field(min_length=1)
    detail: str = Field(min_length=1)


class CustodyGovernedTarget(CustodyPreflightModel):
    kind: Literal["candidate", "release"]
    path: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    revision: str | None = None
    readable: bool
    issue_count: int = Field(ge=0)


class CustodyRootReadability(CustodyPreflightModel):
    logical_root: Literal["outside_assets", "foundry_workspace", "asset_library"]
    path: str = Field(min_length=1)
    readable: bool
    issue_count: int = Field(ge=0)


class CustodyReadabilityCounts(CustodyPreflightModel):
    roots: int = Field(ge=0)
    candidate_roots: int = Field(ge=0)
    release_roots: int = Field(ge=0)
    files_probed: int = Field(ge=0)
    directories_probed: int = Field(ge=0)
    unreadable_targets: int = Field(ge=0)
    setup_issues: int = Field(ge=0)


class CustodyReadabilityPreflight(CustodyPreflightModel):
    schema_version: Literal["vandrel_foundry_custody_readability_preflight/1.0"]
    generated_at: str
    status: Literal["passing", "blocked"]
    ready_for_inventory: bool
    principal: CustodyPrincipal
    roots: list[CustodyRootReadability]
    governed_targets: list[CustodyGovernedTarget]
    setup_issues: list[CustodyPreflightSetupIssue]
    unreadable_targets: list[CustodyReadabilityIssue]
    counts: CustodyReadabilityCounts
