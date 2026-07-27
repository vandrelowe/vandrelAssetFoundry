import hashlib
import json
import struct
from pathlib import Path

import pytest

from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.lanes import LaneConfiguration
from vandrel_foundry.domain.manifest import Artifact
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.inspect_assets import initialize_workspace
from vandrel_foundry.services.validate_humanoid_retarget import validate_humanoid_retarget
from vandrel_foundry.storage.manifests import ManifestRepository


def _write_glb(path: Path, document: dict) -> bytes:
    payload = json.dumps(document, separators=(",", ":")).encode("utf-8")
    payload += b" " * (-len(payload) % 4)
    content = (
        struct.pack("<4sII", b"glTF", 2, 20 + len(payload))
        + struct.pack("<II", len(payload), 0x4E4F534A)
        + payload
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return content


def _meshy_document(
    *,
    animations: int = 1,
    omit_joint: str | None = None,
    hips_y: float = 0.0,
) -> dict:
    names_and_children = [
        ("LeftToeBase", []),
        ("LeftFoot", [0]),
        ("LeftLeg", [1]),
        ("LeftUpLeg", [2]),
        ("RightToeBase", []),
        ("RightFoot", [4]),
        ("RightLeg", [5]),
        ("RightUpLeg", [6]),
        ("LeftHand", []),
        ("LeftForeArm", [8]),
        ("LeftArm", [9]),
        ("LeftShoulder", [10]),
        ("RightHand", []),
        ("RightForeArm", [12]),
        ("RightArm", [13]),
        ("RightShoulder", [14]),
        ("head_end", []),
        ("headfront", []),
        ("Head", [16, 17]),
        ("neck", [18]),
        ("Spine", [11, 15, 19]),
        ("Spine01", [20]),
        ("Spine02", [21]),
        ("Hips", [3, 7, 22]),
        ("Armature", [23]),
    ]
    nodes = [{"name": name, "children": children} for name, children in names_and_children]
    nodes[23]["translation"] = [0.0, hips_y, 0.0]
    joint_indices = [
        index for index, (name, _) in enumerate(names_and_children[:-1]) if name != omit_joint
    ]
    animation_values = []
    for number in range(animations):
        targets = [*joint_indices, 24]
        animation_values.append(
            {
                "name": f"clip_{number + 1}",
                "channels": [
                    {"sampler": 0, "target": {"node": index, "path": "rotation"}}
                    for index in targets
                ],
                "samplers": [],
            }
        )
    return {
        "asset": {"version": "2.0"},
        "nodes": nodes,
        "skins": [{"joints": joint_indices}],
        "animations": animation_values,
    }


def _add_processed_asset(
    config,
    lanes: LaneConfiguration,
    prompt: Path,
    asset_id: str,
    document: dict,
) -> None:
    manifest = create_asset(config, lanes, asset_id, "humanoid", asset_id, prompt)
    relative = "processed/passthrough/processed_glb_001.glb"
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    content = _write_glb(asset_root / relative, document)
    manifest.artifacts.append(
        Artifact(
            artifact_id="processed_glb_001",
            role="processed_model",
            stage="processed",
            format="glb",
            path=relative,
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
        )
    )
    manifest.workflow.state = WorkflowState.REVIEW
    manifest.validation.result = "passed"
    manifest.validation.checks = [{"name": "fixture_check", "passed": True}]
    manifest.revision += 1
    ManifestRepository(config.foundry.workspace_root).save(
        manifest, "fixture.processed", expected_revision=manifest.revision - 1
    )


@pytest.fixture
def humanoid_lanes() -> LaneConfiguration:
    return LaneConfiguration.model_validate(
        {
            "lanes": {
                "humanoid": {
                    "wrapper_template": "humanoid",
                    "collision_policy": "manual_review",
                    "requires_materials": True,
                    "requires_skeleton": True,
                }
            }
        }
    )


def test_records_hash_bound_meshy_humanoid_and_donor_compatibility(
    config, humanoid_lanes: LaneConfiguration, prompt: Path
) -> None:
    initialize_workspace(config.foundry.workspace_root)
    _add_processed_asset(
        config,
        humanoid_lanes,
        prompt,
        "meshy_character_001",
        _meshy_document(),
    )
    _add_processed_asset(
        config,
        humanoid_lanes,
        prompt,
        "meshy_animations_001",
        _meshy_document(animations=3),
    )

    result = validate_humanoid_retarget(config, "meshy_character_001", "meshy_animations_001")

    repository = ManifestRepository(config.foundry.workspace_root)
    saved = repository.load("meshy_character_001")
    report = json.loads(
        (
            config.foundry.workspace_root / "assets/meshy_character_001" / str(result.report.path)
        ).read_text(encoding="utf-8")
    )
    assert result.mapping_complete
    assert result.hierarchy_valid
    assert result.direct_skeleton_match
    assert result.direct_rest_transform_match
    assert result.humanoid_retarget_candidate
    assert result.shared_animation_transfer_candidate
    assert report["mapping_profile"]["profile_id"] == "meshy_humanoid"
    assert report["mapping_profile"]["profile_bones"]["Spine"] == "Spine02"
    assert report["animation_donor"]["animation_count"] == 3
    assert report["checks"]["direct_skeleton_match"]
    assert report["checks"]["direct_rest_transform_match"]
    assert report["authority"]["result_is_not"].startswith("Vandrel runtime")
    assert saved.workflow.state is WorkflowState.REVIEW
    assert saved.validation.result == "passed"
    check = next(
        item
        for item in saved.validation.checks
        if item["name"] == "humanoid_retarget_compatibility"
    )
    assert check["passed"]
    assert check["animation_donor_asset_id"] == "meshy_animations_001"


def test_incomplete_required_mapping_fails_closed(
    config, humanoid_lanes: LaneConfiguration, prompt: Path
) -> None:
    initialize_workspace(config.foundry.workspace_root)
    _add_processed_asset(
        config,
        humanoid_lanes,
        prompt,
        "incomplete_character_001",
        _meshy_document(omit_joint="LeftHand"),
    )
    _add_processed_asset(
        config,
        humanoid_lanes,
        prompt,
        "meshy_animations_001",
        _meshy_document(animations=2),
    )

    result = validate_humanoid_retarget(config, "incomplete_character_001", "meshy_animations_001")

    saved = ManifestRepository(config.foundry.workspace_root).load("incomplete_character_001")
    report = json.loads(
        (
            config.foundry.workspace_root
            / "assets/incomplete_character_001"
            / str(result.report.path)
        ).read_text(encoding="utf-8")
    )
    assert not result.mapping_complete
    assert not result.shared_animation_transfer_candidate
    assert report["diagnostics"]["missing_required_profile_bones"] == ["LeftHand"]
    assert saved.validation.result == "failed"


def test_rejects_hash_changed_donor(
    config, humanoid_lanes: LaneConfiguration, prompt: Path
) -> None:
    initialize_workspace(config.foundry.workspace_root)
    _add_processed_asset(config, humanoid_lanes, prompt, "meshy_character_001", _meshy_document())
    _add_processed_asset(config, humanoid_lanes, prompt, "meshy_animations_001", _meshy_document())
    donor = (
        config.foundry.workspace_root
        / "assets/meshy_animations_001/processed/passthrough/processed_glb_001.glb"
    )
    donor.write_bytes(donor.read_bytes() + b"changed")

    with pytest.raises(FoundryError, match="hash or size changed"):
        validate_humanoid_retarget(config, "meshy_character_001", "meshy_animations_001")


def test_rest_transform_mismatch_requires_retarget_instead_of_direct_transfer(
    config, humanoid_lanes: LaneConfiguration, prompt: Path
) -> None:
    initialize_workspace(config.foundry.workspace_root)
    _add_processed_asset(
        config,
        humanoid_lanes,
        prompt,
        "meshy_character_001",
        _meshy_document(hips_y=100.0),
    )
    _add_processed_asset(
        config,
        humanoid_lanes,
        prompt,
        "meshy_animations_001",
        _meshy_document(animations=2, hips_y=1.0),
    )

    result = validate_humanoid_retarget(config, "meshy_character_001", "meshy_animations_001")

    report = json.loads(
        (
            config.foundry.workspace_root / "assets/meshy_character_001" / str(result.report.path)
        ).read_text(encoding="utf-8")
    )
    assert result.direct_skeleton_match
    assert not result.direct_rest_transform_match
    assert result.humanoid_retarget_candidate
    assert not result.shared_animation_transfer_candidate
    assert report["diagnostics"]["joint_rest_transform_mismatches"] == ["Hips"]
    saved = ManifestRepository(config.foundry.workspace_root).load("meshy_character_001")
    assert saved.validation.result == "passed"
    check = next(
        item
        for item in saved.validation.checks
        if item["name"] == "humanoid_retarget_compatibility"
    )
    assert check["passed"]
