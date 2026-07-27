import hashlib
import importlib.resources
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.inspect_glb import load_glb_document
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path
from vandrel_foundry.storage.provider_evidence import write_new_json_evidence

VALIDATOR_VERSION = "2"
REST_TRANSFORM_TOLERANCE = 1e-5
PROFILE_RESOURCE = "rig_profiles/meshy_humanoid_v1.json"
ALLOWED_STATES = {
    WorkflowState.PROCESSED,
    WorkflowState.STAGED,
    WorkflowState.REVIEW,
    WorkflowState.APPROVED,
}


@dataclass(frozen=True)
class SkeletonFacts:
    joint_names: tuple[str, ...]
    parent_by_joint: dict[str, str]
    local_transform_by_joint: dict[str, tuple[float, ...]]
    animation_names: tuple[str, ...]
    animation_target_names: tuple[str, ...]


@dataclass(frozen=True)
class HumanoidRetargetResult:
    report: Artifact
    mapping_complete: bool
    hierarchy_valid: bool
    direct_skeleton_match: bool
    direct_rest_transform_match: bool
    humanoid_retarget_candidate: bool
    shared_animation_transfer_candidate: bool


def validate_humanoid_retarget(
    config: FoundryConfig,
    asset_id: str,
    animation_donor_asset_id: str,
) -> HumanoidRetargetResult:
    if asset_id == animation_donor_asset_id:
        raise FoundryError("Humanoid retarget validation requires a distinct animation donor.")
    repository = ManifestRepository(config.foundry.workspace_root)
    target_manifest = repository.load(asset_id)
    donor_manifest = repository.load(animation_donor_asset_id)
    if target_manifest.workflow.state not in ALLOWED_STATES:
        raise FoundryError(f"Humanoid retarget validation requires a processed asset: {asset_id}")
    if donor_manifest.workflow.state not in ALLOWED_STATES:
        raise FoundryError(
            "Humanoid retarget validation requires a processed animation donor: "
            f"{animation_donor_asset_id}"
        )

    target_artifact = _latest_processed(target_manifest.artifacts, asset_id)
    donor_artifact = _latest_processed(donor_manifest.artifacts, animation_donor_asset_id)
    target_root = config.foundry.workspace_root / "assets" / asset_id
    donor_root = config.foundry.workspace_root / "assets" / animation_donor_asset_id
    target_path = contained_path(target_root, target_artifact.path)
    donor_path = contained_path(donor_root, donor_artifact.path)
    _verify_artifact(target_path, target_artifact)
    _verify_artifact(donor_path, donor_artifact)

    profile, profile_sha256 = _load_profile()
    target_facts = extract_skeleton_facts(load_glb_document(target_path))
    donor_facts = extract_skeleton_facts(load_glb_document(donor_path))
    mapping = profile["profile_bones"]
    required_profile_bones = profile["required_profile_bones"]
    missing_required = sorted(
        profile_bone
        for profile_bone in required_profile_bones
        if mapping.get(profile_bone) not in target_facts.joint_names
    )
    missing_mapped_source = sorted(
        source_bone
        for source_bone in mapping.values()
        if source_bone not in target_facts.joint_names
    )
    hierarchy_errors = _hierarchy_errors(profile, target_facts)
    donor_hierarchy_errors = _hierarchy_errors(profile, donor_facts)
    target_joint_set = set(target_facts.joint_names)
    donor_joint_set = set(donor_facts.joint_names)
    direct_skeleton_match = (
        target_joint_set == donor_joint_set
        and target_facts.parent_by_joint == donor_facts.parent_by_joint
    )
    rest_transform_mismatches = joint_rest_transform_mismatches(target_facts, donor_facts)
    direct_rest_transform_match = direct_skeleton_match and not rest_transform_mismatches
    donor_unmapped_animation_targets = sorted(
        set(donor_facts.animation_target_names)
        - donor_joint_set
        - set(profile["allowed_animation_auxiliary_nodes"])
    )
    mapping_complete = not missing_required and not missing_mapped_source
    hierarchy_valid = not hierarchy_errors
    donor_compatible = (
        not donor_hierarchy_errors
        and bool(donor_facts.animation_names)
        and not donor_unmapped_animation_targets
    )
    retarget_candidate = mapping_complete and hierarchy_valid and donor_compatible
    transfer_candidate = (
        retarget_candidate and direct_skeleton_match and direct_rest_transform_match
    )

    report_number = _next_report_number(target_root)
    report_relative = RelativeManifestPath(
        f"reports/humanoid-retarget-compatibility-{report_number:03d}.json"
    )
    report_path = contained_path(target_root, report_relative)
    report_data = {
        "schema_version": 1,
        "validator": {
            "name": "humanoid_retarget_compatibility",
            "version": VALIDATOR_VERSION,
        },
        "mapping_profile": {
            "profile_id": profile["profile_id"],
            "profile_version": profile["profile_version"],
            "target": profile["target"],
            "resource": PROFILE_RESOURCE,
            "sha256": profile_sha256,
            "profile_bones": mapping,
        },
        "target": _artifact_binding(asset_id, target_artifact, target_facts),
        "animation_donor": _artifact_binding(animation_donor_asset_id, donor_artifact, donor_facts),
        "checks": {
            "mapping_complete": mapping_complete,
            "target_hierarchy_valid": hierarchy_valid,
            "donor_hierarchy_valid": not donor_hierarchy_errors,
            "donor_has_animations": bool(donor_facts.animation_names),
            "animation_targets_are_donor_joints": not donor_unmapped_animation_targets,
            "direct_skeleton_match": direct_skeleton_match,
            "direct_rest_transform_match": direct_rest_transform_match,
            "humanoid_retarget_candidate": retarget_candidate,
            "shared_animation_transfer_candidate": transfer_candidate,
        },
        "diagnostics": {
            "missing_required_profile_bones": missing_required,
            "missing_mapped_source_bones": missing_mapped_source,
            "target_hierarchy_errors": hierarchy_errors,
            "donor_hierarchy_errors": donor_hierarchy_errors,
            "donor_unmapped_animation_targets": donor_unmapped_animation_targets,
            "joint_rest_transform_mismatches": rest_transform_mismatches,
        },
        "authority": {
            "result_is": "Foundry technical compatibility evidence",
            "result_is_not": "Vandrel runtime skeleton or animation acceptance",
            "external_contract": "Vandrel docs/systems/ANIMATION_CONTRACT.md (read 2026-07-27)",
        },
        "limitations": [
            "Matching local joint rest transforms do not prove inverse-bind matrices or deformation quality.",
            "This check does not create a Vandrel runtime wrapper or animation library.",
            (
                "A retarget candidate with mismatched rest transforms requires a real "
                "retargeting step; raw animation-channel copying is unsafe."
            ),
            "Any produced animation still requires visual playback validation in the consumer.",
        ],
    }
    write_new_json_evidence(report_path, report_data)
    report_sha256, report_size = _hash_file(report_path)
    report_artifact = Artifact(
        artifact_id=f"humanoid_retarget_report_{report_number:03d}",
        role="humanoid_retarget_compatibility_report",
        stage="validation",
        format="json",
        path=report_relative,
        sha256=report_sha256,
        size_bytes=report_size,
        derived_from=[target_artifact.artifact_id],
        processor=Processor(name="humanoid_retarget_compatibility", version=VALIDATOR_VERSION),
    )
    target_manifest.artifacts.append(report_artifact)
    check = {
        "name": "humanoid_retarget_compatibility",
        "passed": retarget_candidate,
        "report": str(report_relative),
        "animation_donor_asset_id": animation_donor_asset_id,
        "mapping_profile": f"{profile['profile_id']}/v{profile['profile_version']}",
        "direct_skeleton_match": direct_skeleton_match,
        "direct_rest_transform_match": direct_rest_transform_match,
        "humanoid_retarget_candidate": retarget_candidate,
    }
    target_manifest.validation.checks = [
        existing
        for existing in target_manifest.validation.checks
        if existing.get("name") != "humanoid_retarget_compatibility"
    ]
    target_manifest.validation.checks.append(check)
    target_manifest.validation.result = (
        "passed"
        if all(bool(existing.get("passed")) for existing in target_manifest.validation.checks)
        else "failed"
    )
    target_manifest.revision += 1
    target_manifest.asset.updated_at = utc_now()
    repository.save(
        target_manifest,
        "asset.humanoid_retarget_validated",
        expected_revision=target_manifest.revision - 1,
    )
    return HumanoidRetargetResult(
        report=report_artifact,
        mapping_complete=mapping_complete,
        hierarchy_valid=hierarchy_valid,
        direct_skeleton_match=direct_skeleton_match,
        direct_rest_transform_match=direct_rest_transform_match,
        humanoid_retarget_candidate=retarget_candidate,
        shared_animation_transfer_candidate=transfer_candidate,
    )


def _latest_processed(artifacts: list[Artifact], asset_id: str) -> Artifact:
    candidates = [item for item in artifacts if item.role == "processed_model"]
    if not candidates:
        raise FoundryError(f"No processed GLB artifact exists: {asset_id}")
    artifact = candidates[-1]
    if artifact.format != "glb":
        raise FoundryError(f"Processed humanoid artifact is not GLB: {artifact.artifact_id}")
    return artifact


def _verify_artifact(path: Path, artifact: Artifact) -> None:
    digest, size = _hash_file(path)
    if digest != artifact.sha256 or size != artifact.size_bytes:
        raise FoundryError(f"Processed artifact hash or size changed: {artifact.artifact_id}")


def _load_profile() -> tuple[dict[str, Any], str]:
    resource = importlib.resources.files("vandrel_foundry.data").joinpath(PROFILE_RESOURCE)
    raw = resource.read_bytes()
    profile = json.loads(raw)
    if not isinstance(profile, dict) or profile.get("schema_version") != 1:
        raise FoundryError("Bundled humanoid mapping profile is invalid.")
    return profile, hashlib.sha256(raw).hexdigest()


def extract_skeleton_facts(document: dict[str, Any]) -> SkeletonFacts:
    nodes = document.get("nodes", [])
    skins = document.get("skins", [])
    animations = document.get("animations", [])
    if not isinstance(nodes, list) or not isinstance(skins, list) or not skins:
        raise FoundryError("Humanoid compatibility requires at least one GLB skin.")
    joint_indices: set[int] = set()
    for skin in skins:
        joints = skin.get("joints", []) if isinstance(skin, dict) else None
        if not isinstance(joints, list):
            raise FoundryError("GLB skin joints must be an array.")
        joint_indices.update(joints)
    names_by_index: dict[int, str] = {}
    for index in joint_indices:
        if not isinstance(index, int) or not 0 <= index < len(nodes):
            raise FoundryError("GLB skin contains an invalid joint reference.")
        node = nodes[index]
        name = node.get("name") if isinstance(node, dict) else None
        if not isinstance(name, str) or not name:
            raise FoundryError("Every humanoid joint must have a non-empty name.")
        if name in names_by_index.values():
            raise FoundryError(f"Humanoid joint names must be unique: {name}")
        names_by_index[index] = name
    parent_by_joint: dict[str, str] = {}
    for parent_index, parent_node in enumerate(nodes):
        children = parent_node.get("children", []) if isinstance(parent_node, dict) else []
        if not isinstance(children, list):
            raise FoundryError("GLB node children must be an array.")
        if parent_index not in names_by_index:
            continue
        for child_index in children:
            if child_index in names_by_index:
                parent_by_joint[names_by_index[child_index]] = names_by_index[parent_index]
    animation_names: list[str] = []
    target_names: set[str] = set()
    for number, animation in enumerate(animations, start=1):
        if not isinstance(animation, dict):
            raise FoundryError("GLB animation must be an object.")
        animation_names.append(str(animation.get("name") or f"animation_{number:03d}"))
        channels = animation.get("channels", [])
        if not isinstance(channels, list):
            raise FoundryError("GLB animation channels must be an array.")
        for channel in channels:
            target = channel.get("target", {}) if isinstance(channel, dict) else {}
            node_index = target.get("node") if isinstance(target, dict) else None
            if isinstance(node_index, int) and 0 <= node_index < len(nodes):
                node = nodes[node_index]
                name = node.get("name") if isinstance(node, dict) else None
                if isinstance(name, str) and name:
                    target_names.add(name)
    return SkeletonFacts(
        joint_names=tuple(sorted(names_by_index.values())),
        parent_by_joint=dict(sorted(parent_by_joint.items())),
        local_transform_by_joint={
            name: _node_local_matrix(nodes[index])
            for index, name in sorted(names_by_index.items(), key=lambda item: item[1])
        },
        animation_names=tuple(animation_names),
        animation_target_names=tuple(sorted(target_names)),
    )


def joint_rest_transform_mismatches(
    target: SkeletonFacts,
    donor: SkeletonFacts,
) -> list[str]:
    mismatches: list[str] = []
    for name in sorted(set(target.joint_names) & set(donor.joint_names)):
        target_matrix = target.local_transform_by_joint[name]
        donor_matrix = donor.local_transform_by_joint[name]
        if any(
            not math.isclose(left, right, rel_tol=0.0, abs_tol=REST_TRANSFORM_TOLERANCE)
            for left, right in zip(target_matrix, donor_matrix, strict=True)
        ):
            mismatches.append(name)
    return mismatches


def _node_local_matrix(node: Any) -> tuple[float, ...]:
    if not isinstance(node, dict):
        raise FoundryError("GLB joint node must be an object.")
    matrix = node.get("matrix")
    if matrix is not None:
        return _finite_vector(matrix, 16, "joint matrix")
    translation = _finite_vector(node.get("translation", [0.0, 0.0, 0.0]), 3, "translation")
    rotation = _finite_vector(node.get("rotation", [0.0, 0.0, 0.0, 1.0]), 4, "rotation")
    scale = _finite_vector(node.get("scale", [1.0, 1.0, 1.0]), 3, "scale")
    x, y, z, w = rotation
    sx, sy, sz = scale
    # glTF matrices are column-major; scale applies to the rotation columns.
    return (
        (1 - 2 * (y * y + z * z)) * sx,
        (2 * (x * y + z * w)) * sx,
        (2 * (x * z - y * w)) * sx,
        0.0,
        (2 * (x * y - z * w)) * sy,
        (1 - 2 * (x * x + z * z)) * sy,
        (2 * (y * z + x * w)) * sy,
        0.0,
        (2 * (x * z + y * w)) * sz,
        (2 * (y * z - x * w)) * sz,
        (1 - 2 * (x * x + y * y)) * sz,
        0.0,
        translation[0],
        translation[1],
        translation[2],
        1.0,
    )


def _finite_vector(value: Any, length: int, label: str) -> tuple[float, ...]:
    if not isinstance(value, list) or len(value) != length:
        raise FoundryError(f"GLB joint {label} must contain {length} numbers.")
    result: list[float] = []
    for item in value:
        if not isinstance(item, (int, float)) or isinstance(item, bool) or not math.isfinite(item):
            raise FoundryError(f"GLB joint {label} must contain finite numbers.")
        result.append(float(item))
    return tuple(result)


def _hierarchy_errors(profile: dict[str, Any], facts: SkeletonFacts) -> list[str]:
    mapping = profile["profile_bones"]
    errors: list[str] = []
    for child_profile, parent_profile in profile["expected_parent_profile_bones"].items():
        child_source = mapping[child_profile]
        parent_source = mapping[parent_profile]
        if child_source not in facts.joint_names or parent_source not in facts.joint_names:
            continue
        actual_parent = facts.parent_by_joint.get(child_source)
        if actual_parent != parent_source:
            errors.append(
                f"{child_profile} ({child_source}) parent is {actual_parent!r}, "
                f"expected {parent_profile} ({parent_source})"
            )
    return errors


def _artifact_binding(asset_id: str, artifact: Artifact, facts: SkeletonFacts) -> dict[str, Any]:
    return {
        "asset_id": asset_id,
        "artifact_id": artifact.artifact_id,
        "artifact_sha256": artifact.sha256,
        "artifact_size_bytes": artifact.size_bytes,
        "joint_count": len(facts.joint_names),
        "joint_names": list(facts.joint_names),
        "joint_parents": facts.parent_by_joint,
        "animation_count": len(facts.animation_names),
        "animation_names": list(facts.animation_names),
        "animation_target_names": list(facts.animation_target_names),
    }


def _next_report_number(asset_root: Path) -> int:
    number = 1
    while contained_path(
        asset_root,
        RelativeManifestPath(f"reports/humanoid-retarget-compatibility-{number:03d}.json"),
    ).exists():
        number += 1
    return number


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise FoundryError(f"Could not hash humanoid compatibility artifact {path}: {exc}") from exc
    return digest.hexdigest(), size
