import json
import math
import struct
from dataclasses import dataclass, field
from pathlib import Path

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
