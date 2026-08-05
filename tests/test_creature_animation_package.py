import json
import struct
import zipfile
from pathlib import Path

import pytest

from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.services.inspect_creature_package import (
    inspect_creature_animation_package,
)


def _glb(joints: list[str], animation: str | None, rest_offset: float = 0.0) -> bytes:
    nodes = [
        {
            "name": name,
            "translation": [rest_offset + index, 0.0, 0.0],
            **({"children": [index + 1]} if index + 1 < len(joints) else {}),
        }
        for index, name in enumerate(joints)
    ]
    document = {
        "asset": {"version": "2.0"},
        "nodes": nodes,
        "skins": [{"joints": list(range(len(joints)))}],
        "accessors": [{"count": 3}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
    }
    if animation is not None:
        document["accessors"].append({"count": 2, "min": [0.0], "max": [1.25]})
        document["animations"] = [
            {"name": animation, "samplers": [{"input": 1, "output": 0}], "channels": []}
        ]
    payload = json.dumps(document, separators=(",", ":")).encode("utf-8")
    payload += b" " * (-len(payload) % 4)
    return (
        struct.pack("<4sII", b"glTF", 2, 20 + len(payload))
        + struct.pack("<II", len(payload), 0x4E4F534A)
        + payload
    )


def _package(
    path: Path,
    *,
    animated_joints: list[str] | None = None,
    run_offset: float = 0.0,
) -> None:
    animated_joints = animated_joints or ["body", "neck", "head"]
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "bear/animations/final_rig/bear.glb",
            _glb([*animated_joints, "head_end"], None, rest_offset=2.0),
        )
        for semantic in ("idle", "walk", "run"):
            archive.writestr(
                f"bear/animations/{semantic}/bear_{semantic}.glb",
                _glb(
                    animated_joints,
                    f"rig|{semantic}",
                    rest_offset=run_offset if semantic == "run" else 0.0,
                ),
            )


def test_reports_coherent_clips_without_claiming_original_rig_transfer(tmp_path: Path) -> None:
    archive = tmp_path / "bear.zip"
    _package(archive)

    profile = inspect_creature_animation_package(
        archive,
        "ursine",
        "anything_world_animate_anything",
        "anything_world_quadruped_v1",
    )

    assert profile.coherent_animation_set is True
    assert profile.direct_original_rig_transfer_compatible is False
    assert profile.base_extra_joint_names == ["head_end"]
    assert [clip.semantic for clip in profile.clips] == ["idle", "walk", "run"]
    assert all(clip.duration_seconds == 1.25 for clip in profile.clips)


def test_reports_incoherent_animation_rest_transforms(tmp_path: Path) -> None:
    archive = tmp_path / "bear.zip"
    _package(archive, run_offset=0.5)

    profile = inspect_creature_animation_package(
        archive,
        "ursine",
        "anything_world_animate_anything",
        "anything_world_quadruped_v1",
    )

    assert profile.animated_rest_transforms_match is False
    assert profile.coherent_animation_set is False


def test_rejects_missing_semantic_clip(tmp_path: Path) -> None:
    archive = tmp_path / "bear.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("bear/animations/final_rig/bear.glb", _glb(["body"], None))
        package.writestr("bear/animations/walk/bear.glb", _glb(["body"], "walk"))
        package.writestr("bear/animations/run/bear.glb", _glb(["body"], "run"))

    with pytest.raises(FoundryError, match="exactly one idle GLB"):
        inspect_creature_animation_package(archive, "ursine", "provider", "quadruped_v1")


def test_rejects_traversal_before_reading_models(tmp_path: Path) -> None:
    archive = tmp_path / "bear.zip"
    _package(archive)
    with zipfile.ZipFile(archive, "a") as package:
        package.writestr("../escape.glb", b"bad")

    with pytest.raises(FoundryError, match="unsafe path"):
        inspect_creature_animation_package(archive, "ursine", "provider", "quadruped_v1")
