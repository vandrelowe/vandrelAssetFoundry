import copy
import hashlib
import json
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.inspect_glb import inspect_glb
from vandrel_foundry.services.validate_humanoid_retarget import (
    extract_skeleton_facts,
    joint_rest_transform_mismatches,
)
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path
from vandrel_foundry.storage.provider_evidence import write_new_json_evidence

GRAFTER_VERSION = "2"
GLB_MAGIC = b"glTF"
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942
MAX_GLB_BYTES = 512 * 1024 * 1024
MAX_JSON_BYTES = 64 * 1024 * 1024
ALLOWED_STATES = {
    WorkflowState.PROCESSED,
    WorkflowState.STAGED,
    WorkflowState.REVIEW,
    WorkflowState.APPROVED,
}


@dataclass(frozen=True)
class GraftFacts:
    target_animation_count: int
    donor_animation_count: int
    output_animation_count: int
    copied_accessor_count: int
    copied_buffer_view_count: int
    copied_binary_bytes: int
    animation_names: tuple[str, ...]


@dataclass(frozen=True)
class AnimationGraftResult:
    model: Artifact
    report: Artifact
    log: Artifact
    facts: GraftFacts


def graft_animations(
    config: FoundryConfig,
    asset_id: str,
    animation_donor_asset_id: str,
) -> AnimationGraftResult:
    if asset_id == animation_donor_asset_id:
        raise FoundryError("Animation graft requires a distinct donor asset.")
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    donor_manifest = repository.load(animation_donor_asset_id)
    if manifest.workflow.state not in ALLOWED_STATES:
        raise FoundryError(f"Animation graft requires a processed target: {asset_id}")
    if donor_manifest.workflow.state not in ALLOWED_STATES:
        raise FoundryError(
            f"Animation graft requires a processed donor: {animation_donor_asset_id}"
        )
    target = _latest_processed(manifest.artifacts, asset_id)
    donor = _latest_processed(donor_manifest.artifacts, animation_donor_asset_id)
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    donor_root = config.foundry.workspace_root / "assets" / animation_donor_asset_id
    target_path = contained_path(asset_root, target.path)
    donor_path = contained_path(donor_root, donor.path)
    _verify_artifact(target_path, target)
    _verify_artifact(donor_path, donor)

    number = sum(item.role == "processed_model" for item in manifest.artifacts) + 1
    model_id = f"processed_glb_{number:03d}"
    model_relative = RelativeManifestPath(f"processed/animation_graft/{model_id}.glb")
    report_relative = RelativeManifestPath(f"reports/animation-graft-{number:03d}.json")
    log_relative = RelativeManifestPath(f"reports/animation-graft-{number:03d}.log")
    model_path = contained_path(asset_root, model_relative)
    report_path = contained_path(asset_root, report_relative)
    log_path = contained_path(asset_root, log_relative)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if model_path.exists() or report_path.exists() or log_path.exists():
        raise FoundryError("Animation graft output or evidence destination already exists.")
    try:
        facts = graft_same_skeleton_glb(target_path, donor_path, model_path)
        inspection = inspect_glb(model_path)
        if inspection.animation_count != facts.output_animation_count:
            raise FoundryError("Animation graft output inspection count does not match its report.")
        model_sha256, model_size = _hash_file(model_path)
        report_data = {
            "schema_version": 1,
            "processor": {"name": "same_skeleton_animation_graft", "version": GRAFTER_VERSION},
            "asset_id": asset_id,
            "target": _artifact_binding(asset_id, target),
            "animation_donor": _artifact_binding(animation_donor_asset_id, donor),
            "output": {
                "artifact_id": model_id,
                "sha256": model_sha256,
                "size_bytes": model_size,
            },
            "checks": {
                "exact_joint_names_and_hierarchy": True,
                "exact_joint_rest_transforms": True,
                "all_animation_targets_remapped_by_unique_node_name": True,
                "output_glb_structure_valid": True,
                "output_animation_count_matches": True,
            },
            "measurements": {
                "target_animation_count": facts.target_animation_count,
                "donor_animation_count": facts.donor_animation_count,
                "output_animation_count": facts.output_animation_count,
                "copied_accessor_count": facts.copied_accessor_count,
                "copied_buffer_view_count": facts.copied_buffer_view_count,
                "copied_binary_bytes": facts.copied_binary_bytes,
                "animation_names": list(facts.animation_names),
            },
            "limitations": [
                "Matching local joint rest transforms do not prove inverse-bind matrix equality.",
                "The graft does not prove root-motion semantics or visual playback quality.",
                "The output remains a Foundry candidate and is not Vandrel runtime acceptance.",
            ],
        }
        write_new_json_evidence(report_path, report_data)
        _write_new_text(
            log_path,
            "\n".join(
                [
                    "Vandrel Asset Foundry deterministic animation graft",
                    f"processor_version={GRAFTER_VERSION}",
                    f"target_asset_id={asset_id}",
                    f"target_artifact_id={target.artifact_id}",
                    f"donor_asset_id={animation_donor_asset_id}",
                    f"donor_artifact_id={donor.artifact_id}",
                    f"donor_animation_count={facts.donor_animation_count}",
                    f"output_animation_count={facts.output_animation_count}",
                    "result=success",
                ]
            )
            + "\n",
        )
        report_sha256, report_size = _hash_file(report_path)
        log_sha256, log_size = _hash_file(log_path)
    except BaseException:
        model_path.unlink(missing_ok=True)
        report_path.unlink(missing_ok=True)
        log_path.unlink(missing_ok=True)
        raise

    processor = Processor(name="same_skeleton_animation_graft", version=GRAFTER_VERSION)
    model_artifact = Artifact(
        artifact_id=model_id,
        role="processed_model",
        stage="processed",
        format="glb",
        path=model_relative,
        sha256=model_sha256,
        size_bytes=model_size,
        derived_from=[target.artifact_id],
        source_task_key=target.source_task_key,
        processor=processor,
    )
    report_artifact = Artifact(
        artifact_id=f"animation_graft_report_{number:03d}",
        role="animation_graft_report",
        stage="processing",
        format="json",
        path=report_relative,
        sha256=report_sha256,
        size_bytes=report_size,
        derived_from=[target.artifact_id, model_artifact.artifact_id],
        processor=processor,
    )
    log_artifact = Artifact(
        artifact_id=f"animation_graft_log_{number:03d}",
        role="animation_graft_log",
        stage="processing",
        format="log",
        path=log_relative,
        sha256=log_sha256,
        size_bytes=log_size,
        derived_from=[target.artifact_id, model_artifact.artifact_id],
        processor=processor,
    )
    manifest.artifacts.extend([model_artifact, report_artifact, log_artifact])
    manifest.workflow.state = WorkflowState.PROCESSED
    manifest.validation.result = "not_run"
    manifest.validation.checks = []
    manifest.approval.approved = False
    manifest.approval.approved_at = None
    manifest.approval.approved_artifact_hashes = {}
    manifest.approval.custody_assertion_sha256 = None
    manifest.approval.custody_source_inputs = []
    manifest.quality.observed["animation_count"] = facts.output_animation_count
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    repository.save(
        manifest,
        "asset.animations_grafted",
        expected_revision=manifest.revision - 1,
    )
    return AnimationGraftResult(
        model=model_artifact,
        report=report_artifact,
        log=log_artifact,
        facts=facts,
    )


def graft_same_skeleton_glb(
    target_path: Path,
    donor_path: Path,
    destination: Path,
) -> GraftFacts:
    target_document, target_binary = _read_glb(target_path)
    donor_document, donor_binary = _read_glb(donor_path)
    target_facts = extract_skeleton_facts(target_document)
    donor_facts = extract_skeleton_facts(donor_document)
    if (
        target_facts.joint_names != donor_facts.joint_names
        or target_facts.parent_by_joint != donor_facts.parent_by_joint
    ):
        raise FoundryError(
            "Animation graft requires exact joint-name and joint-hierarchy compatibility."
        )
    if joint_rest_transform_mismatches(target_facts, donor_facts):
        raise FoundryError(
            "Animation graft requires matching joint rest transforms; this pair requires "
            "humanoid retargeting instead of raw animation copying."
        )

    target_animations = _array(target_document, "animations")
    donor_animations = _array(donor_document, "animations")
    if not donor_animations:
        raise FoundryError("Animation donor contains no animations.")
    donor_names = [_animation_name(value, number) for number, value in enumerate(donor_animations)]
    if len(set(donor_names)) != len(donor_names):
        raise FoundryError("Animation donor contains duplicate animation names.")

    target_nodes = _unique_node_indices(target_document)
    donor_nodes = _array(donor_document, "nodes")
    target_accessors = _array(target_document, "accessors")
    donor_accessors = _array(donor_document, "accessors")
    target_views = _array(target_document, "bufferViews")
    donor_views = _array(donor_document, "bufferViews")
    target_buffer = bytearray(target_binary)
    accessor_map: dict[int, int] = {}
    view_map: dict[int, int] = {}
    copied_binary_bytes = 0

    def copy_view(view_index: int) -> int:
        nonlocal copied_binary_bytes
        if view_index in view_map:
            return view_map[view_index]
        if not 0 <= view_index < len(donor_views):
            raise FoundryError("Animation accessor references an invalid donor buffer view.")
        view = donor_views[view_index]
        if not isinstance(view, dict) or view.get("buffer", 0) != 0:
            raise FoundryError("Animation graft supports one embedded donor buffer only.")
        offset = _nonnegative_int(view.get("byteOffset", 0), "buffer view byteOffset")
        length = _nonnegative_int(view.get("byteLength"), "buffer view byteLength")
        if offset + length > len(donor_binary):
            raise FoundryError("Animation donor buffer view exceeds its binary chunk.")
        while len(target_buffer) % 4:
            target_buffer.append(0)
        new_offset = len(target_buffer)
        target_buffer.extend(donor_binary[offset : offset + length])
        copied_binary_bytes += length
        copied = copy.deepcopy(view)
        copied["buffer"] = 0
        copied["byteOffset"] = new_offset
        new_index = len(target_views)
        target_views.append(copied)
        view_map[view_index] = new_index
        return new_index

    def copy_accessor(accessor_index: int) -> int:
        if accessor_index in accessor_map:
            return accessor_map[accessor_index]
        if not 0 <= accessor_index < len(donor_accessors):
            raise FoundryError("Animation sampler references an invalid donor accessor.")
        accessor = donor_accessors[accessor_index]
        if not isinstance(accessor, dict) or "sparse" in accessor:
            raise FoundryError("Animation graft does not support sparse animation accessors.")
        view_index = accessor.get("bufferView")
        if not isinstance(view_index, int) or isinstance(view_index, bool):
            raise FoundryError("Animation accessor must reference an embedded buffer view.")
        copied = copy.deepcopy(accessor)
        copied["bufferView"] = copy_view(view_index)
        new_index = len(target_accessors)
        target_accessors.append(copied)
        accessor_map[accessor_index] = new_index
        return new_index

    grafted_animations: list[dict[str, Any]] = []
    for number, animation in enumerate(donor_animations):
        if not isinstance(animation, dict):
            raise FoundryError("Animation donor entry must be an object.")
        copied_animation = copy.deepcopy(animation)
        samplers = copied_animation.get("samplers")
        channels = copied_animation.get("channels")
        if not isinstance(samplers, list) or not isinstance(channels, list):
            raise FoundryError("Animation donor samplers and channels must be arrays.")
        for sampler in samplers:
            if not isinstance(sampler, dict):
                raise FoundryError("Animation sampler must be an object.")
            input_index = sampler.get("input")
            output_index = sampler.get("output")
            if (
                not isinstance(input_index, int)
                or isinstance(input_index, bool)
                or not isinstance(output_index, int)
                or isinstance(output_index, bool)
            ):
                raise FoundryError("Animation sampler input and output must be accessors.")
            sampler["input"] = copy_accessor(input_index)
            sampler["output"] = copy_accessor(output_index)
        for channel in channels:
            if not isinstance(channel, dict):
                raise FoundryError("Animation channel must be an object.")
            sampler_index = channel.get("sampler")
            if (
                not isinstance(sampler_index, int)
                or isinstance(sampler_index, bool)
                or not 0 <= sampler_index < len(samplers)
            ):
                raise FoundryError("Animation channel references an invalid sampler.")
            target = channel.get("target")
            if not isinstance(target, dict):
                raise FoundryError("Animation channel target must be an object.")
            donor_node_index = target.get("node")
            path = target.get("path")
            if (
                not isinstance(donor_node_index, int)
                or isinstance(donor_node_index, bool)
                or not 0 <= donor_node_index < len(donor_nodes)
                or path not in {"translation", "rotation", "scale"}
            ):
                raise FoundryError("Animation channel has an unsupported target.")
            donor_node = donor_nodes[donor_node_index]
            donor_name = donor_node.get("name") if isinstance(donor_node, dict) else None
            if not isinstance(donor_name, str) or donor_name not in target_nodes:
                raise FoundryError("Every animated donor node must uniquely exist in the target.")
            target["node"] = target_nodes[donor_name]
        copied_animation["name"] = donor_names[number]
        grafted_animations.append(copied_animation)

    target_document["accessors"] = target_accessors
    target_document["bufferViews"] = target_views
    target_document["animations"] = grafted_animations
    buffers = _array(target_document, "buffers")
    if len(buffers) != 1 or not isinstance(buffers[0], dict) or "uri" in buffers[0]:
        raise FoundryError("Animation graft supports one embedded target buffer only.")
    buffers[0]["byteLength"] = len(target_buffer)
    _write_glb(destination, target_document, bytes(target_buffer))
    return GraftFacts(
        target_animation_count=len(target_animations),
        donor_animation_count=len(donor_animations),
        output_animation_count=len(donor_animations),
        copied_accessor_count=len(accessor_map),
        copied_buffer_view_count=len(view_map),
        copied_binary_bytes=copied_binary_bytes,
        animation_names=tuple(donor_names),
    )


def _read_glb(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        size = path.stat().st_size
        if size > MAX_GLB_BYTES:
            raise FoundryError(f"GLB exceeds the {MAX_GLB_BYTES}-byte graft limit.")
        raw = path.read_bytes()
    except OSError as exc:
        raise FoundryError(f"Could not read animation graft input {path}: {exc}") from exc
    if len(raw) < 20:
        raise FoundryError("Animation graft input is a truncated GLB.")
    magic, version, declared_length = struct.unpack_from("<4sII", raw, 0)
    if magic != GLB_MAGIC or version != 2 or declared_length != len(raw):
        raise FoundryError("Animation graft input is not a complete GLB 2.0 file.")
    offset = 12
    chunks: list[tuple[int, bytes]] = []
    while offset < len(raw):
        if offset + 8 > len(raw):
            raise FoundryError("Animation graft input has a truncated chunk header.")
        length, chunk_type = struct.unpack_from("<II", raw, offset)
        offset += 8
        if offset + length > len(raw):
            raise FoundryError("Animation graft input has a truncated chunk.")
        chunks.append((chunk_type, raw[offset : offset + length]))
        offset += length
    if not chunks or chunks[0][0] != JSON_CHUNK or len(chunks[0][1]) > MAX_JSON_BYTES:
        raise FoundryError("Animation graft input lacks a bounded first JSON chunk.")
    if len(chunks) != 2 or chunks[1][0] != BIN_CHUNK:
        raise FoundryError("Animation graft supports GLBs with one embedded binary chunk.")
    try:
        document = json.loads(chunks[0][1].rstrip(b" \t\r\n\x00").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FoundryError(f"Animation graft input has invalid JSON: {exc}") from exc
    if not isinstance(document, dict) or document.get("asset", {}).get("version") != "2.0":
        raise FoundryError("Animation graft input JSON does not declare glTF 2.0.")
    buffers = _array(document, "buffers")
    if len(buffers) != 1 or not isinstance(buffers[0], dict) or "uri" in buffers[0]:
        raise FoundryError("Animation graft supports one embedded GLB buffer.")
    byte_length = _nonnegative_int(buffers[0].get("byteLength"), "buffer byteLength")
    if byte_length > len(chunks[1][1]) or len(chunks[1][1]) - byte_length > 3:
        raise FoundryError("GLB buffer length does not match its binary chunk.")
    return document, chunks[1][1][:byte_length]


def _write_glb(path: Path, document: dict[str, Any], binary: bytes) -> None:
    json_bytes = json.dumps(
        document, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    json_bytes += b" " * (-len(json_bytes) % 4)
    binary_chunk = binary + b"\x00" * (-len(binary) % 4)
    length = 12 + 8 + len(json_bytes) + 8 + len(binary_chunk)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(struct.pack("<4sII", GLB_MAGIC, 2, length))
            stream.write(struct.pack("<II", len(json_bytes), JSON_CHUNK))
            stream.write(json_bytes)
            stream.write(struct.pack("<II", len(binary_chunk), BIN_CHUNK))
            stream.write(binary_chunk)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        path.unlink(missing_ok=True)
        raise FoundryError(f"Could not create animation graft output: {exc}") from exc


def _array(document: dict[str, Any], key: str) -> list[Any]:
    value = document.get(key, [])
    if not isinstance(value, list):
        raise FoundryError(f"GLB {key} must be an array.")
    return value


def _unique_node_indices(document: dict[str, Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    duplicates: set[str] = set()
    for index, node in enumerate(_array(document, "nodes")):
        name = node.get("name") if isinstance(node, dict) else None
        if not isinstance(name, str) or not name:
            continue
        if name in result:
            duplicates.add(name)
        result[name] = index
    for duplicate in duplicates:
        result.pop(duplicate, None)
    return result


def _animation_name(animation: Any, number: int) -> str:
    if not isinstance(animation, dict):
        raise FoundryError("GLB animation must be an object.")
    name = animation.get("name")
    if not isinstance(name, str) or not name.strip():
        raise FoundryError(f"Animation {number + 1} must have a non-empty stable name.")
    return name


def _nonnegative_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise FoundryError(f"GLB {label} must be a nonnegative integer.")
    return value


def _latest_processed(artifacts: list[Artifact], asset_id: str) -> Artifact:
    candidates = [
        item for item in artifacts if item.role == "processed_model" and item.format == "glb"
    ]
    if not candidates:
        raise FoundryError(f"No processed GLB artifact exists: {asset_id}")
    return candidates[-1]


def _artifact_binding(asset_id: str, artifact: Artifact) -> dict[str, Any]:
    return {
        "asset_id": asset_id,
        "artifact_id": artifact.artifact_id,
        "sha256": artifact.sha256,
        "size_bytes": artifact.size_bytes,
    }


def _verify_artifact(path: Path, artifact: Artifact) -> None:
    digest, size = _hash_file(path)
    if digest != artifact.sha256 or size != artifact.size_bytes:
        raise FoundryError(f"Animation graft input changed: {artifact.artifact_id}")


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise FoundryError(f"Could not hash animation graft artifact {path}: {exc}") from exc
    return digest.hexdigest(), size


def _write_new_text(path: Path, value: str) -> None:
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        path.unlink(missing_ok=True)
        raise FoundryError(f"Could not write animation graft log: {exc}") from exc
