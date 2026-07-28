import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.lanes import LaneConfiguration
from vandrel_foundry.domain.manifest import utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path
from vandrel_foundry.storage.provider_evidence import write_new_json_evidence

GLB_MAGIC = b"glTF"
GLB_JSON_CHUNK = 0x4E4F534A
MAX_GLB_JSON_BYTES = 64 * 1024 * 1024
TECHNICAL_CHECK_NAMES = {
    "glb_structure",
    "triangle_budget",
    "geometry_present",
    "materials_required",
    "skeleton_required",
}


@dataclass(frozen=True)
class GlbInspection:
    triangle_count: int
    mesh_count: int
    primitive_count: int
    material_count: int
    texture_count: int
    image_count: int
    skin_count: int
    joint_count: int
    animation_count: int


def inspect_processed_glb(
    config: FoundryConfig,
    lanes: LaneConfiguration,
    asset_id: str,
) -> GlbInspection:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.workflow.state not in {WorkflowState.PROCESSED, WorkflowState.REVIEW}:
        raise FoundryError(f"GLB inspection requires processed or review state: {asset_id}")
    candidates = [item for item in manifest.artifacts if item.role == "processed_model"]
    if not candidates:
        raise FoundryError(f"No processed GLB artifact exists: {asset_id}")
    artifact = candidates[-1]
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    inspection = inspect_glb(contained_path(asset_root, artifact.path))
    lane = lanes.lanes.get(manifest.asset.lane)
    if lane is None:
        raise FoundryError(f"Lane policy is unavailable: {manifest.asset.lane}")
    maximum = lane.maximum_triangles
    geometry_ok = inspection.mesh_count > 0 and inspection.primitive_count > 0
    triangle_ok = maximum is None or inspection.triangle_count <= maximum
    materials_ok = not lane.requires_materials or inspection.material_count > 0
    skeleton_ok = not lane.requires_skeleton or (
        inspection.skin_count > 0 and inspection.joint_count > 0
    )
    checks = [
        {
            "name": "glb_structure",
            "passed": True,
            "detail": "GLB 2.0 JSON structure parsed successfully.",
        },
        {
            "name": "triangle_budget",
            "passed": triangle_ok,
            "observed": inspection.triangle_count,
            "maximum": maximum,
        },
        {
            "name": "geometry_present",
            "passed": geometry_ok,
            "observed_meshes": inspection.mesh_count,
            "observed_primitives": inspection.primitive_count,
        },
        {
            "name": "materials_required",
            "passed": materials_ok,
            "observed": inspection.material_count,
            "required": lane.requires_materials,
        },
        {
            "name": "skeleton_required",
            "passed": skeleton_ok,
            "observed_skins": inspection.skin_count,
            "observed_joints": inspection.joint_count,
            "required": lane.requires_skeleton,
        },
    ]
    report = {
        "schema_version": 1,
        "asset_id": asset_id,
        "artifact_id": artifact.artifact_id,
        "artifact_sha256": artifact.sha256,
        "lane": manifest.asset.lane,
        "inspection": inspection.__dict__,
        "checks": checks,
    }
    report_relative = _next_report_path(asset_root)
    write_new_json_evidence(contained_path(asset_root, report_relative), report)
    manifest.quality.observed.update(inspection.__dict__)
    manifest.quality.observed["inspected_processed_artifact_id"] = artifact.artifact_id
    manifest.quality.observed["inspected_processed_sha256"] = artifact.sha256
    retained_checks = [
        check
        for check in manifest.validation.checks
        if str(check.get("name")) not in TECHNICAL_CHECK_NAMES
    ]
    manifest.validation.checks = [*checks, *retained_checks]
    manifest.validation.result = (
        "passed"
        if geometry_ok
        and triangle_ok
        and materials_ok
        and skeleton_ok
        and all(bool(check.get("passed")) for check in retained_checks)
        else "failed"
    )
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    repository.save(
        manifest,
        "asset.inspected",
        expected_revision=manifest.revision - 1,
    )
    return inspection


def inspect_glb(path: Path) -> GlbInspection:
    return _measure(load_glb_document(path))


def load_glb_document(path: Path) -> dict[str, Any]:
    """Load and validate the bounded JSON document from a GLB 2.0 container."""
    try:
        with path.open("rb") as stream:
            header = stream.read(12)
            if len(header) != 12:
                raise FoundryError("GLB header is truncated.")
            magic, version, declared_length = struct.unpack("<4sII", header)
            if magic != GLB_MAGIC or version != 2:
                raise FoundryError("Artifact is not a GLB 2.0 file.")
            actual_length = path.stat().st_size
            if declared_length != actual_length:
                raise FoundryError(
                    f"GLB length mismatch: header={declared_length}, file={actual_length}"
                )
            chunk_header = stream.read(8)
            if len(chunk_header) != 8:
                raise FoundryError("GLB JSON chunk header is missing.")
            chunk_length, chunk_type = struct.unpack("<II", chunk_header)
            if chunk_type != GLB_JSON_CHUNK or chunk_length > MAX_GLB_JSON_BYTES:
                raise FoundryError("GLB first chunk is not a bounded JSON chunk.")
            raw_json = stream.read(chunk_length)
            if len(raw_json) != chunk_length:
                raise FoundryError("GLB JSON chunk is truncated.")
    except OSError as exc:
        raise FoundryError(f"Could not inspect GLB {path}: {exc}") from exc
    try:
        document = json.loads(raw_json.rstrip(b" \t\r\n\x00").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FoundryError(f"GLB JSON is invalid: {exc}") from exc
    if not isinstance(document, dict) or document.get("asset", {}).get("version") != "2.0":
        raise FoundryError("GLB JSON does not declare glTF 2.0.")
    return document


def _measure(document: dict[str, Any]) -> GlbInspection:
    accessors = document.get("accessors", [])
    meshes = document.get("meshes", [])
    if not isinstance(accessors, list) or not isinstance(meshes, list):
        raise FoundryError("GLB accessors and meshes must be arrays.")
    triangles = 0
    primitive_count = 0
    for mesh in meshes:
        primitives = mesh.get("primitives", []) if isinstance(mesh, dict) else None
        if not isinstance(primitives, list):
            raise FoundryError("GLB mesh primitives must be an array.")
        for primitive in primitives:
            if not isinstance(primitive, dict):
                raise FoundryError("GLB primitive must be an object.")
            primitive_count += 1
            mode = primitive.get("mode", 4)
            accessor_index = primitive.get("indices")
            if accessor_index is None:
                attributes = primitive.get("attributes", {})
                accessor_index = (
                    attributes.get("POSITION") if isinstance(attributes, dict) else None
                )
            count = _accessor_count(accessors, accessor_index)
            if mode == 4:
                triangles += count // 3
            elif mode in {5, 6}:
                triangles += max(0, count - 2)
    return GlbInspection(
        triangle_count=triangles,
        mesh_count=len(meshes),
        primitive_count=primitive_count,
        material_count=_array_length(document, "materials"),
        texture_count=_array_length(document, "textures"),
        image_count=_array_length(document, "images"),
        skin_count=_array_length(document, "skins"),
        joint_count=_joint_count(document),
        animation_count=_array_length(document, "animations"),
    )


def _accessor_count(accessors: list[Any], index: Any) -> int:
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(accessors):
        raise FoundryError("GLB primitive references an invalid accessor.")
    accessor = accessors[index]
    count = accessor.get("count") if isinstance(accessor, dict) else None
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise FoundryError("GLB accessor has an invalid count.")
    return count


def _array_length(document: dict[str, Any], key: str) -> int:
    value = document.get(key, [])
    if not isinstance(value, list):
        raise FoundryError(f"GLB {key} must be an array.")
    return len(value)


def _joint_count(document: dict[str, Any]) -> int:
    skins = document.get("skins", [])
    if not isinstance(skins, list):
        raise FoundryError("GLB skins must be an array.")
    node_count = _array_length(document, "nodes")
    joints: set[int] = set()
    for skin in skins:
        values = skin.get("joints", []) if isinstance(skin, dict) else None
        if not isinstance(values, list) or any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            or value >= node_count
            for value in values
        ):
            raise FoundryError("GLB skin joints must reference valid node indices.")
        joints.update(values)
    return len(joints)


def _next_report_path(asset_root: Path) -> RelativeManifestPath:
    number = 1
    while True:
        relative = RelativeManifestPath(f"reports/technical-inspection-{number:03d}.json")
        if not contained_path(asset_root, relative).exists():
            return relative
        number += 1
