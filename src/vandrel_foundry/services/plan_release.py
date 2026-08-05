import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.custody import PortableCustodyPath
from vandrel_foundry.domain.custody_assertion import approval_custody_freshness
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.lanes import LaneConfiguration
from vandrel_foundry.domain.manifest import Artifact, AssetManifest
from vandrel_foundry.domain.release_descriptor import (
    ReleaseDescriptorV2,
    format_release_revision,
)
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import contained_path

RELEASE_ROLES = {
    "godot_wrapper_scene": ("godot/wrapper.tscn", "godot_wrapper_scene"),
    "godot_animation_loader_script": (
        "godot/animation_loader.gd",
        "godot_animation_loader_script",
    ),
    "processed_animation_walk": ("animations/walk.res", "animation_walk"),
    "processed_animation_run": ("animations/run.res", "animation_run"),
}
OPTIONAL_RELEASE_ROLES = {
    "godot_animation_loader_script",
    "processed_animation_walk",
    "processed_animation_run",
}
HUMANOID_LANE = "humanoid"
HUMANOID_COMPATIBILITY_CHECK = "humanoid_retarget_compatibility"
UNSAFE_RELEASE_COMPONENT = re.compile(r"[^a-zA-Z0-9._-]+")
PORTABLE_TECHNICAL_FIELDS = {
    "triangle_count",
    "mesh_count",
    "primitive_count",
    "material_count",
    "texture_count",
    "image_count",
    "skin_count",
    "joint_count",
    "animation_count",
    "visible_mesh_count",
    "visible_skinned_mesh_count",
    "visible_unskinned_mesh_count",
    "visible_skinned_triangle_count",
    "inspected_processed_artifact_id",
    "inspected_processed_sha256",
    "animation_source",
    "recommended_fbx_embedded_texture_handling",
}


@dataclass(frozen=True)
class ReleasePlan:
    release_revision: int
    destination: Path
    descriptor: dict[str, Any]

    def __post_init__(self) -> None:
        format_release_revision(self.release_revision)


def plan_release(
    config: FoundryConfig,
    lanes: LaneConfiguration,
    asset_id: str,
    *,
    release_revision: int | None = None,
) -> ReleasePlan:
    manifest = ManifestRepository(config.foundry.workspace_root).load(asset_id)
    if manifest.workflow.state is not WorkflowState.APPROVED or not manifest.approval.approved:
        raise FoundryError(f"Release planning requires approved state: {asset_id}")
    custody_fresh, custody_blockers = approval_custody_freshness(manifest)
    if not custody_fresh:
        raise FoundryError(
            "Release planning requires approved fresh custody: " + ", ".join(custody_blockers)
        )
    lane = lanes.lanes.get(manifest.asset.lane)
    if lane is None or not lane.release_enabled:
        raise FoundryError(f"Release is disabled for lane: {manifest.asset.lane}")
    library_asset_root = config.foundry.asset_library_root / "assets" / asset_id
    revision = _next_revision(library_asset_root) if release_revision is None else release_revision
    format_release_revision(revision)
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    files: list[dict[str, Any]] = []
    humanoid_compatibility, humanoid_report = _humanoid_release_evidence(
        manifest,
        asset_root,
    )
    model = _approved_artifact(manifest, asset_root, "processed_model")
    files.append(
        {
            "role": "model",
            "path": f"model.{model.format}",
            "sha256": model.sha256,
            "size_bytes": model.size_bytes,
            "source_artifact_id": model.artifact_id,
        }
    )
    for source_role, (release_path, release_role) in RELEASE_ROLES.items():
        approved_hash = manifest.approval.approved_artifact_hashes.get(source_role)
        if approved_hash is None and source_role in OPTIONAL_RELEASE_ROLES:
            continue
        candidates = [
            item
            for item in manifest.artifacts
            if item.role == source_role and item.sha256 == approved_hash
        ]
        if approved_hash is None or not candidates:
            raise FoundryError(f"Approved release artifact is unavailable: {source_role}")
        artifact = candidates[-1]
        _verify_artifact(asset_root, artifact)
        files.append(
            {
                "role": release_role,
                "path": release_path,
                "sha256": artifact.sha256,
                "size_bytes": artifact.size_bytes,
                "source_artifact_id": artifact.artifact_id,
            }
        )
    assert manifest.custody is not None
    evidence_release_paths: dict[str, str] = {}
    for contribution in manifest.custody.source_contributions:
        for evidence in contribution.license_evidence:
            if evidence.binding_id in evidence_release_paths:
                continue
            artifact = next(
                (
                    item
                    for item in manifest.artifacts
                    if item.artifact_id == evidence.candidate_evidence_artifact_id
                ),
                None,
            )
            if artifact is None:
                raise FoundryError(
                    f"Custody evidence artifact is unavailable: {evidence.binding_id}"
                )
            _verify_artifact(asset_root, artifact)
            suffix = f".{artifact.format}" if artifact.format else ".bin"
            safe_binding_id = UNSAFE_RELEASE_COMPONENT.sub("-", evidence.binding_id).strip(".-")
            if not safe_binding_id:
                safe_binding_id = "evidence"
            release_path = (
                f"custody/evidence/{safe_binding_id}-{evidence.evidence_sha256[:12]}{suffix}"
            )
            evidence_release_paths[evidence.binding_id] = release_path
            files.append(
                {
                    "role": "custody_license_evidence",
                    "path": release_path,
                    "sha256": artifact.sha256,
                    "size_bytes": artifact.size_bytes,
                    "source_artifact_id": artifact.artifact_id,
                }
            )
    if humanoid_report is not None:
        release_path = (
            f"evidence/humanoid/{humanoid_report.artifact_id}-{humanoid_report.sha256[:12]}.json"
        )
        files.append(
            {
                "role": "humanoid_compatibility_report",
                "path": release_path,
                "sha256": humanoid_report.sha256,
                "size_bytes": humanoid_report.size_bytes,
                "source_artifact_id": humanoid_report.artifact_id,
            }
        )
        assert humanoid_compatibility is not None
        humanoid_compatibility["report"] = {
            "release_path": release_path,
            "sha256": humanoid_report.sha256,
            "size_bytes": humanoid_report.size_bytes,
            "source_artifact_id": humanoid_report.artifact_id,
        }
    godot_checks = [
        check for check in manifest.validation.checks if check.get("name") == "godot_sandbox_import"
    ]
    if (
        manifest.custody.schema_version
        not in {
            "vandrel_foundry_candidate_custody/1.1",
            "vandrel_foundry_candidate_custody/1.2",
        }
        or manifest.custody.register_root_fingerprints is None
        or manifest.custody.evidence_fingerprint_sha256 is None
    ):
        raise FoundryError(
            "Release descriptor v2 requires current custody with freshness bindings."
        )
    descriptor_value = {
        "schema_version": 2,
        "asset_id": asset_id,
        "release_revision": revision,
        "display_name": manifest.asset.display_name,
        "lane": manifest.asset.lane,
        "files": files,
        "godot": {
            "import_validated": bool(godot_checks and godot_checks[-1].get("passed")),
            "wrapper_template": lane.wrapper_template,
        },
        "technical": {
            **{
                key: value
                for key, value in manifest.quality.observed.items()
                if key in PORTABLE_TECHNICAL_FIELDS
            },
            "collision_recommendation": lane.collision_policy,
        },
        "custody": {
            "schema_version": manifest.custody.schema_version,
            "assessment_status": manifest.custody.assessment_status,
            "effective_rights_status": manifest.custody.effective_rights_status,
            "semantic_assertion_sha256": manifest.custody.semantic_assertion_sha256,
            "policy": {
                "schema_version": manifest.custody.policy_schema_version,
                "sha256": manifest.custody.policy_sha256,
            },
            "register": {
                "schema_version": manifest.custody.register_schema_version,
                "sha256": manifest.custody.register_sha256,
                "root_fingerprints": manifest.custody.register_root_fingerprints,
            },
            "evidence_fingerprint_sha256": (manifest.custody.evidence_fingerprint_sha256),
            "evaluated_manifest_revision": manifest.custody.evaluated_manifest_revision,
            "source_contributions": [
                {
                    "contribution_id": contribution.contribution_id,
                    "source_id": contribution.source_id,
                    "package_id": contribution.package_id,
                    "package_root": _portable_custody_path(contribution.package_root),
                    "rights_status": contribution.rights_status,
                    "source_inputs": [
                        item.model_dump(mode="json") for item in contribution.source_inputs
                    ],
                    "license_evidence": [
                        {
                            "binding_id": evidence.binding_id,
                            "original_evidence_path": _portable_custody_path(
                                evidence.original_evidence_path
                            ),
                            "release_path": evidence_release_paths[evidence.binding_id],
                            "sha256": evidence.evidence_sha256,
                            "size_bytes": evidence.size_bytes,
                            "source_artifact_id": (evidence.candidate_evidence_artifact_id),
                            "scope_root": _portable_custody_path(evidence.scope_root),
                            "rights_semantics": evidence.rights_semantics,
                        }
                        for evidence in contribution.license_evidence
                    ],
                }
                for contribution in manifest.custody.source_contributions
            ],
        },
        **(
            {"humanoid_compatibility": humanoid_compatibility}
            if humanoid_compatibility is not None
            else {}
        ),
        **(
            {
                "scale_calibration": {
                    "processed_model_sha256": manifest.scale_calibration.processed_model_sha256,
                    "preview_report_sha256": manifest.scale_calibration.preview_report_sha256,
                    "source_bounds_min": manifest.scale_calibration.source_bounds_min,
                    "source_bounds_max": manifest.scale_calibration.source_bounds_max,
                    "source_dimensions": manifest.scale_calibration.source_dimensions,
                    "target_height_meters": manifest.scale_calibration.target_height_meters,
                    "baseline_uniform_scale": manifest.scale_calibration.baseline_uniform_scale,
                    "variation_min_multiplier": manifest.scale_calibration.variation_min_multiplier,
                    "variation_max_multiplier": manifest.scale_calibration.variation_max_multiplier,
                    "reference_standard": manifest.scale_calibration.reference_standard,
                    "reviewer": manifest.scale_calibration.reviewer,
                    "approved_at": manifest.scale_calibration.approved_at,
                    "notes": manifest.scale_calibration.notes,
                }
            }
            if manifest.scale_calibration.status == "approved"
            else {}
        ),
        "provenance": {
            "foundry_manifest_revision": manifest.revision,
            "approval_reviewer": manifest.approval.reviewer,
            "approved_at": (
                manifest.approval.approved_at.isoformat() if manifest.approval.approved_at else None
            ),
        },
    }
    try:
        descriptor = ReleaseDescriptorV2.model_validate(descriptor_value).model_dump(
            mode="json",
            exclude_none=True,
            by_alias=True,
        )
    except ValidationError as exc:
        raise FoundryError(f"Release descriptor v2 is invalid: {exc}") from exc
    return ReleasePlan(
        release_revision=revision,
        destination=library_asset_root / format_release_revision(revision),
        descriptor=descriptor,
    )


def _humanoid_release_evidence(
    manifest: AssetManifest,
    asset_root: Path,
) -> tuple[dict[str, Any] | None, Artifact | None]:
    if manifest.asset.lane != HUMANOID_LANE:
        return None, None
    native_checks = [
        check
        for check in manifest.validation.checks
        if check.get("name") == "provider_native_character_playback"
    ]
    if native_checks:
        check = native_checks[-1]
        approved_model_hash = manifest.approval.approved_artifact_hashes.get("processed_model")
        approved_walk_hash = manifest.approval.approved_artifact_hashes.get(
            "processed_animation_walk"
        )
        approved_run_hash = manifest.approval.approved_artifact_hashes.get(
            "processed_animation_run"
        )
        if (
            not check.get("passed")
            or not check.get("same_provider_task")
            or not check.get("skin_binding_passed")
            or check.get("processed_model_sha256") != approved_model_hash
            or check.get("walk_sha256") != approved_walk_hash
            or check.get("run_sha256") != approved_run_hash
        ):
            raise FoundryError(
                "Humanoid release requires passing hash-bound provider-native playback evidence."
            )
        report_artifact = _packaged_humanoid_report(manifest, asset_root, check.get("report"))
        return {
            "evidence_route": "provider_native_same_task",
            "candidate_only": True,
            "vandrel_runtime_accepted": False,
            "provider_native_same_task": True,
            "shared_animation_pool_compatible": False,
        }, report_artifact
    checks = [
        check
        for check in manifest.validation.checks
        if check.get("name") == HUMANOID_COMPATIBILITY_CHECK
    ]
    if not checks:
        raise FoundryError(
            "Humanoid release requires hash-bound humanoid retarget compatibility evidence."
        )
    check = checks[-1]
    if not check.get("passed") or not check.get("humanoid_retarget_candidate"):
        raise FoundryError("Humanoid release requires a passing humanoid retarget candidate check.")
    report = check.get("report")
    mapping_profile = check.get("mapping_profile")
    if not isinstance(report, str) or not report or not isinstance(mapping_profile, str):
        raise FoundryError("Humanoid release compatibility evidence is incomplete.")
    report_artifact = _packaged_humanoid_report(manifest, asset_root, report)
    return {
        "evidence_route": "retarget_mapping",
        "candidate_only": True,
        "vandrel_runtime_accepted": False,
        "mapping_profile": mapping_profile,
        "animation_donor_asset_id": check.get("animation_donor_asset_id"),
        "direct_skeleton_match": bool(check.get("direct_skeleton_match")),
        "direct_rest_transform_match": bool(check.get("direct_rest_transform_match")),
        "humanoid_retarget_candidate": True,
    }, report_artifact


def _next_revision(root: Path) -> int:
    if not root.is_dir():
        return 1
    revisions: list[int] = []
    try:
        entries = list(root.iterdir())
    except OSError as exc:
        raise FoundryError(f"Could not inspect asset-library revisions: {exc}") from exc
    for entry in entries:
        if entry.is_dir() and len(entry.name) == 4 and entry.name.startswith("r"):
            suffix = entry.name[1:]
            if suffix.isdigit():
                revisions.append(int(suffix))
    revision = max(revisions, default=0) + 1
    format_release_revision(revision)
    return revision


def _verify_artifact(asset_root: Path, artifact: Artifact) -> None:
    path = contained_path(asset_root, artifact.path)
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise FoundryError(
            f"Could not verify release artifact {artifact.artifact_id}: {exc}"
        ) from exc
    if digest.hexdigest() != artifact.sha256 or size != artifact.size_bytes:
        raise FoundryError(f"Approved release artifact changed: {artifact.artifact_id}")


def _approved_artifact(
    manifest: AssetManifest,
    asset_root: Path,
    role: str,
) -> Artifact:
    approved_hash = manifest.approval.approved_artifact_hashes.get(role)
    candidates = [
        item for item in manifest.artifacts if item.role == role and item.sha256 == approved_hash
    ]
    if approved_hash is None or not candidates:
        raise FoundryError(f"Approved release artifact is unavailable: {role}")
    artifact = candidates[-1]
    _verify_artifact(asset_root, artifact)
    return artifact


def _portable_custody_path(value: object) -> dict[str, str]:
    if not isinstance(value, PortableCustodyPath):
        raise FoundryError("Release descriptor v2 requires qualified custody paths.")
    return value.model_dump(mode="json")


def _packaged_humanoid_report(
    manifest: AssetManifest,
    asset_root: Path,
    report_path: object,
) -> Artifact:
    if not isinstance(report_path, str) or not report_path:
        raise FoundryError("Humanoid release compatibility report path is unavailable.")
    candidates = [
        artifact
        for artifact in manifest.artifacts
        if str(artifact.path) == report_path
        and artifact.role
        in {
            "humanoid_retarget_compatibility_report",
            "provider_native_character_report",
        }
    ]
    if not candidates:
        raise FoundryError(
            "Humanoid release compatibility report must be a manifest-owned artifact."
        )
    artifact = candidates[-1]
    _verify_artifact(asset_root, artifact)
    return artifact
