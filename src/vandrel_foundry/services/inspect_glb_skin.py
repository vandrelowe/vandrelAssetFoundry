import hashlib
import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vandrel_foundry.domain.errors import FoundryError

_JSON_CHUNK = 0x4E4F534A
_BIN_CHUNK = 0x004E4942
_COMPONENTS = {
    5120: ("b", 1),
    5121: ("B", 1),
    5122: ("h", 2),
    5123: ("H", 2),
    5125: ("I", 4),
    5126: ("f", 4),
}
_WIDTHS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


@dataclass(frozen=True)
class GlbSkinProof:
    policy: str
    primitive_count: int
    vertex_count: int
    joint_weight_sets: tuple[str, ...]
    maximum_influences: int
    unweighted_vertex_count: int
    maximum_weight_sum_error: float
    skin_payload_sha256: str
    inverse_bind_matrices_sha256: str
    material_binding_sha256: str
    embedded_image_sha256s: tuple[str, ...]


def inspect_top4_glb_skin(path: Path) -> GlbSkinProof:
    document, binary = _load(path)
    accessors = _array(document, "accessors")
    views = _array(document, "bufferViews")
    nodes = _array(document, "nodes")
    meshes = _array(document, "meshes")
    skins = _array(document, "skins")
    if len(skins) != 1 or not isinstance(skins[0], dict):
        raise FoundryError("Top-four GLB proof requires exactly one skin.")
    skin = skins[0]
    joints = skin.get("joints")
    if not isinstance(joints, list) or len(joints) != 24:
        raise FoundryError("Top-four GLB proof requires exactly 24 skin joints.")
    if any(not isinstance(index, int) or not 0 <= index < len(nodes) for index in joints):
        raise FoundryError("Top-four GLB skin contains an invalid joint node reference.")
    joint_names = []
    for index in joints:
        node = nodes[index]
        name = node.get("name") if isinstance(node, dict) else None
        if not isinstance(name, str) or not name:
            raise FoundryError("Top-four GLB skin joint is unnamed.")
        joint_names.append(name)
    if len(set(joint_names)) != len(joint_names):
        raise FoundryError("Top-four GLB skin joint names are ambiguous.")
    inverse_index = skin.get("inverseBindMatrices")
    inverse = _accessor(document, binary, accessors, views, inverse_index)
    if len(inverse) != len(joints) or any(len(row) != 16 for row in inverse):
        raise FoundryError("Top-four GLB inverse bind matrices are incomplete.")
    inverse_signature = _signature(inverse)

    bound_meshes: dict[int, set[int]] = {}
    for node in nodes:
        if not isinstance(node, dict) or "mesh" not in node:
            continue
        mesh_index = node.get("mesh")
        skin_index = node.get("skin")
        if not isinstance(mesh_index, int) or not 0 <= mesh_index < len(meshes):
            raise FoundryError("Top-four GLB node references an invalid mesh.")
        if skin_index != 0:
            raise FoundryError("Every exported character mesh must use the intended skin.")
        bound_meshes.setdefault(mesh_index, set()).add(skin_index)
    if set(bound_meshes) != set(range(len(meshes))):
        raise FoundryError("Every exported character mesh must be bound to the intended skin.")

    records: list[dict[str, object]] = []
    material_bindings: list[dict[str, int]] = []
    weight_sets: set[str] = set()
    maximum_influences = 0
    unweighted = 0
    maximum_sum_error = 0.0
    primitive_count = 0
    for mesh_index, mesh in enumerate(meshes):
        primitives = mesh.get("primitives") if isinstance(mesh, dict) else None
        if not isinstance(primitives, list) or not primitives:
            raise FoundryError("Top-four GLB mesh has no primitives.")
        for primitive_index, primitive in enumerate(primitives):
            primitive_count += 1
            if not isinstance(primitive, dict):
                raise FoundryError("Top-four GLB primitive is invalid.")
            attributes = primitive.get("attributes")
            if not isinstance(attributes, dict):
                raise FoundryError("Top-four GLB primitive attributes are invalid.")
            skin_keys = sorted(
                key for key in attributes if key.startswith(("JOINTS_", "WEIGHTS_"))
            )
            if skin_keys != ["JOINTS_0", "WEIGHTS_0"]:
                raise FoundryError(
                    "Top-four GLB must contain exactly JOINTS_0 and WEIGHTS_0."
                )
            weight_sets.update(skin_keys)
            positions = _accessor(
                document, binary, accessors, views, attributes.get("POSITION")
            )
            joint_rows = _accessor(
                document, binary, accessors, views, attributes.get("JOINTS_0")
            )
            weight_rows = _accessor(
                document, binary, accessors, views, attributes.get("WEIGHTS_0")
            )
            if not (len(positions) == len(joint_rows) == len(weight_rows)):
                raise FoundryError("Top-four GLB skin accessor counts do not match.")
            material = primitive.get("material")
            if not isinstance(material, int):
                raise FoundryError("Top-four GLB primitive has no material binding.")
            material_bindings.append(
                {"mesh": mesh_index, "primitive": primitive_index, "material": material}
            )
            for position, joint_row, weight_row in zip(
                positions, joint_rows, weight_rows, strict=True
            ):
                if len(position) != 3 or len(joint_row) != 4 or len(weight_row) != 4:
                    raise FoundryError("Top-four GLB vertex accessor shape is invalid.")
                influences = []
                total = 0.0
                for joint, weight in zip(joint_row, weight_row, strict=True):
                    if not isinstance(joint, int) or not 0 <= joint < len(joint_names):
                        raise FoundryError("Top-four GLB vertex references an invalid joint.")
                    numeric_weight = float(weight)
                    if not math.isfinite(numeric_weight) or numeric_weight < 0:
                        raise FoundryError("Top-four GLB vertex contains an invalid weight.")
                    if numeric_weight > 1e-8:
                        influences.append((joint_names[joint], round(numeric_weight, 8)))
                        total += numeric_weight
                if not influences:
                    unweighted += 1
                maximum_influences = max(maximum_influences, len(influences))
                maximum_sum_error = max(maximum_sum_error, abs(total - 1.0))
                records.append(
                    {
                        "position": [round(float(value), 8) for value in position],
                        "influences": sorted(influences),
                    }
                )
    if unweighted or maximum_influences > 4 or maximum_sum_error > 1e-5:
        raise FoundryError(
            "Top-four GLB skin is unweighted, exceeds four influences, or is not normalized."
        )

    images = _array(document, "images")
    if not images:
        raise FoundryError("Top-four GLB has no embedded texture image.")
    image_hashes = []
    for image in images:
        if not isinstance(image, dict) or "uri" in image:
            raise FoundryError("Top-four GLB texture image must be embedded.")
        view_index = image.get("bufferView")
        image_hashes.append(hashlib.sha256(_view(binary, views, view_index)).hexdigest())
    material_value = {
        "primitive_bindings": material_bindings,
        "materials": _array(document, "materials"),
        "textures": _array(document, "textures"),
        "samplers": document.get("samplers", []),
        "image_hashes": image_hashes,
    }
    return GlbSkinProof(
        policy="deterministic_top4_normalized",
        primitive_count=primitive_count,
        vertex_count=len(records),
        joint_weight_sets=tuple(sorted(weight_sets)),
        maximum_influences=maximum_influences,
        unweighted_vertex_count=unweighted,
        maximum_weight_sum_error=maximum_sum_error,
        skin_payload_sha256=_signature(sorted(records, key=_canonical)),
        inverse_bind_matrices_sha256=inverse_signature,
        material_binding_sha256=_signature(material_value),
        embedded_image_sha256s=tuple(image_hashes),
    )


def require_matching_top4_skin(
    reference: GlbSkinProof, output: GlbSkinProof, texture_sha256: str
) -> None:
    exact_fields = (
        "policy",
        "primitive_count",
        "vertex_count",
        "joint_weight_sets",
        "maximum_influences",
        "unweighted_vertex_count",
        "skin_payload_sha256",
        "inverse_bind_matrices_sha256",
        "material_binding_sha256",
        "embedded_image_sha256s",
    )
    if any(getattr(reference, field) != getattr(output, field) for field in exact_fields):
        raise FoundryError(
            "Exported GLB skin, inverse binds, material bindings, or texture bytes differ "
            "from the deterministic pre-animation top-four reference."
        )
    if reference.joint_weight_sets != ("JOINTS_0", "WEIGHTS_0"):
        raise FoundryError("Exported GLB does not use the exact top-four joint/weight set.")
    if tuple(reference.embedded_image_sha256s) != (texture_sha256,):
        raise FoundryError("Exported GLB does not embed the exact bound source texture bytes.")


def _load(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise FoundryError(f"Could not read GLB skin evidence: {exc}") from exc
    if len(raw) < 20:
        raise FoundryError("GLB skin evidence is truncated.")
    magic, version, declared = struct.unpack_from("<4sII", raw, 0)
    if magic != b"glTF" or version != 2 or declared != len(raw):
        raise FoundryError("GLB skin evidence has an invalid header.")
    offset = 12
    json_bytes = None
    binary = None
    while offset < len(raw):
        if offset + 8 > len(raw):
            raise FoundryError("GLB skin evidence has a truncated chunk header.")
        length, kind = struct.unpack_from("<II", raw, offset)
        offset += 8
        end = offset + length
        if end > len(raw):
            raise FoundryError("GLB skin evidence has a truncated chunk.")
        if kind == _JSON_CHUNK:
            if json_bytes is not None:
                raise FoundryError("GLB skin evidence has duplicate JSON chunks.")
            json_bytes = raw[offset:end]
        elif kind == _BIN_CHUNK:
            if binary is not None:
                raise FoundryError("GLB skin evidence has duplicate BIN chunks.")
            binary = raw[offset:end]
        offset = end
    if json_bytes is None or binary is None:
        raise FoundryError("GLB skin evidence requires JSON and embedded BIN chunks.")
    try:
        document = json.loads(json_bytes.rstrip(b" \t\r\n\x00").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FoundryError(f"GLB skin JSON is invalid: {exc}") from exc
    if not isinstance(document, dict) or document.get("asset", {}).get("version") != "2.0":
        raise FoundryError("GLB skin JSON does not declare glTF 2.0.")
    return document, binary


def _accessor(document, binary, accessors, views, index):
    if not isinstance(index, int) or not 0 <= index < len(accessors):
        raise FoundryError("GLB skin accessor reference is invalid.")
    accessor = accessors[index]
    if not isinstance(accessor, dict) or "sparse" in accessor:
        raise FoundryError("GLB skin accessor is invalid or sparse.")
    view_index = accessor.get("bufferView")
    if not isinstance(view_index, int) or not 0 <= view_index < len(views):
        raise FoundryError("GLB skin accessor requires an embedded buffer view.")
    view = views[view_index]
    if not isinstance(view, dict) or view.get("buffer", 0) != 0:
        raise FoundryError("GLB skin buffer view is invalid.")
    component_type = accessor.get("componentType")
    kind = accessor.get("type")
    count = accessor.get("count")
    if component_type not in _COMPONENTS or kind not in _WIDTHS:
        raise FoundryError("GLB skin accessor component or shape is unsupported.")
    if not isinstance(count, int) or count < 0:
        raise FoundryError("GLB skin accessor count is invalid.")
    code, component_size = _COMPONENTS[component_type]
    width = _WIDTHS[kind]
    element_size = component_size * width
    stride = view.get("byteStride", element_size)
    if not isinstance(stride, int) or stride < element_size:
        raise FoundryError("GLB skin accessor stride is invalid.")
    base = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    view_length = view.get("byteLength")
    if not isinstance(base, int) or not isinstance(view_length, int):
        raise FoundryError("GLB skin accessor offsets are invalid.")
    view_start = view.get("byteOffset", 0)
    view_end = view_start + view_length
    normalized = bool(accessor.get("normalized", False))
    rows = []
    for row_index in range(count):
        start = base + (row_index * stride)
        end = start + element_size
        if start < view_start or end > view_end or end > len(binary):
            raise FoundryError("GLB skin accessor exceeds its embedded buffer view.")
        values = struct.unpack_from("<" + (code * width), binary, start)
        if normalized:
            values = tuple(_normalize(value, component_type) for value in values)
        if kind == "VEC4" and component_type in {5121, 5123} and not normalized:
            rows.append(tuple(int(value) for value in values))
        else:
            rows.append(tuple(float(value) for value in values))
    return rows


def _normalize(value, component_type):
    if component_type == 5120:
        return max(float(value) / 127.0, -1.0)
    if component_type == 5121:
        return float(value) / 255.0
    if component_type == 5122:
        return max(float(value) / 32767.0, -1.0)
    if component_type == 5123:
        return float(value) / 65535.0
    return float(value)


def _view(binary: bytes, views: list[Any], index: Any) -> bytes:
    if not isinstance(index, int) or not 0 <= index < len(views):
        raise FoundryError("GLB embedded image references an invalid buffer view.")
    view = views[index]
    if not isinstance(view, dict) or view.get("buffer", 0) != 0:
        raise FoundryError("GLB embedded image buffer view is invalid.")
    start = view.get("byteOffset", 0)
    length = view.get("byteLength")
    if not isinstance(start, int) or not isinstance(length, int):
        raise FoundryError("GLB embedded image offsets are invalid.")
    end = start + length
    if start < 0 or end > len(binary):
        raise FoundryError("GLB embedded image exceeds the BIN chunk.")
    return binary[start:end]


def _array(document: dict[str, Any], key: str) -> list[Any]:
    value = document.get(key, [])
    if not isinstance(value, list):
        raise FoundryError(f"GLB skin {key} must be an array.")
    return value


def _signature(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
