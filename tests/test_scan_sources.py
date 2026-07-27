import json
import os
from pathlib import Path

from vandrel_foundry.services.scan_sources import scan_source_directory


def test_scan_sources_classifies_and_bounds_external_models(tmp_path: Path) -> None:
    meshy = tmp_path / "Meshy" / "basket_texture_fbx"
    meshy.mkdir(parents=True)
    (meshy / "Basket.fbx").write_bytes(b"fbx")
    (meshy / "Basket.png").write_bytes(b"png")
    gltf_root = tmp_path / "Quaternius" / "glTF"
    gltf_root.mkdir(parents=True)
    (gltf_root / "Anvil.bin").write_bytes(b"bin")
    (gltf_root / "Metal.png").write_bytes(b"png")
    (gltf_root / "Unused.png").write_bytes(b"unused")
    (gltf_root / "Anvil.gltf").write_text(
        json.dumps(
            {
                "asset": {"version": "2.0"},
                "buffers": [{"uri": "Anvil.bin", "byteLength": 3}],
                "images": [{"uri": "Metal.png"}],
            }
        ),
        encoding="utf-8",
    )
    mixamo = tmp_path / "Mixamo"
    mixamo.mkdir()
    (mixamo / "Walking.fbx").write_bytes(b"fbx")

    candidates = scan_source_directory(tmp_path)
    by_name = {item.path.name: item for item in candidates}
    assert len(candidates) == 3
    assert by_name["Basket.fbx"].source_family == "meshy"
    assert by_name["Basket.fbx"].sidecar_count == 1
    assert by_name["Anvil.gltf"].source_family == "quaternius"
    assert by_name["Anvil.gltf"].sidecar_count == 2
    assert by_name["Walking.fbx"].suggested_lane == "humanoid"
    assert by_name["Walking.fbx"].suggested_asset_id == "walking"

    assert len(scan_source_directory(tmp_path, limit=2)) == 2

    linked = tmp_path / "linked.fbx"
    try:
        os.symlink(meshy / "Basket.fbx", linked)
    except (NotImplementedError, OSError):
        pass
    else:
        assert all(item.path != linked for item in scan_source_directory(tmp_path))


def test_scan_sources_disambiguates_duplicate_asset_ids(tmp_path: Path) -> None:
    first = tmp_path / "one"
    second = tmp_path / "two"
    first.mkdir()
    second.mkdir()
    (first / "Rock.fbx").write_bytes(b"first")
    (second / "Rock.fbx").write_bytes(b"second")

    candidates = scan_source_directory(tmp_path)

    ids = [candidate.suggested_asset_id for candidate in candidates]
    assert len(set(ids)) == 2
    assert all(value.startswith("rock_") and len(value) == 13 for value in ids)


def test_scan_sources_recognizes_named_humanoid_characters(tmp_path: Path) -> None:
    meshy = tmp_path / "Meshy"
    meshy.mkdir()
    (meshy / "Cave Female Athletic Chieftain.fbx").write_bytes(b"character")

    candidate = scan_source_directory(tmp_path)[0]

    assert candidate.source_family == "meshy"
    assert candidate.suggested_lane == "humanoid"
