import json
import os
import struct
from pathlib import Path

import pytest

from vandrel_foundry.services.add_source import add_external_glb
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.inspect_assets import initialize_workspace
from vandrel_foundry.services.inspect_glb import inspect_glb
from vandrel_foundry.services.process_blender import process_with_blender


@pytest.mark.live_tool
def test_real_blender_processing_is_opt_in(config, lanes, prompt: Path) -> None:
    executable_value = os.environ.get("VANDREL_FOUNDRY_TEST_BLENDER")
    if not executable_value:
        pytest.skip("Set VANDREL_FOUNDRY_TEST_BLENDER for the opt-in Blender test.")
    executable = Path(executable_value)
    if not executable.is_file():
        pytest.skip(f"Configured Blender executable does not exist: {executable}")
    config.tools.blender_executable = executable
    initialize_workspace(config.foundry.workspace_root)
    create_asset(
        config,
        lanes,
        "blender_smoke_asset",
        "static_prop",
        "Blender Smoke Asset",
        prompt,
    )
    source = prompt.parent / "triangle.glb"
    _write_triangle_glb(source)
    add_external_glb(config, "blender_smoke_asset", source)

    artifact = process_with_blender(config, "blender_smoke_asset")
    output = config.foundry.workspace_root / "assets" / "blender_smoke_asset" / str(artifact.path)
    inspection = inspect_glb(output)
    assert inspection.triangle_count == 1
    assert artifact.processor is not None
    assert "blender-5.1.2" in artifact.processor.version


def _write_triangle_glb(path: Path) -> None:
    positions = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
    indices = struct.pack("<3H", 0, 1, 2)
    binary = positions + indices + b"\x00\x00"
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(positions), "target": 34962},
            {
                "buffer": 0,
                "byteOffset": len(positions),
                "byteLength": len(indices),
                "target": 34963,
            },
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 3,
                "type": "VEC3",
                "min": [0, 0, 0],
                "max": [1, 1, 0],
            },
            {
                "bufferView": 1,
                "componentType": 5123,
                "count": 3,
                "type": "SCALAR",
            },
        ],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "nodes": [{"mesh": 0}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    encoded = json.dumps(document, separators=(",", ":")).encode("utf-8")
    encoded += b" " * (-len(encoded) % 4)
    length = 12 + 8 + len(encoded) + 8 + len(binary)
    path.write_bytes(
        struct.pack("<4sII", b"glTF", 2, length)
        + struct.pack("<II", len(encoded), 0x4E4F534A)
        + encoded
        + struct.pack("<II", len(binary), 0x004E4942)
        + binary
    )
