from pathlib import Path

import pytest

from vandrel_foundry.services.generate_procedural_fern import (
    generate_fiddlehead_fern_glb,
    generate_textured_fiddlehead_fern_glb,
)
from vandrel_foundry.services.inspect_glb import inspect_glb, load_glb_document


def test_generate_fiddlehead_fern_is_low_poly_and_structurally_valid(tmp_path: Path) -> None:
    output = tmp_path / "fern.glb"

    result = generate_fiddlehead_fern_glb(output)
    inspection = inspect_glb(output)
    document = load_glb_document(output)

    assert result["fronds"] == 8
    assert result["curled_fronds"] == 2
    assert result["triangles"] == inspection.triangle_count
    assert 0 < inspection.triangle_count < 2_000
    assert inspection.mesh_count == 1
    assert inspection.primitive_count == 2
    assert inspection.material_count == 2
    assert document["extras"]["units"] == "meters"
    assert document["extras"]["provenance"].startswith("Locally generated")


def test_generate_fiddlehead_fern_refuses_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "fern.glb"
    output.write_bytes(b"owned")

    with pytest.raises(FileExistsError, match="already exists"):
        generate_fiddlehead_fern_glb(output)

    assert output.read_bytes() == b"owned"


def test_generate_textured_fern_uses_alpha_cards_and_embedded_texture(
    tmp_path: Path,
) -> None:
    output = tmp_path / "fern_cards.glb"

    result = generate_textured_fiddlehead_fern_glb(output)
    inspection = inspect_glb(output)
    document = load_glb_document(output)

    assert result["opened_fronds"] == 6
    assert result["curled_fronds"] == 2
    assert result["triangles"] == inspection.triangle_count
    assert inspection.triangle_count < 500
    assert inspection.texture_count == 1
    assert inspection.image_count == 1
    assert inspection.material_count == 3
    assert document["materials"][0]["alphaMode"] == "MASK"
    assert document["materials"][0]["doubleSided"] is True
    assert document["images"][0]["mimeType"] == "image/png"
    assert document["extras"]["construction"] == "segmented foliage cards with alpha-mask texture"
