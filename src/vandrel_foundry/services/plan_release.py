import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.lanes import LaneConfiguration
from vandrel_foundry.domain.manifest import Artifact, AssetManifest
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import contained_path

RELEASE_ROLES = {
    "processed_model": ("model.glb", "model"),
    "godot_wrapper_scene": ("godot/wrapper.tscn", "godot_wrapper_scene"),
}
HUMANOID_LANE = "humanoid"
HUMANOID_COMPATIBILITY_CHECK = "humanoid_retarget_compatibility"


@dataclass(frozen=True)
class ReleasePlan:
    release_revision: int
    destination: Path
    descriptor: dict[str, Any]


def plan_release(
    config: FoundryConfig,
    lanes: LaneConfiguration,
    asset_id: str,
) -> ReleasePlan:
    manifest = ManifestRepository(config.foundry.workspace_root).load(asset_id)
    if manifest.workflow.state is not WorkflowState.APPROVED or not manifest.approval.approved:
        raise FoundryError(f"Release planning requires approved state: {asset_id}")
    lane = lanes.lanes.get(manifest.asset.lane)
    if lane is None or not lane.release_enabled:
        raise FoundryError(f"Release is disabled for lane: {manifest.asset.lane}")
    humanoid_compatibility = _humanoid_release_evidence(manifest)
    library_asset_root = config.foundry.asset_library_root / "assets" / asset_id
    revision = _next_revision(library_asset_root)
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    files: list[dict[str, Any]] = []
    for source_role, (release_path, release_role) in RELEASE_ROLES.items():
        approved_hash = manifest.approval.approved_artifact_hashes.get(source_role)
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
    godot_checks = [
        check for check in manifest.validation.checks if check.get("name") == "godot_sandbox_import"
    ]
    descriptor = {
        "schema_version": 1,
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
            **manifest.quality.observed,
            "collision_recommendation": lane.collision_policy,
        },
        **(
            {"humanoid_compatibility": humanoid_compatibility}
            if humanoid_compatibility is not None
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
    return ReleasePlan(
        release_revision=revision,
        destination=library_asset_root / f"r{revision:03d}",
        descriptor=descriptor,
    )


def _humanoid_release_evidence(manifest: AssetManifest) -> dict[str, Any] | None:
    if manifest.asset.lane != HUMANOID_LANE:
        return None
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
        raise FoundryError(
            "Humanoid release requires a passing humanoid retarget candidate check."
        )
    report = check.get("report")
    mapping_profile = check.get("mapping_profile")
    if not isinstance(report, str) or not report or not isinstance(mapping_profile, str):
        raise FoundryError("Humanoid release compatibility evidence is incomplete.")
    return {
        "candidate_only": True,
        "vandrel_runtime_accepted": False,
        "mapping_profile": mapping_profile,
        "report": report,
        "animation_donor_asset_id": check.get("animation_donor_asset_id"),
        "direct_skeleton_match": bool(check.get("direct_skeleton_match")),
        "direct_rest_transform_match": bool(check.get("direct_rest_transform_match")),
        "humanoid_retarget_candidate": True,
    }


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
    return max(revisions, default=0) + 1


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
