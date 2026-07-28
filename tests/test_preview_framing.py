from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from vandrel_foundry.blender.preview_framing import fit_perspective_bounds
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.services.render_multi_angle_preview import _rendered_occupancy


def _box(width: float, depth: float, height: float):
    return [
        (x, y, z)
        for x in (-width / 2, width / 2)
        for y in (-depth / 2, depth / 2)
        for z in (-height / 2, height / 2)
    ]


@pytest.mark.parametrize(
    ("dimensions", "direction"),
    [
        ((0.2, 0.2, 2.0), (0.0, -1.0, 0.45)),
        ((3.0, 1.0, 1.0), (0.0, -1.0, 0.45)),
        ((3.0, 1.0, 1.0), (1.0, 0.0, 0.45)),
    ],
)
def test_perspective_fit_contains_all_bounds_with_useful_projected_span(dimensions, direction):
    solution = fit_perspective_bounds(
        _box(*dimensions),
        (0.0, 0.0, 0.0),
        direction,
        0.85,
        0.85,
    )

    left, right, bottom, top = solution.projected_bounds
    assert solution.distance > 0
    assert max(abs(value) for value in solution.projected_bounds) <= 0.88 + 1e-6
    assert max(right - left, top - bottom) >= 1.0


def test_framing_rejects_incomplete_or_degenerate_inputs():
    with pytest.raises(ValueError, match="at least one"):
        fit_perspective_bounds([], (0, 0, 0), (0, -1, 0), 0.85, 0.85)
    with pytest.raises(ValueError, match="nonzero"):
        fit_perspective_bounds(_box(1, 1, 1), (0, 0, 0), (0, 0, 0), 0.85, 0.85)


def test_rendered_occupancy_records_margins_and_no_crop(tmp_path: Path):
    path = tmp_path / "framed.png"
    image = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((10, 20, 89, 79), fill=(255, 0, 0, 255))
    image.save(path)

    facts = _rendered_occupancy(path)

    assert facts["alpha_bounding_box_pixels"] == [10, 20, 90, 80]
    assert facts["crop_margin_pixels"] == {
        "left": 10,
        "right": 10,
        "top": 20,
        "bottom": 20,
    }
    assert facts["no_crop"] is True
    assert facts["useful_occupancy"] is True


def test_rendered_occupancy_flags_boundary_contact_as_crop(tmp_path: Path):
    path = tmp_path / "cropped.png"
    image = Image.new("RGBA", (100, 100), (255, 0, 0, 255))
    image.save(path)

    facts = _rendered_occupancy(path)

    assert facts["no_crop"] is False


def test_rendered_occupancy_rejects_empty_foreground(tmp_path: Path):
    path = tmp_path / "empty.png"
    Image.new("RGBA", (32, 32), (0, 0, 0, 0)).save(path)

    with pytest.raises(FoundryError, match="no rendered foreground"):
        _rendered_occupancy(path)
