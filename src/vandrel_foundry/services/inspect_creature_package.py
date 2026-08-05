import hashlib
import math
import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from vandrel_foundry.domain.creature_animation import (
    CreatureAnimationProfile,
    CreatureClipEvidence,
)
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.services.inspect_glb import load_glb_document
from vandrel_foundry.storage.paths import RelativeManifestPath

MAX_ENTRIES = 512
MAX_TOTAL_BYTES = 2_000_000_000
SEMANTICS = ("idle", "walk", "run")


def inspect_creature_animation_package(
    archive: Path,
    creature_family: str,
    animation_provider: str,
    rig_family: str,
) -> CreatureAnimationProfile:
    archive = archive.resolve(strict=True)
    if not archive.is_file() or archive.suffix.lower() != ".zip":
        raise FoundryError("Creature animation inspection requires a ZIP archive.")
    archive_sha256 = _hash_file(archive)
    try:
        with zipfile.ZipFile(archive) as package:
            members = _safe_members(package)
            base = _select_glb(members, "final_rig")
            selected = {semantic: _select_glb(members, semantic) for semantic in SEMANTICS}
            temporary = Path(tempfile.mkdtemp(prefix="foundry-creature-inspection-"))
            try:
                documents = {"base": _load_member(package, base, temporary)}
                documents.update(
                    {
                        semantic: _load_member(package, member, temporary)
                        for semantic, member in selected.items()
                    }
                )
            finally:
                shutil.rmtree(temporary, ignore_errors=True)
    except (OSError, zipfile.BadZipFile) as exc:
        raise FoundryError(f"Could not inspect creature animation package: {exc}") from exc

    rigs = {name: _rig(document) for name, document in documents.items()}
    animated = [rigs[name] for name in SEMANTICS]
    names_match = all(item["names"] == animated[0]["names"] for item in animated[1:])
    hierarchy_matches = all(item["hierarchy"] == animated[0]["hierarchy"] for item in animated[1:])
    rest_matches = all(item["rest"] == animated[0]["rest"] for item in animated[1:])
    base_names = set(rigs["base"]["names"])
    animated_names = set(animated[0]["names"])
    base_contains = animated_names <= base_names
    base_hierarchy = {name: rigs["base"]["hierarchy"].get(name) for name in animated[0]["names"]}
    base_rest = {name: rigs["base"]["rest"].get(name) for name in animated[0]["names"]}
    base_hierarchy_matches = base_contains and base_hierarchy == animated[0]["hierarchy"]
    base_rest_matches = base_contains and base_rest == animated[0]["rest"]
    clips = [
        _clip_evidence(semantic, selected[semantic], documents[semantic], rigs[semantic])
        for semantic in SEMANTICS
    ]
    coherent = names_match and hierarchy_matches and rest_matches
    return CreatureAnimationProfile(
        schema_version="vandrel_foundry_creature_animation_profile/1.0",
        archive_name=archive.name,
        archive_sha256=archive_sha256,
        creature_family=creature_family,
        animation_provider=animation_provider,
        rig_family=rig_family,
        base_member_path=RelativeManifestPath(base.filename),
        base_joint_count=len(rigs["base"]["names"]),
        animated_joint_count=len(animated[0]["names"]),
        shared_joint_names=animated[0]["names"],
        base_extra_joint_names=sorted(base_names - animated_names, key=str.casefold),
        clips=clips,
        animated_names_match=names_match,
        animated_hierarchy_matches=hierarchy_matches,
        animated_rest_transforms_match=rest_matches,
        base_contains_animated_rig=base_contains,
        base_shared_hierarchy_matches=base_hierarchy_matches,
        base_shared_rest_transforms_match=base_rest_matches,
        coherent_animation_set=coherent,
        direct_original_rig_transfer_compatible=(
            coherent and base_hierarchy_matches and base_rest_matches
        ),
        classification_authority="foundry_technical_suggestion_only",
    )


def _safe_members(package: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = package.infolist()
    if len(members) > MAX_ENTRIES:
        raise FoundryError("Creature package has too many entries.")
    seen: set[str] = set()
    total = 0
    for member in members:
        path = _safe_path(member.filename)
        key = path.as_posix().casefold()
        if key in seen:
            raise FoundryError(f"Creature package has a colliding path: {member.filename}")
        seen.add(key)
        if stat.S_ISLNK(member.external_attr >> 16):
            raise FoundryError(f"Creature package contains a symbolic link: {member.filename}")
        total += member.file_size
        if total > MAX_TOTAL_BYTES:
            raise FoundryError("Creature package exceeds the uncompressed size limit.")
    return members


def _safe_path(value: str) -> PurePosixPath:
    if not value or "\\" in value or value.startswith("/"):
        raise FoundryError(f"Creature package contains an unsafe path: {value!r}")
    path = PurePosixPath(value)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise FoundryError(f"Creature package contains an unsafe path: {value!r}")
    if path.parts and ":" in path.parts[0]:
        raise FoundryError(f"Creature package contains an unsafe path: {value!r}")
    return path


def _select_glb(members: list[zipfile.ZipInfo], semantic: str) -> zipfile.ZipInfo:
    matches = [
        member
        for member in members
        if not member.is_dir()
        and PurePosixPath(member.filename).suffix.lower() == ".glb"
        and semantic.casefold()
        in {part.casefold() for part in PurePosixPath(member.filename).parts}
    ]
    if len(matches) != 1:
        raise FoundryError(
            f"Creature package requires exactly one {semantic} GLB; found {len(matches)}."
        )
    return matches[0]


def _load_member(
    package: zipfile.ZipFile,
    member: zipfile.ZipInfo,
    temporary: Path,
) -> dict[str, Any]:
    destination = temporary / f"{hashlib.sha256(member.filename.encode()).hexdigest()}.glb"
    with package.open(member) as source, destination.open("xb") as target:
        shutil.copyfileobj(source, target, length=1024 * 1024)
        target.flush()
        os.fsync(target.fileno())
    return load_glb_document(destination)


def _rig(document: dict[str, Any]) -> dict[str, Any]:
    skins = document.get("skins")
    nodes = document.get("nodes")
    if not isinstance(skins, list) or len(skins) != 1 or not isinstance(nodes, list):
        raise FoundryError("Creature GLB requires exactly one skin and a node array.")
    joints = skins[0].get("joints") if isinstance(skins[0], dict) else None
    if not isinstance(joints, list) or not joints:
        raise FoundryError("Creature GLB skin requires joints.")
    names: list[str] = []
    indices: dict[int, str] = {}
    for index in joints:
        if not isinstance(index, int) or not 0 <= index < len(nodes):
            raise FoundryError("Creature GLB skin has an invalid joint reference.")
        node = nodes[index]
        name = node.get("name") if isinstance(node, dict) else None
        if not isinstance(name, str) or not name or name in names:
            raise FoundryError("Creature GLB joints require unique nonempty names.")
        names.append(name)
        indices[index] = name
    parents: dict[int, int] = {}
    for parent_index, node in enumerate(nodes):
        children = node.get("children", []) if isinstance(node, dict) else []
        if not isinstance(children, list):
            raise FoundryError("Creature GLB node children must be an array.")
        for child in children:
            if isinstance(child, int) and child in indices:
                if child in parents:
                    raise FoundryError("Creature GLB joint has multiple parents.")
                parents[child] = parent_index
    hierarchy = {indices[index]: indices.get(parents.get(index)) for index in joints}
    rest = {indices[index]: _rest_transform(nodes[index]) for index in joints}
    return {"names": names, "hierarchy": hierarchy, "rest": rest}


def _rest_transform(node: Any) -> tuple[tuple[float, ...], ...]:
    if not isinstance(node, dict):
        raise FoundryError("Creature GLB joint node must be an object.")
    if "matrix" in node:
        return (_finite_vector(node["matrix"], 16),)
    return (
        _finite_vector(node.get("translation", [0.0, 0.0, 0.0]), 3),
        _finite_vector(node.get("rotation", [0.0, 0.0, 0.0, 1.0]), 4),
        _finite_vector(node.get("scale", [1.0, 1.0, 1.0]), 3),
    )


def _finite_vector(value: Any, length: int) -> tuple[float, ...]:
    if (
        not isinstance(value, list)
        or len(value) != length
        or any(
            not isinstance(item, (int, float))
            or isinstance(item, bool)
            or not math.isfinite(float(item))
            for item in value
        )
    ):
        raise FoundryError("Creature GLB joint transform must contain finite numbers.")
    return tuple(float(item) for item in value)


def _clip_evidence(
    semantic: str,
    member: zipfile.ZipInfo,
    document: dict[str, Any],
    rig: dict[str, Any],
) -> CreatureClipEvidence:
    animations = document.get("animations")
    accessors = document.get("accessors")
    if not isinstance(animations, list) or len(animations) != 1 or not isinstance(accessors, list):
        raise FoundryError(f"Creature {semantic} GLB requires exactly one animation.")
    animation = animations[0]
    name = animation.get("name") if isinstance(animation, dict) else None
    samplers = animation.get("samplers") if isinstance(animation, dict) else None
    if not isinstance(name, str) or not name or not isinstance(samplers, list) or not samplers:
        raise FoundryError(f"Creature {semantic} animation metadata is incomplete.")
    times: list[float] = []
    for sampler in samplers:
        input_index = sampler.get("input") if isinstance(sampler, dict) else None
        if not isinstance(input_index, int) or not 0 <= input_index < len(accessors):
            raise FoundryError(f"Creature {semantic} animation has an invalid sampler.")
        accessor = accessors[input_index]
        minimum = accessor.get("min") if isinstance(accessor, dict) else None
        maximum = accessor.get("max") if isinstance(accessor, dict) else None
        if (
            not isinstance(minimum, list)
            or len(minimum) != 1
            or not isinstance(maximum, list)
            or len(maximum) != 1
        ):
            raise FoundryError(f"Creature {semantic} animation lacks bounded time evidence.")
        times.extend((float(minimum[0]), float(maximum[0])))
    if any(not math.isfinite(value) for value in times):
        raise FoundryError(f"Creature {semantic} animation times must be finite.")
    duration = max(times) - min(times)
    return CreatureClipEvidence(
        semantic=semantic,
        member_path=RelativeManifestPath(member.filename),
        animation_name=name,
        duration_seconds=duration,
        joint_count=len(rig["names"]),
    )


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
