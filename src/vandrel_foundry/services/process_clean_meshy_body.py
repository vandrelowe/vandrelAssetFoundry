"""Deterministic Blender body-only processing for exact clean-body intake."""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import shutil
import struct
import tempfile
from pathlib import Path

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.clean_meshy_body import (
    CLEAN_BODY_PROCESSOR,
    CLEAN_BODY_PROCESSOR_VERSION,
)
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.domain.workflow_policy import invalidate_approval, transition_workflow
from vandrel_foundry.services.run_clean_meshy_body_blender import (
    CleanBodyBlenderRunner,
    run_bounded_clean_body_blender,
)
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path


def process_clean_meshy_body(
    config: FoundryConfig, asset_id: str, runner: CleanBodyBlenderRunner | None = None
) -> list[Artifact]:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.asset.lane != "humanoid" or manifest.workflow.state not in {WorkflowState.DOWNLOADED, WorkflowState.PROCESSED}:
        raise FoundryError("Clean-body processing requires a downloaded humanoid candidate.")
    executable = config.tools.blender_executable
    if executable is None or not executable.is_absolute() or not executable.is_file():
        raise FoundryError("Configure tools.blender_executable as an existing absolute file.")
    body = _latest(manifest.artifacts, "clean_meshy_body_fbx")
    albedo = _latest(manifest.artifacts, "clean_meshy_body_albedo")
    intake = _latest(manifest.artifacts, "clean_meshy_body_intake_report")
    asset_root = repository.asset_directory(asset_id)
    for item in (body, albedo, intake):
        _verify(contained_path(asset_root, item.path), item)
    forbidden = set(json.loads(contained_path(asset_root, intake.path).read_text())["forbidden_output_sha256s"])
    processed_root = asset_root / "processed"
    processed_root.mkdir(parents=True, exist_ok=True)
    operation = Path(tempfile.mkdtemp(prefix=".clean-body-process-", dir=processed_root))
    destination = asset_root / "processed" / "clean_body_001"
    try:
        source = operation / "source.fbx"
        texture = operation / "source-albedo.png"
        shutil.copyfile(contained_path(asset_root, body.path), source)
        shutil.copyfile(contained_path(asset_root, albedo.path), texture)
        output = operation / "body.gltf"
        report = operation / "processing-report.json"
        result = (runner or run_bounded_clean_body_blender)([
            str(executable), "--background", "--factory-startup", "--disable-autoexec",
            "--python-exit-code", "1", "--python",
            str(Path(__file__).parents[1] / "blender/process_clean_meshy_body.py"), "--",
            str(source), str(texture), str(output), str(report),
        ], asset_root, _safe_environment(), config.tools.blender_timeout_seconds, config.tools.maximum_output_bytes)
        if result.return_code != 0 or result.timed_out or result.output_limited:
            raise FoundryError("Bounded clean-body Blender processing failed.")
        blender_diagnostic = json.loads(report.read_text(encoding="utf-8"))
        source.unlink(); texture.unlink()
        required = {"body.gltf", "body.bin", "albedo.png", "processing-report.json"}
        if required != {path.name for path in operation.iterdir()}:
            raise FoundryError("Blender did not create the exact clean-body outputs.")
        if blender_diagnostic.get("schema_version") != _blender_diagnostic_schema():
            raise FoundryError("Blender did not emit the expected processing diagnostic.")
        facts = _derive_gltf_facts(operation / "body.gltf", operation / "body.bin", operation / "albedo.png")
        report.write_text(
            json.dumps(
                {
                    "schema_version": "vandrel_foundry_clean_meshy_body_processing/2.0",
                    "processor": {"name": CLEAN_BODY_PROCESSOR, "version": CLEAN_BODY_PROCESSOR_VERSION},
                    "source_body_sha256": body.sha256,
                    "source_albedo_sha256": albedo.sha256,
                    **facts,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        for name in ("body.gltf", "body.bin", "albedo.png"):
            if _hash(operation / name)[0] in forbidden:
                raise FoundryError("Clean-body processing produced a forbidden historical output.")
        if destination.exists():
            raise FoundryError("Clean-body processing destination already exists.")
        os.replace(operation, destination)
    except BaseException:
        if operation.exists(): shutil.rmtree(operation)
        raise
    processor = Processor(name=CLEAN_BODY_PROCESSOR, version=CLEAN_BODY_PROCESSOR_VERSION)
    specs = (
        ("processed_clean_body_001", "processed_model", "gltf", "body.gltf"),
        ("processed_clean_body_buffer_001", "processed_clean_body_buffer", "bin", "body.bin"),
        ("processed_clean_body_albedo_001", "processed_clean_body_albedo", "png", "albedo.png"),
        ("clean_body_processing_report_001", "clean_body_processing_report", "json", "processing-report.json"),
    )
    artifacts = []
    for artifact_id, role, fmt, name in specs:
        digest, size = _hash(destination / name)
        artifacts.append(Artifact(artifact_id=artifact_id, role=role, stage="processed", format=fmt, path=RelativeManifestPath(f"processed/clean_body_001/{name}"), sha256=digest, size_bytes=size, derived_from=[body.artifact_id, albedo.artifact_id], processor=processor))
    revision = manifest.revision
    manifest.artifacts.extend(artifacts)
    manifest.quality.observed.update({"animation_count": 0, "clean_body_route": "clean_body_shared_animation"})
    transition_workflow(manifest, WorkflowState.PROCESSED)
    manifest.validation.result = "not_run"; manifest.validation.checks = []
    invalidate_approval(manifest)
    manifest.revision += 1; manifest.asset.updated_at = utc_now()
    try:
        repository.save(manifest, "asset.clean_meshy_body_processed", expected_revision=revision)
    except BaseException:
        live = repository.load(asset_id)
        if live.revision == manifest.revision and _references(live.artifacts, artifacts):
            for item in artifacts:
                _verify(contained_path(asset_root, item.path), item)
            return artifacts
        if live.revision == revision and not _references(live.artifacts, artifacts):
            shutil.rmtree(destination)
        raise
    return artifacts


def _latest(artifacts: list[Artifact], role: str) -> Artifact:
    values = [item for item in artifacts if item.role == role]
    if not values: raise FoundryError(f"Clean-body artifact role is missing: {role}")
    return values[-1]


def _verify(path: Path, artifact: Artifact) -> None:
    if _hash(path) != (artifact.sha256, artifact.size_bytes): raise FoundryError(f"Clean-body input changed: {artifact.artifact_id}")


def _references(live: list[Artifact], targets: list[Artifact]) -> bool:
    expected = {(item.artifact_id, item.sha256, item.size_bytes) for item in targets}
    actual = {(item.artifact_id, item.sha256, item.size_bytes) for item in live}
    return expected.issubset(actual)


def _hash(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256(); size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024): digest.update(chunk); size += len(chunk)
    return digest.hexdigest(), size


def _safe_environment() -> dict[str, str]:
    allowed = {"APPDATA", "HOME", "LOCALAPPDATA", "PATH", "SYSTEMDRIVE", "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE", "WINDIR"}
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


def _blender_diagnostic_schema() -> str:
    script = Path(__file__).parents[1] / "blender/process_clean_meshy_body.py"
    try:
        tree = ast.parse(script.read_text(encoding="utf-8"), filename=str(script))
    except (OSError, SyntaxError) as exc:
        raise FoundryError(f"Clean-body Blender processor source is unreadable: {exc}") from exc
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "BLENDER_DIAGNOSTIC_SCHEMA" for target in node.targets):
            value = ast.literal_eval(node.value)
            if isinstance(value, str) and value:
                return value
    raise FoundryError("Clean-body Blender processor has no exact diagnostic schema constant.")


_COMPONENT_FORMATS = {
    5120: ("b", 1),
    5121: ("B", 1),
    5122: ("h", 2),
    5123: ("H", 2),
    5125: ("I", 4),
    5126: ("f", 4),
}
_TYPE_WIDTHS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def _derive_gltf_facts(gltf_path: Path, buffer_path: Path, albedo_path: Path) -> dict[str, object]:
    """Derive release facts from exported bytes, never the Blender-authored report."""
    try:
        document = json.loads(gltf_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FoundryError(f"Processed clean-body glTF is unreadable: {exc}") from exc
    if document.get("asset", {}).get("version") != "2.0":
        raise FoundryError("Processed clean body must be glTF 2.0.")
    if document.get("animations") not in (None, []):
        raise FoundryError("Processed clean body contains embedded animations.")
    buffers = document.get("buffers")
    images = document.get("images")
    if not isinstance(buffers, list) or len(buffers) != 1 or buffers[0].get("uri") != "body.bin":
        raise FoundryError("Processed clean body must have the exact external body.bin dependency.")
    if buffers[0].get("byteLength") != buffer_path.stat().st_size:
        raise FoundryError("Processed clean-body buffer length differs from the glTF binding.")
    if not isinstance(images, list) or len(images) != 1 or images[0].get("uri") != "albedo.png":
        raise FoundryError("Processed clean body must have the exact external albedo.png dependency.")
    buffer_bytes = buffer_path.read_bytes()
    materials = document.get("materials")
    textures = document.get("textures")
    if not isinstance(materials, list) or not materials or not isinstance(textures, list):
        raise FoundryError("Processed clean body has no material/texture bindings.")
    for material in materials:
        pbr = material.get("pbrMetallicRoughness", {})
        texture_index = pbr.get("baseColorTexture", {}).get("index")
        if not isinstance(texture_index, int) or not 0 <= texture_index < len(textures) or textures[texture_index].get("source") != 0:
            raise FoundryError("Every clean-body material must use the exact external albedo.")
        if pbr.get("metallicFactor", 1.0) != 0.0 or not math.isclose(float(pbr.get("roughnessFactor", -1.0)), 0.8, abs_tol=1e-6):
            raise FoundryError("Clean-body material is not the accepted lit Principled policy.")
    meshes = document.get("meshes")
    skins = document.get("skins")
    nodes = document.get("nodes")
    if not isinstance(meshes, list) or not meshes or not isinstance(skins, list) or len(skins) != 1 or not isinstance(nodes, list):
        raise FoundryError("Processed clean body must contain one skinned mesh body.")
    if not skins[0].get("joints") or not isinstance(skins[0].get("inverseBindMatrices"), int):
        raise FoundryError("Processed clean body has no exact skin joints/bind matrices.")
    skinned_nodes = [(index, node) for index, node in enumerate(nodes) if isinstance(node, dict) and isinstance(node.get("mesh"), int)]
    if not skinned_nodes or any(node.get("skin") != 0 for _, node in skinned_nodes):
        raise FoundryError("Every clean-body mesh node must use the sole skin.")
    world_matrices = _node_world_matrices(document)
    positions: list[tuple[float, ...]] = []
    minimum_weight_sum = math.inf
    maximum_weight_sum = 0.0
    minimum_influences = 99
    maximum_influences = 0
    primitive_count = 0
    for node_index, node in skinned_nodes:
        mesh_index = node["mesh"]
        if not 0 <= mesh_index < len(meshes):
            raise FoundryError("Clean-body node references an invalid mesh.")
        mesh = meshes[mesh_index]
        world_matrix = world_matrices[node_index]
        primitives = mesh.get("primitives", [])
        if not primitives:
            raise FoundryError("Processed clean-body mesh has no material surface.")
        for primitive in primitives:
            primitive_count += 1
            material_index = primitive.get("material")
            attrs = primitive.get("attributes", {})
            if not isinstance(material_index, int) or not 0 <= material_index < len(materials):
                raise FoundryError("Every clean-body surface must bind a material.")
            required = ("POSITION", "JOINTS_0", "WEIGHTS_0")
            if any(not isinstance(attrs.get(name), int) for name in required):
                raise FoundryError("Every clean-body surface must contain skin weights.")
            surface_positions = _read_accessor(document, buffer_bytes, attrs["POSITION"])
            joints = _read_accessor(document, buffer_bytes, attrs["JOINTS_0"])
            weights = _read_accessor(document, buffer_bytes, attrs["WEIGHTS_0"])
            has_extra_weights = isinstance(attrs.get("WEIGHTS_1"), int)
            has_extra_joints = isinstance(attrs.get("JOINTS_1"), int)
            if has_extra_weights != has_extra_joints:
                raise FoundryError("Clean-body secondary joints and weights must be paired.")
            extra_weights = _read_accessor(document, buffer_bytes, attrs["WEIGHTS_1"]) if has_extra_weights else [()] * len(weights)
            extra_joints = _read_accessor(document, buffer_bytes, attrs["JOINTS_1"]) if has_extra_joints else [()] * len(weights)
            if not surface_positions or len({len(surface_positions), len(joints), len(weights), len(extra_weights), len(extra_joints)}) != 1:
                raise FoundryError("Clean-body position, joint, and weight counts differ.")
            positions.extend(_transform_position(world_matrix, position) for position in surface_positions)
            for primary_joints, primary, secondary_joints, extra in zip(joints, weights, extra_joints, extra_weights, strict=True):
                values = [float(value) for value in (*primary, *extra)]
                joint_values = [*primary_joints, *secondary_joints]
                if not all(math.isfinite(value) and value >= 0.0 for value in values):
                    raise FoundryError("Clean-body skin contains invalid weights.")
                for joint, weight in zip(joint_values, values, strict=True):
                    if weight > 1e-6 and (not isinstance(joint, int) or not 0 <= joint < len(skins[0]["joints"])):
                        raise FoundryError("Clean-body weighted joint index is non-integral or outside the skin joint table.")
                total = sum(values)
                count = sum(value > 1e-6 for value in values)
                if total <= 0.0 or not math.isclose(total, 1.0, abs_tol=1e-3):
                    raise FoundryError("Clean-body vertex influences are missing or unnormalized.")
                minimum_weight_sum = min(minimum_weight_sum, total)
                maximum_weight_sum = max(maximum_weight_sum, total)
                minimum_influences = min(minimum_influences, count)
                maximum_influences = max(maximum_influences, count)
    flat = [value for position in positions for value in position]
    if not positions or not all(math.isfinite(value) for value in flat):
        raise FoundryError("Clean-body positions are absent or non-finite.")
    bounds_min = [min(position[axis] for position in positions) for axis in range(3)]
    bounds_max = [max(position[axis] for position in positions) for axis in range(3)]
    dimensions = [maximum - minimum for minimum, maximum in zip(bounds_min, bounds_max, strict=True)]
    if any(value <= 0.0 or not math.isfinite(value) for value in dimensions):
        raise FoundryError("Clean-body exported scale is not finite and positive.")
    if abs(bounds_min[1]) > 1e-4:
        raise FoundryError("Clean-body exported geometry is not grounded at Y=0.")
    dependencies = []
    for role, path in (("buffer", buffer_path), ("albedo", albedo_path)):
        digest, size = _hash(path)
        dependencies.append({"role": role, "uri": path.name, "sha256": digest, "size_bytes": size})
    return {
        "gltf_sha256": _hash(gltf_path)[0],
        "animation_count": 0,
        "dependency_bindings": dependencies,
        "skin_count": 1,
        "joint_count": len(skins[0]["joints"]),
        "primitive_count": primitive_count,
        "vertex_count": len(positions),
        "minimum_weight_sum": minimum_weight_sum,
        "maximum_weight_sum": maximum_weight_sum,
        "minimum_vertex_influences": minimum_influences,
        "maximum_vertex_influences": maximum_influences,
        "material_count": len(materials),
        "all_surfaces_material_bound": True,
        "external_lit_albedo": "albedo.png",
        "bounds_min": bounds_min,
        "bounds_max": bounds_max,
        "dimensions": dimensions,
        "grounded": True,
    }


def _read_accessor(document: dict, buffer_bytes: bytes, index: int) -> list[tuple[float | int, ...]]:
    try:
        accessor = document["accessors"][index]
        view = document["bufferViews"][accessor["bufferView"]]
        component_format, component_size = _COMPONENT_FORMATS[accessor["componentType"]]
        width = _TYPE_WIDTHS[accessor["type"]]
        count = accessor["count"]
    except (KeyError, IndexError, TypeError) as exc:
        raise FoundryError("Clean-body glTF accessor is malformed.") from exc
    if view.get("buffer") != 0 or accessor.get("sparse") is not None:
        raise FoundryError("Clean-body accessors must use the exact sole non-sparse buffer.")
    packed_size = component_size * width
    stride = view.get("byteStride", packed_size)
    start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    values: list[tuple[float | int, ...]] = []
    normalized = bool(accessor.get("normalized", False))
    for element in range(count):
        offset = start + element * stride
        if offset < 0 or offset + packed_size > len(buffer_bytes):
            raise FoundryError("Clean-body accessor exceeds its exact buffer bytes.")
        item = struct.unpack_from("<" + component_format * width, buffer_bytes, offset)
        if normalized and accessor["componentType"] != 5126:
            maximum = {5120: 127, 5121: 255, 5122: 32767, 5123: 65535, 5125: 4294967295}[accessor["componentType"]]
            item = tuple(max(float(value) / maximum, -1.0) for value in item)
        values.append(tuple(item))
    return values


def _node_world_matrices(document: dict) -> dict[int, tuple[tuple[float, ...], ...]]:
    nodes = document["nodes"]
    parents: set[int] = set()
    for node in nodes:
        for child in node.get("children", []):
            if not isinstance(child, int) or not 0 <= child < len(nodes) or child in parents:
                raise FoundryError("Clean-body glTF node hierarchy is invalid or multiply parented.")
            parents.add(child)
    scene_index = document.get("scene", 0)
    scenes = document.get("scenes")
    if isinstance(scenes, list) and scenes:
        if not isinstance(scene_index, int) or not 0 <= scene_index < len(scenes):
            raise FoundryError("Clean-body glTF active scene is invalid.")
        roots = scenes[scene_index].get("nodes", [])
    else:
        roots = [index for index in range(len(nodes)) if index not in parents]
    identity = ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0))
    worlds: dict[int, tuple[tuple[float, ...], ...]] = {}

    def visit(index: int, parent: tuple[tuple[float, ...], ...], active: set[int]) -> None:
        if not isinstance(index, int) or not 0 <= index < len(nodes) or index in active or index in worlds:
            raise FoundryError("Clean-body glTF node hierarchy is cyclic or duplicated.")
        world = _matrix_multiply(parent, _node_local_matrix(nodes[index]))
        worlds[index] = world
        for child in nodes[index].get("children", []):
            visit(child, world, active | {index})

    for root in roots:
        visit(root, identity, set())
    if len(worlds) != len(nodes):
        raise FoundryError("Clean-body glTF contains nodes outside its active scene hierarchy.")
    return worlds


def _node_local_matrix(node: dict) -> tuple[tuple[float, ...], ...]:
    if "matrix" in node:
        values = node["matrix"]
        if not isinstance(values, list) or len(values) != 16 or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in values):
            raise FoundryError("Clean-body node matrix is invalid.")
        return tuple(tuple(float(values[column * 4 + row]) for column in range(4)) for row in range(4))
    translation = node.get("translation", [0.0, 0.0, 0.0])
    rotation = node.get("rotation", [0.0, 0.0, 0.0, 1.0])
    scale = node.get("scale", [1.0, 1.0, 1.0])
    values = [*translation, *rotation, *scale]
    if len(translation) != 3 or len(rotation) != 4 or len(scale) != 3 or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in values):
        raise FoundryError("Clean-body node transform is invalid.")
    x, y, z, w = (float(value) for value in rotation)
    magnitude = math.sqrt(x * x + y * y + z * z + w * w)
    if magnitude <= 0.0:
        raise FoundryError("Clean-body node rotation is not a finite unit quaternion.")
    x, y, z, w = x / magnitude, y / magnitude, z / magnitude, w / magnitude
    sx, sy, sz = (float(value) for value in scale)
    if sx <= 0.0 or sy <= 0.0 or sz <= 0.0:
        raise FoundryError("Clean-body node scale must be positive.")
    tx, ty, tz = (float(value) for value in translation)
    return (
        ((1 - 2 * (y * y + z * z)) * sx, (2 * (x * y - z * w)) * sy, (2 * (x * z + y * w)) * sz, tx),
        ((2 * (x * y + z * w)) * sx, (1 - 2 * (x * x + z * z)) * sy, (2 * (y * z - x * w)) * sz, ty),
        ((2 * (x * z - y * w)) * sx, (2 * (y * z + x * w)) * sy, (1 - 2 * (x * x + y * y)) * sz, tz),
        (0.0, 0.0, 0.0, 1.0),
    )


def _matrix_multiply(left: tuple[tuple[float, ...], ...], right: tuple[tuple[float, ...], ...]) -> tuple[tuple[float, ...], ...]:
    return tuple(tuple(sum(left[row][inner] * right[inner][column] for inner in range(4)) for column in range(4)) for row in range(4))


def _transform_position(matrix: tuple[tuple[float, ...], ...], position: tuple[float | int, ...]) -> tuple[float, float, float]:
    if len(position) != 3:
        raise FoundryError("Clean-body position accessor is not VEC3.")
    x, y, z = (float(value) for value in position)
    result = tuple(matrix[row][0] * x + matrix[row][1] * y + matrix[row][2] * z + matrix[row][3] for row in range(3))
    if not all(math.isfinite(value) for value in result):
        raise FoundryError("Clean-body world-space position is non-finite.")
    return result
