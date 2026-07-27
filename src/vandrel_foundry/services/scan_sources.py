import os
import re
from collections import Counter
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path

from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.services.add_source import (
    SUPPORTED_PACKAGE_MODEL_SUFFIXES,
    SUPPORTED_SIDECAR_SUFFIXES,
    _gltf_sidecars,
)

SUPPORTED_SCAN_SUFFIXES = SUPPORTED_PACKAGE_MODEL_SUFFIXES | {".glb"}


@dataclass(frozen=True)
class SourceCandidate:
    path: Path
    relative_path: str
    format: str
    size_bytes: int
    sidecar_count: int
    source_family: str
    suggested_lane: str
    suggested_asset_id: str
    warning: str | None = None


def scan_source_directory(root: Path, limit: int = 1000) -> list[SourceCandidate]:
    if not root.is_dir():
        raise FoundryError(f"Source scan root is not a directory: {root}")
    if limit <= 0 or limit > 10_000:
        raise FoundryError("Source scan limit must be between 1 and 10000.")
    resolved_root = root.resolve()
    candidates: list[SourceCandidate] = []
    try:
        for directory, directory_names, file_names in os.walk(resolved_root):
            directory_names[:] = sorted(
                name for name in directory_names if not (Path(directory) / name).is_symlink()
            )
            for filename in sorted(file_names):
                path = Path(directory) / filename
                if path.is_symlink() or path.suffix.lower() not in SUPPORTED_SCAN_SUFFIXES:
                    continue
                candidates.append(_candidate(resolved_root, path))
                if len(candidates) >= limit:
                    return _unique_asset_ids(candidates)
    except OSError as exc:
        raise FoundryError(f"Could not scan external source directory: {exc}") from exc
    return _unique_asset_ids(candidates)


def _candidate(root: Path, path: Path) -> SourceCandidate:
    relative = path.relative_to(root).as_posix()
    family, lane = _classify(relative)
    warning = None
    sidecars: list[Path] = []
    try:
        if path.suffix.lower() == ".gltf":
            sidecars = _gltf_sidecars(path)
        elif path.suffix.lower() == ".fbx":
            sidecars = [
                item
                for item in path.parent.iterdir()
                if item.is_file() and item.suffix.lower() in SUPPORTED_SIDECAR_SUFFIXES
            ]
        size = path.stat().st_size
    except (FoundryError, OSError) as exc:
        warning = str(exc)
        size = path.stat().st_size if path.exists() else 0
    return SourceCandidate(
        path=path,
        relative_path=relative,
        format=path.suffix.lower().removeprefix("."),
        size_bytes=size,
        sidecar_count=len(sidecars),
        source_family=family,
        suggested_lane=lane,
        suggested_asset_id=_suggest_asset_id(path.stem),
        warning=warning,
    )


def _classify(relative_path: str) -> tuple[str, str]:
    normalized = relative_path.casefold()
    if "mixamo" in normalized:
        return "mixamo", "humanoid"
    humanoid_markers = (
        "biped",
        "rigged",
        "character_output",
        "withskin",
        "female",
        "male",
        "caveman",
        "apeman",
        "chieftain",
        "raider",
        "shaman",
        "sorcerer",
    )
    if any(marker in normalized for marker in humanoid_markers):
        return ("meshy" if "meshy" in normalized else "external"), "humanoid"
    if "meshy" in normalized:
        return "meshy", "static_prop"
    if "quaternius" in normalized:
        return "quaternius", "static_prop"
    return "external", "static_prop"


def _suggest_asset_id(stem: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", stem.casefold()).strip("_")
    value = re.sub(r"_+", "_", value)[:64].rstrip("_")
    if len(value) < 3:
        value = f"asset_{value or 'model'}"
    return value


def _unique_asset_ids(candidates: list[SourceCandidate]) -> list[SourceCandidate]:
    counts = Counter(candidate.suggested_asset_id for candidate in candidates)
    result: list[SourceCandidate] = []
    for candidate in candidates:
        if counts[candidate.suggested_asset_id] == 1:
            result.append(candidate)
            continue
        suffix = sha256(candidate.relative_path.encode("utf-8")).hexdigest()[:8]
        base = candidate.suggested_asset_id[:55].rstrip("_")
        result.append(replace(candidate, suggested_asset_id=f"{base}_{suffix}"))
    return result
