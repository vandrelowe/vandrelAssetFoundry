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
from vandrel_foundry.services.graft_animations import graft_animations
from vandrel_foundry.services.inspect_assets import initialize_workspace
from vandrel_foundry.services.inspect_glb import load_glb_document
from vandrel_foundry.storage.manifests import ManifestRepository


def _skeleton_nodes() -> list[dict]:
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
    return [{"name": name, "children": children} for name, children in names_and_children]


def _animated_glb(
    path: Path,
    animation_names: list[str],
    *,
    mismatch: bool = False,
    rest_mismatch: bool = False,
) -> bytes:
    nodes = _skeleton_nodes()
    if mismatch:
        nodes[8]["name"] = "DifferentLeftHand"
    if rest_mismatch:
        nodes[23]["translation"] = [0.0, 100.0, 0.0]
    binary = bytearray()
    buffer_views = []
    accessors = []
    animations = []
    for number, name in enumerate(animation_names):
        while len(binary) % 4:
            binary.append(0)
        input_offset = len(binary)
        input_bytes = struct.pack("<2f", 0.0, 1.0)
        binary.extend(input_bytes)
        input_view = len(buffer_views)
        buffer_views.append(
            {"buffer": 0, "byteOffset": input_offset, "byteLength": len(input_bytes)}
        )
        input_accessor = len(accessors)
        accessors.append(
            {
                "bufferView": input_view,
                "componentType": 5126,
                "count": 2,
                "type": "SCALAR",
                "min": [0.0],
                "max": [1.0],
            }
        )
        output_offset = len(binary)
        output_bytes = struct.pack("<8f", 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
        binary.extend(output_bytes)
        output_view = len(buffer_views)
        buffer_views.append(
            {"buffer": 0, "byteOffset": output_offset, "byteLength": len(output_bytes)}
        )
        output_accessor = len(accessors)
        accessors.append(
            {
                "bufferView": output_view,
                "componentType": 5126,
                "count": 2,
                "type": "VEC4",
            }
        )
        animations.append(
            {
                "name": name,
                "samplers": [
                    {
                        "input": input_accessor,
                        "output": output_accessor,
                        "interpolation": "LINEAR",
                    }
                ],
                "channels": [{"sampler": 0, "target": {"node": 23, "path": "rotation"}}],
                "extras": {"fixture_number": number},
            }
        )
    document = {
        "asset": {"version": "2.0"},
        "nodes": nodes,
        "skins": [{"joints": list(range(24))}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
        "animations": animations,
    }
    json_bytes = json.dumps(document, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * (-len(json_bytes) % 4)
    binary_bytes = bytes(binary) + b"\x00" * (-len(binary) % 4)
    total = 12 + 8 + len(json_bytes) + 8 + len(binary_bytes)
    content = (
        struct.pack("<4sII", b"glTF", 2, total)
        + struct.pack("<II", len(json_bytes), 0x4E4F534A)
        + json_bytes
        + struct.pack("<II", len(binary_bytes), 0x004E4942)
        + binary_bytes
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return content


def _lanes() -> LaneConfiguration:
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


def _asset(
    config,
    prompt: Path,
    asset_id: str,
    names: list[str],
    *,
    mismatch=False,
    rest_mismatch=False,
) -> Path:
    manifest = create_asset(config, _lanes(), asset_id, "humanoid", asset_id, prompt)
    relative = "processed/passthrough/processed_glb_001.glb"
    path = config.foundry.workspace_root / "assets" / asset_id / relative
    content = _animated_glb(
        path,
        names,
        mismatch=mismatch,
        rest_mismatch=rest_mismatch,
    )
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
    manifest.validation.checks = [{"name": "old_check", "passed": True}]
    manifest.approval.approved = True
    manifest.approval.approved_artifact_hashes = {"processed_model": "a" * 64}
    manifest.revision += 1
    ManifestRepository(config.foundry.workspace_root).save(
        manifest, "fixture.processed", expected_revision=manifest.revision - 1
    )
    return path


def test_graft_creates_immutable_processed_glb_and_resets_validation(config, prompt: Path) -> None:
    initialize_workspace(config.foundry.workspace_root)
    target_path = _asset(config, prompt, "target_character_001", ["TargetPose"])
    donor_path = _asset(config, prompt, "animation_donor_001", ["Walk", "Run"])
    target_before = target_path.read_bytes()
    donor_before = donor_path.read_bytes()

    result = graft_animations(config, "target_character_001", "animation_donor_001")

    saved = ManifestRepository(config.foundry.workspace_root).load("target_character_001")
    output_path = (
        config.foundry.workspace_root / "assets/target_character_001" / str(result.model.path)
    )
    output_document = load_glb_document(output_path)
    report = json.loads(
        (
            config.foundry.workspace_root / "assets/target_character_001" / str(result.report.path)
        ).read_text(encoding="utf-8")
    )
    assert target_path.read_bytes() == target_before
    assert donor_path.read_bytes() == donor_before
    assert [item["name"] for item in output_document["animations"]] == ["Walk", "Run"]
    assert result.facts.donor_animation_count == 2
    assert result.facts.target_animation_count == 1
    assert result.facts.output_animation_count == 2
    assert report["animation_donor"]["asset_id"] == "animation_donor_001"
    assert report["checks"]["exact_joint_names_and_hierarchy"]
    assert report["checks"]["exact_joint_rest_transforms"]
    assert saved.workflow.state is WorkflowState.PROCESSED
    assert saved.validation.result == "not_run"
    assert saved.validation.checks == []
    assert not saved.approval.approved
    assert saved.approval.approved_artifact_hashes == {}
    assert [item.role for item in saved.artifacts[-3:]] == [
        "processed_model",
        "animation_graft_report",
        "animation_graft_log",
    ]


def test_graft_rejects_nonidentical_skeleton_without_partial_output(config, prompt: Path) -> None:
    initialize_workspace(config.foundry.workspace_root)
    _asset(config, prompt, "target_character_001", ["TargetPose"])
    _asset(config, prompt, "animation_donor_001", ["Walk"], mismatch=True)

    with pytest.raises(FoundryError, match="exact joint-name"):
        graft_animations(config, "target_character_001", "animation_donor_001")

    asset_root = config.foundry.workspace_root / "assets/target_character_001"
    assert not (asset_root / "processed/animation_graft/processed_glb_002.glb").exists()
    assert not (asset_root / "reports/animation-graft-002.json").exists()


def test_graft_rejects_rest_transform_mismatch_without_partial_output(config, prompt: Path) -> None:
    initialize_workspace(config.foundry.workspace_root)
    _asset(config, prompt, "target_character_001", ["TargetPose"])
    _asset(
        config,
        prompt,
        "animation_donor_001",
        ["Walk"],
        rest_mismatch=True,
    )

    with pytest.raises(FoundryError, match="matching joint rest transforms"):
        graft_animations(config, "target_character_001", "animation_donor_001")

    asset_root = config.foundry.workspace_root / "assets/target_character_001"
    assert not (asset_root / "processed/animation_graft/processed_glb_002.glb").exists()
    assert not (asset_root / "reports/animation-graft-002.json").exists()


def test_graft_replaces_same_named_target_clip_with_donor_library(config, prompt: Path) -> None:
    initialize_workspace(config.foundry.workspace_root)
    _asset(config, prompt, "target_character_001", ["Walk"])
    _asset(config, prompt, "animation_donor_001", ["Walk"])

    result = graft_animations(config, "target_character_001", "animation_donor_001")

    output = config.foundry.workspace_root / "assets/target_character_001" / str(result.model.path)
    assert [item["name"] for item in load_glb_document(output)["animations"]] == ["Walk"]
