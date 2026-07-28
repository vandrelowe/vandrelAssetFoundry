"""Strict schema models for deterministic custody inventory."""

import re
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    WithJsonSchema,
    field_validator,
    model_validator,
)


class CustodyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


LogicalRoot = Literal["outside_assets", "foundry_workspace", "asset_library"]
PortablePathValue = Annotated[
    str,
    Field(min_length=1),
    WithJsonSchema(
        {
            "type": "string",
            "minLength": 1,
            "pattern": (
                r"^(?!/)(?![A-Za-z]:)(?!.*(?:^|/)\.\.?(?:/|$))"
                r"(?!.*\\)(?!.*//)[^/]+(?:/[^/]+)*$"
            ),
        }
    ),
]
Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class PortableCustodyPath(CustodyModel):
    logical_root: LogicalRoot
    path: PortablePathValue

    @field_validator("path")
    @classmethod
    def normalized_relative_posix(cls, value: str) -> str:
        pure = PurePosixPath(value)
        if (
            value == "."
            or pure.is_absolute()
            or value.startswith("//")
            or re.match(r"^[A-Za-z]:", value)
            or ".." in pure.parts
            or "\\" in value
            or str(pure) != value
        ):
            raise ValueError("Custody path must be normalized relative POSIX.")
        return value


class LicenseBindingPolicy(CustodyModel):
    binding_id: str = Field(min_length=1)
    evidence_path: str = Field(min_length=1)
    evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    scope_root: str = Field(min_length=1)
    rights_semantics: Literal["documented"]


class SourceRulePolicy(CustodyModel):
    source_id: str = Field(min_length=1)
    path_prefix: str = Field(min_length=1)
    package_mode: Literal["first_child", "loose_file"]


class PackagePolicy(CustodyModel):
    package_root: str = Field(min_length=1)
    rights_status: Literal["documented", "missing", "disputed"]
    license_binding_ids: list[str] = Field(default_factory=list)


class ExclusionPolicy(CustodyModel):
    logical_root: Literal["outside_assets"]
    path: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    hash_file: bool = False
    duplicate_participating: bool = False


class CustodyPolicy(CustodyModel):
    schema_version: Literal["vandrel_foundry_custody_policy/1.0"]
    scan_algorithm_version: Literal["vandrel_foundry_custody_scan/1.0"]
    source_rules: list[SourceRulePolicy]
    packages: list[PackagePolicy] = Field(default_factory=list)
    license_bindings: list[LicenseBindingPolicy] = Field(default_factory=list)
    exclusions: list[ExclusionPolicy] = Field(default_factory=list)
    workspace_temp_paths: list[str] = Field(default_factory=list)


RightsStatus = Literal["documented", "missing", "disputed"]
StorageClass = Literal[
    "candidate_manifest",
    "candidate_input",
    "manifest_recovery_history",
    "event_audit_log",
    "managed_manifest_artifact",
    "managed_historical_artifact",
    "generated_cache_or_temp",
    "operational_report",
    "unregistered_file",
]
V1_STORAGE_CLASSES = {
    "candidate_manifest",
    "managed_manifest_artifact",
    "generated_cache_or_temp",
    "unregistered_file",
}
V1_1_STORAGE_CLASSES = {
    "candidate_manifest",
    "candidate_input",
    "manifest_recovery_history",
    "event_audit_log",
    "managed_manifest_artifact",
    "managed_historical_artifact",
    "generated_cache_or_temp",
    "operational_report",
    "unregistered_file",
}


class OutsideFileRecord(CustodyModel):
    logical_root: Literal["outside_assets"] | None = None
    path: str
    entry_kind: Literal["regular_file"]
    size_bytes: int = Field(ge=0)
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    source_id: str | None
    mechanical_source_hint: str | None
    package_id: str
    package_root: str
    effective_rights_status: RightsStatus
    license_binding_ids: list[str]
    excluded: bool
    exclusion_reason: str | None
    exclusion_duplicate_participating: bool
    promotion_eligible: bool
    duplicate_set_id: str | None


class PackageRecord(CustodyModel):
    logical_root: Literal["outside_assets"] | None = None
    package_id: str
    package_root: str
    source_id: str | None
    rights_status: RightsStatus
    license_binding_ids: list[str]
    promotion_eligible: bool


class DuplicateSetRecord(CustodyModel):
    duplicate_set_id: str
    file_count: int = Field(ge=2)
    size_bytes_each: int = Field(ge=0)
    potential_duplicate_bytes: int = Field(ge=0)


class WorkspaceFileRecord(CustodyModel):
    logical_root: Literal["foundry_workspace"] | None = None
    path: str
    entry_kind: Literal["regular_file"]
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    asset_id: str | None
    storage_class: StorageClass


class CandidateIntegrity(CustodyModel):
    authority: Literal["audit_asset"]
    passed: bool


class WorkspaceCandidateRecord(CustodyModel):
    asset_id: str
    manifest_revision: int = Field(ge=1)
    workflow_state: str
    artifact_record_count: int = Field(ge=0)
    physical_file_count: int = Field(ge=0)
    physical_bytes: int = Field(ge=0)
    released_revision: int | None = Field(default=None, ge=1)
    storage_class_counts: dict[StorageClass, int]
    integrity: CandidateIntegrity
    retention_hold_reasons: list[
        Literal[
            "active_workflow",
            "approval_or_release_history",
            "rejected_evidence",
            "integrity_failure",
            "unregistered_content",
        ]
    ]
    deletability_claimed: Literal[False]


class CoverageRecord(CustodyModel):
    discovered_files: int = Field(ge=0)
    represented_files: int = Field(ge=0)
    excluded_files: int = Field(ge=0)
    reconciles: bool


class RegisterPolicyBinding(CustodyModel):
    schema_version: Literal["vandrel_foundry_custody_policy/1.0"]
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class RegisterCounts(CustodyModel):
    outside_files: int = Field(ge=0)
    workspace_files: int = Field(ge=0)
    packages: int = Field(ge=0)
    eligible_outside_files: int = Field(ge=0)
    duplicate_groups: int = Field(ge=0)
    duplicate_files: int = Field(ge=0)
    potential_duplicate_bytes: int = Field(ge=0)


class CustodyDefect(CustodyModel):
    kind: Literal["custody_ineligible"]
    logical_root: Literal["outside_assets"] | None = None
    path: str
    reason: RightsStatus


class CustodyRegister(CustodyModel):
    schema_version: Literal[
        "vandrel_foundry_custody_register/1.0",
        "vandrel_foundry_custody_register/1.1",
    ]
    scan_algorithm_version: Literal["vandrel_foundry_custody_scan/1.0"]
    roots: tuple[Literal["outside_assets"], Literal["foundry_workspace"]]
    root_fingerprints: Annotated[
        dict[LogicalRoot, Sha256],
        Field(min_length=3, max_length=3),
    ] | None = None
    policy: RegisterPolicyBinding
    outside_files: list[OutsideFileRecord]
    packages: list[PackageRecord]
    duplicate_sets: list[DuplicateSetRecord]
    workspace_files: list[WorkspaceFileRecord]
    workspace_candidates: list[WorkspaceCandidateRecord]
    coverage: dict[Literal["outside_assets", "foundry_workspace"], CoverageRecord]
    counts: RegisterCounts
    defects: list[CustodyDefect]

    @model_validator(mode="after")
    def versioned_path_and_classification_shape(self) -> "CustodyRegister":
        if self.schema_version.endswith("/1.0"):
            if self.root_fingerprints is not None or any(
                item.logical_root is not None
                for item in [*self.outside_files, *self.packages, *self.workspace_files, *self.defects]
            ):
                raise ValueError("Custody register 1.0 cannot carry 1.1 root qualifiers.")
            if any(item.storage_class not in V1_STORAGE_CLASSES for item in self.workspace_files):
                raise ValueError("Custody register 1.0 has an unsupported storage class.")
            return self
        expected_roots = {"outside_assets", "foundry_workspace", "asset_library"}
        if self.root_fingerprints is None or set(self.root_fingerprints) != expected_roots:
            raise ValueError("Custody register 1.1 requires all root fingerprints.")
        if any(not re.fullmatch(r"[a-f0-9]{64}", value) for value in self.root_fingerprints.values()):
            raise ValueError("Custody register root fingerprints must be SHA-256.")
        if any(item.logical_root != "outside_assets" for item in self.outside_files):
            raise ValueError("Outside records require the outside_assets logical root.")
        if any(item.logical_root != "outside_assets" for item in self.packages):
            raise ValueError("Package records require the outside_assets logical root.")
        if any(item.logical_root != "outside_assets" for item in self.defects):
            raise ValueError("Custody defects require the outside_assets logical root.")
        if any(item.logical_root != "foundry_workspace" for item in self.workspace_files):
            raise ValueError("Workspace records require the foundry_workspace logical root.")
        if any(item.storage_class not in V1_1_STORAGE_CLASSES for item in self.workspace_files):
            raise ValueError("Custody register 1.1 has an unsupported storage class.")
        for record in [*self.outside_files, *self.workspace_files]:
            PortableCustodyPath(
                logical_root=record.logical_root,
                path=record.path,
            )
        return self
