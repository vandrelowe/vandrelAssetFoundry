import json
import math
import struct
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

Vec3 = tuple[float, float, float]


@dataclass
class _Primitive:
    positions: list[Vec3] = field(default_factory=list)
    normals: list[Vec3] = field(default_factory=list)
    indices: list[int] = field(default_factory=list)

    def vertex(self, position: Vec3, normal: Vec3) -> int:
        self.positions.append(position)
        self.normals.append(normal)
        return len(self.positions) - 1


def generate_fiddlehead_fern_glb(destination: Path) -> dict[str, int]:
    """Write one deterministic, very-low-poly fiddlehead fern GLB."""
    if destination.exists():
        raise FileExistsError(f"Procedural fern output already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    plant = _Primitive()
    soil = _Primitive()
    _add_soil_crown(soil)

    specifications = (
        (-1.42, 0.58, 0.66, False),
        (-1.00, 0.70, 0.82, False),
        (-0.55, 0.54, 0.70, True),
        (-0.12, 0.72, 0.94, False),
        (0.34, 0.59, 0.76, True),
        (0.76, 0.69, 0.84, False),
        (1.17, 0.58, 0.68, False),
        (2.48, 0.48, 0.56, False),
    )
    for index, (angle, reach, height, curled) in enumerate(specifications):
        _add_frond(plant, angle, reach, height, curled, index)

    _write_glb(destination, plant, soil)
    return {
        "vertices": len(plant.positions) + len(soil.positions),
        "triangles": (len(plant.indices) + len(soil.indices)) // 3,
        "fronds": len(specifications),
        "curled_fronds": sum(1 for item in specifications if item[3]),
    }


def generate_textured_fiddlehead_fern_glb(destination: Path) -> dict[str, int]:
    """Write a foliage-card fern with an embedded alpha-cutout frond texture."""
    if destination.exists():
        raise FileExistsError(f"Procedural fern output already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    cards = _Primitive()
    croziers = _Primitive()
    soil = _Primitive()
    card_uvs: list[tuple[float, float]] = []
    opened = (
        (-1.38, 0.50, 0.59, 0.090),
        (-1.01, 0.61, 0.73, 0.100),
        (-0.62, 0.69, 0.84, 0.108),
        (-0.20, 0.72, 0.91, 0.112),
        (0.24, 0.68, 0.83, 0.106),
        (0.70, 0.60, 0.71, 0.098),
        (1.18, 0.49, 0.57, 0.088),
    )
    for seed, (angle, reach, height, width) in enumerate(opened):
        _add_card_frond(cards, card_uvs, angle, reach, height, width, seed)
    _add_crozier(croziers, -0.05, 0.29, 0.52)
    _add_crozier(croziers, 0.51, 0.25, 0.44)
    _add_soil_crown(soil)
    texture = _make_frond_texture()
    _write_textured_glb(destination, cards, card_uvs, croziers, soil, texture)
    return {
        "vertices": len(cards.positions) + len(croziers.positions) + len(soil.positions),
        "triangles": (len(cards.indices) + len(croziers.indices) + len(soil.indices)) // 3,
        "opened_fronds": len(opened),
        "curled_fronds": 2,
        "texture_bytes": len(texture),
    }


def _add_card_frond(
    mesh: _Primitive,
    uvs: list[tuple[float, float]],
    angle: float,
    reach: float,
    height: float,
    maximum_width: float,
    seed: int,
) -> None:
    radial = (math.cos(angle), math.sin(angle), 0.0)
    side = (-radial[1], radial[0], 0.0)
    normal = _normalize(_cross(radial, (0.0, 0.0, 1.0)))
    rows: list[tuple[int, int]] = []
    segments = 6
    for step in range(segments + 1):
        t = step / segments
        bow = reach * (0.10 * t + 0.90 * t * t)
        sway = math.sin((seed + 2) * 1.33) * 0.015 * t * (1.0 - t)
        center = (
            radial[0] * bow + side[0] * sway,
            radial[1] * bow + side[1] * sway,
            0.028 + height * (t - 0.23 * t * t),
        )
        envelope = max(0.012, math.sin(math.pi * t) ** 0.84)
        half_width = maximum_width * envelope
        left = mesh.vertex(_add(center, _scale(side, half_width)), normal)
        uvs.append((0.0, 1.0 - t))
        right = mesh.vertex(_add(center, _scale(side, -half_width)), normal)
        uvs.append((1.0, 1.0 - t))
        rows.append((left, right))
    for step in range(segments):
        left_a, right_a = rows[step]
        left_b, right_b = rows[step + 1]
        mesh.indices.extend((left_a, right_a, right_b, left_a, right_b, left_b))


def _add_crozier(mesh: _Primitive, angle: float, reach: float, height: float) -> None:
    radial = (math.cos(angle), math.sin(angle), 0.0)
    points: list[Vec3] = []
    for step in range(9):
        t = step / 8
        bow = reach * (0.08 * t + 0.92 * t * t)
        points.append((radial[0] * bow, radial[1] * bow, 0.03 + height * (t - 0.20 * t * t)))
    base = points[-1]
    for step in range(1, 18):
        progress = step / 17
        theta = progress * math.tau * 0.72
        radius = 0.068 * (1.0 - 0.56 * progress)
        points.append(
            (
                base[0] + radial[0] * radius * math.sin(theta),
                base[1] + radial[1] * radius * math.sin(theta),
                base[2] + radius * (math.cos(theta) - 1.0),
            )
        )
    _add_tube(mesh, points, 0.008, 4)


def _make_frond_texture() -> bytes:
    scale = 2
    width, height = 256 * scale, 512 * scale
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    center = width // 2
    stem_dark = (49, 91, 33, 255)
    stem_light = (84, 126, 52, 255)
    greens = (
        (71, 118, 46, 255),
        (78, 128, 49, 255),
        (65, 109, 42, 255),
        (88, 136, 56, 255),
    )
    draw.line((center, height - 3, center, 7), fill=stem_dark, width=6 * scale)
    draw.line((center + scale, height - 4, center + scale, 8), fill=stem_light, width=2 * scale)
    for index in range(17):
        t = (index + 1) / 19
        y = round((1.0 - t) * (height - 28 * scale) + 11 * scale)
        envelope = math.sin(math.pi * t) ** 0.82
        irregular = 0.94 + 0.07 * math.sin(index * 2.31)
        leaflet_length = (13 + 87 * envelope) * irregular * scale
        leaflet_half_width = (3.2 + 7.5 * envelope) * scale
        upward = (10 + 14 * t) * scale
        for sign in (-1, 1):
            side_variation = 1.0 + sign * 0.035 * math.sin(index * 1.77)
            tip_x = center + sign * leaflet_length * side_variation
            tip_y = y - upward * (0.92 + 0.08 * math.cos(index * 1.31 + sign))
            base_x = center + sign * 2.5 * scale
            shoulder_x = center + sign * leaflet_length * 0.44
            color = greens[(index + (1 if sign > 0 else 0)) % len(greens)]
            polygon = (
                (base_x, y + leaflet_half_width * 0.46),
                (shoulder_x, y - leaflet_half_width),
                (tip_x, tip_y),
                (center + sign * leaflet_length * 0.36, y + leaflet_half_width),
                (base_x, y + leaflet_half_width * 0.25),
            )
            draw.polygon(polygon, fill=color)
            draw.line((base_x, y, tip_x, tip_y), fill=stem_light, width=scale)
    draw.polygon(
        ((center - 3 * scale, 12 * scale), (center, 0), (center + 3 * scale, 12 * scale)),
        fill=greens[1],
    )
    image = image.resize((256, 512), Image.Resampling.LANCZOS)
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _add_frond(
    mesh: _Primitive,
    angle: float,
    reach: float,
    height: float,
    curled: bool,
    seed: int,
) -> None:
    radial = (math.cos(angle), math.sin(angle), 0.0)
    side = (-radial[1], radial[0], 0.0)
    points: list[Vec3] = []
    straight_steps = 10 if curled else 12
    for step in range(straight_steps + 1):
        t = step / straight_steps
        bow = reach * (0.12 * t + 0.88 * t * t)
        sway = math.sin((seed + 1) * 1.7) * 0.018 * t * (1.0 - t)
        points.append(
            (
                radial[0] * bow + side[0] * sway,
                radial[1] * bow + side[1] * sway,
                0.032 + height * (t - 0.24 * t * t),
            )
        )
    if curled:
        base = points[-1]
        curl_radius = 0.072
        for step in range(1, 15):
            progress = step / 14
            theta = progress * math.tau * 0.68
            radius = curl_radius * (1.0 - 0.52 * progress)
            points.append(
                (
                    base[0] + radial[0] * radius * math.sin(theta),
                    base[1] + radial[1] * radius * math.sin(theta),
                    base[2] + radius * (math.cos(theta) - 1.0),
                )
            )
    _add_tube(mesh, points, 0.009, 5)

    leaflet_end = straight_steps - (1 if curled else 0)
    for step in range(4, leaflet_end):
        t = step / straight_steps
        center = points[step]
        tangent = _normalize(_subtract(points[step + 1], points[step - 1]))
        envelope = math.sin(math.pi * (t - 0.20) / 0.80)
        width = 0.008 + 0.021 * max(0.0, envelope)
        length = width * 2.15
        for sign in (-1.0, 1.0):
            offset = _scale(side, sign * width * 0.40)
            leaflet_center = _add(center, offset)
            outward = _normalize(_add(_scale(side, sign), _scale(tangent, 0.28)))
            _add_leaflet(mesh, leaflet_center, outward, tangent, length, width)

    if curled:
        for step in range(straight_steps + 2, len(points) - 1, 3):
            tangent = _normalize(_subtract(points[step + 1], points[step - 1]))
            width = 0.007
            for sign in (-1.0, 1.0):
                _add_leaflet(
                    mesh,
                    points[step],
                    _scale(side, sign),
                    tangent,
                    0.017,
                    width,
                )


def _add_tube(mesh: _Primitive, points: list[Vec3], radius: float, sides: int) -> None:
    rings: list[list[int]] = []
    for point_index, point in enumerate(points):
        before = points[max(0, point_index - 1)]
        after = points[min(len(points) - 1, point_index + 1)]
        tangent = _normalize(_subtract(after, before))
        reference = (0.0, 0.0, 1.0)
        if abs(_dot(tangent, reference)) > 0.92:
            reference = (1.0, 0.0, 0.0)
        axis_a = _normalize(_cross(tangent, reference))
        axis_b = _normalize(_cross(tangent, axis_a))
        taper = 1.0 - 0.38 * point_index / max(1, len(points) - 1)
        ring: list[int] = []
        for side_index in range(sides):
            theta = math.tau * side_index / sides
            normal = _normalize(
                _add(_scale(axis_a, math.cos(theta)), _scale(axis_b, math.sin(theta)))
            )
            ring.append(mesh.vertex(_add(point, _scale(normal, radius * taper)), normal))
        rings.append(ring)
    for ring_index in range(len(rings) - 1):
        for side_index in range(sides):
            a = rings[ring_index][side_index]
            b = rings[ring_index][(side_index + 1) % sides]
            c = rings[ring_index + 1][(side_index + 1) % sides]
            d = rings[ring_index + 1][side_index]
            mesh.indices.extend((a, b, c, a, c, d))


def _add_leaflet(
    mesh: _Primitive,
    center: Vec3,
    outward: Vec3,
    tangent: Vec3,
    length: float,
    width: float,
) -> None:
    normal = _normalize(_cross(outward, tangent))
    _add_leaflet_plane(mesh, center, outward, tangent, normal, length, width)
    _add_leaflet_plane(mesh, center, outward, normal, tangent, length, width * 0.72)


def _add_leaflet_plane(
    mesh: _Primitive,
    center: Vec3,
    outward: Vec3,
    width_axis: Vec3,
    normal: Vec3,
    length: float,
    width: float,
) -> None:
    base = _add(center, _scale(outward, -0.10 * length))
    tip = _add(center, _scale(outward, length))
    middle = _add(center, _scale(outward, length * 0.38))
    left = _add(middle, _scale(width_axis, width))
    right = _add(middle, _scale(width_axis, -width))
    indices = [mesh.vertex(point, normal) for point in (base, left, tip, right)]
    mesh.indices.extend((indices[0], indices[1], indices[2], indices[0], indices[2], indices[3]))


def _add_soil_crown(mesh: _Primitive) -> None:
    sides = 10
    top = mesh.vertex((0.0, 0.0, 0.035), (0.0, 0.0, 1.0))
    ring: list[int] = []
    for index in range(sides):
        theta = math.tau * index / sides
        normal = _normalize((math.cos(theta), math.sin(theta), 0.45))
        ring.append(mesh.vertex((0.115 * math.cos(theta), 0.115 * math.sin(theta), 0.0), normal))
    for index in range(sides):
        mesh.indices.extend((top, ring[index], ring[(index + 1) % sides]))


def _write_glb(destination: Path, plant: _Primitive, soil: _Primitive) -> None:
    binary = bytearray()
    buffer_views: list[dict[str, int]] = []
    accessors: list[dict[str, object]] = []
    primitives: list[dict[str, object]] = []
    for material, primitive in enumerate((plant, soil)):
        position_accessor = _append_vec3(binary, buffer_views, accessors, primitive.positions)
        normal_accessor = _append_vec3(binary, buffer_views, accessors, primitive.normals)
        index_accessor = _append_indices(binary, buffer_views, accessors, primitive.indices)
        primitives.append(
            {
                "attributes": {"POSITION": position_accessor, "NORMAL": normal_accessor},
                "indices": index_accessor,
                "material": material,
                "mode": 4,
            }
        )
    document = {
        "asset": {"version": "2.0", "generator": "Vandrel Foundry procedural fern v1"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": "FiddleheadFernClump"}],
        "meshes": [{"name": "FiddleheadFernClump", "primitives": primitives}],
        "materials": [
            {
                "name": "FernGreen",
                "doubleSided": True,
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.24, 0.48, 0.09, 1.0],
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.9,
                },
            },
            {
                "name": "SoilCrown",
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.20, 0.12, 0.055, 1.0],
                    "metallicFactor": 0.0,
                    "roughnessFactor": 1.0,
                },
            },
        ],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
        "extras": {
            "provenance": "Locally generated deterministic geometry; no provider model used.",
            "units": "meters",
            "frond_count": 8,
            "curled_frond_count": 2,
        },
    }
    raw_json = json.dumps(document, separators=(",", ":"), sort_keys=True).encode("utf-8")
    raw_json += b" " * (-len(raw_json) % 4)
    binary += b"\x00" * (-len(binary) % 4)
    total = 12 + 8 + len(raw_json) + 8 + len(binary)
    with destination.open("xb") as stream:
        stream.write(struct.pack("<4sII", b"glTF", 2, total))
        stream.write(struct.pack("<II", len(raw_json), 0x4E4F534A))
        stream.write(raw_json)
        stream.write(struct.pack("<II", len(binary), 0x004E4942))
        stream.write(binary)


def _write_textured_glb(
    destination: Path,
    cards: _Primitive,
    card_uvs: list[tuple[float, float]],
    croziers: _Primitive,
    soil: _Primitive,
    texture_png: bytes,
) -> None:
    binary = bytearray()
    buffer_views: list[dict[str, int]] = []
    accessors: list[dict[str, object]] = []
    primitives: list[dict[str, object]] = []

    card_positions = _append_vec3(binary, buffer_views, accessors, cards.positions)
    card_normals = _append_vec3(binary, buffer_views, accessors, cards.normals)
    card_texcoords = _append_vec2(binary, buffer_views, accessors, card_uvs)
    card_indices = _append_indices(binary, buffer_views, accessors, cards.indices)
    primitives.append(
        {
            "attributes": {
                "POSITION": card_positions,
                "NORMAL": card_normals,
                "TEXCOORD_0": card_texcoords,
            },
            "indices": card_indices,
            "material": 0,
            "mode": 4,
        }
    )
    for material, primitive in ((1, croziers), (2, soil)):
        positions = _append_vec3(binary, buffer_views, accessors, primitive.positions)
        normals = _append_vec3(binary, buffer_views, accessors, primitive.normals)
        indices = _append_indices(binary, buffer_views, accessors, primitive.indices)
        primitives.append(
            {
                "attributes": {"POSITION": positions, "NORMAL": normals},
                "indices": indices,
                "material": material,
                "mode": 4,
            }
        )
    binary.extend(b"\x00" * (-len(binary) % 4))
    texture_offset = len(binary)
    binary.extend(texture_png)
    buffer_views.append({"buffer": 0, "byteOffset": texture_offset, "byteLength": len(texture_png)})
    image_view = len(buffer_views) - 1
    document = {
        "asset": {"version": "2.0", "generator": "Vandrel Foundry foliage-card fern v2"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": "FiddleheadFernCardClump"}],
        "meshes": [{"name": "FiddleheadFernCardClump", "primitives": primitives}],
        "materials": [
            {
                "name": "FernFrondAlphaCutout",
                "doubleSided": True,
                "alphaMode": "MASK",
                "alphaCutoff": 0.45,
                "pbrMetallicRoughness": {
                    "baseColorTexture": {"index": 0},
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.92,
                },
            },
            {
                "name": "FernCrozierGreen",
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.24, 0.48, 0.09, 1.0],
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.9,
                },
            },
            {
                "name": "SoilCrown",
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.20, 0.12, 0.055, 1.0],
                    "metallicFactor": 0.0,
                    "roughnessFactor": 1.0,
                },
            },
        ],
        "samplers": [{"magFilter": 9729, "minFilter": 9987, "wrapS": 33071, "wrapT": 33071}],
        "textures": [{"sampler": 0, "source": 0}],
        "images": [{"bufferView": image_view, "mimeType": "image/png", "name": "frond_mask"}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
        "extras": {
            "provenance": "Locally generated deterministic geometry and RGBA texture; no provider model used.",
            "units": "meters",
            "construction": "gently curved tapered foliage cards with stylized alpha-mask texture",
            "opened_frond_count": 7,
            "curled_frond_count": 2,
        },
    }
    raw_json = json.dumps(document, separators=(",", ":"), sort_keys=True).encode("utf-8")
    raw_json += b" " * (-len(raw_json) % 4)
    binary += b"\x00" * (-len(binary) % 4)
    total = 12 + 8 + len(raw_json) + 8 + len(binary)
    with destination.open("xb") as stream:
        stream.write(struct.pack("<4sII", b"glTF", 2, total))
        stream.write(struct.pack("<II", len(raw_json), 0x4E4F534A))
        stream.write(raw_json)
        stream.write(struct.pack("<II", len(binary), 0x004E4942))
        stream.write(binary)


def _append_vec3(
    binary: bytearray,
    views: list[dict[str, int]],
    accessors: list[dict[str, object]],
    values: list[Vec3],
) -> int:
    offset = len(binary)
    for value in values:
        binary.extend(struct.pack("<3f", *value))
    views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(values) * 12})
    flat = list(zip(*values, strict=True))
    accessors.append(
        {
            "bufferView": len(views) - 1,
            "componentType": 5126,
            "count": len(values),
            "type": "VEC3",
            "min": [min(axis) for axis in flat],
            "max": [max(axis) for axis in flat],
        }
    )
    return len(accessors) - 1


def _append_vec2(
    binary: bytearray,
    views: list[dict[str, int]],
    accessors: list[dict[str, object]],
    values: list[tuple[float, float]],
) -> int:
    offset = len(binary)
    for value in values:
        binary.extend(struct.pack("<2f", *value))
    views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(values) * 8})
    flat = list(zip(*values, strict=True))
    accessors.append(
        {
            "bufferView": len(views) - 1,
            "componentType": 5126,
            "count": len(values),
            "type": "VEC2",
            "min": [min(axis) for axis in flat],
            "max": [max(axis) for axis in flat],
        }
    )
    return len(accessors) - 1


def _append_indices(
    binary: bytearray,
    views: list[dict[str, int]],
    accessors: list[dict[str, object]],
    values: list[int],
) -> int:
    binary.extend(b"\x00" * (-len(binary) % 4))
    offset = len(binary)
    for value in values:
        binary.extend(struct.pack("<I", value))
    views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(values) * 4})
    accessors.append(
        {
            "bufferView": len(views) - 1,
            "componentType": 5125,
            "count": len(values),
            "type": "SCALAR",
            "min": [min(values)],
            "max": [max(values)],
        }
    )
    return len(accessors) - 1


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _subtract(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _scale(value: Vec3, factor: float) -> Vec3:
    return (value[0] * factor, value[1] * factor, value[2] * factor)


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _normalize(value: Vec3) -> Vec3:
    length = math.sqrt(_dot(value, value))
    if length == 0.0:
        raise ValueError("Cannot normalize a zero-length vector.")
    return _scale(value, 1.0 / length)
