import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from vandrel_foundry.domain.errors import FoundryError


def normalize_bone_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


ROLE_ALIASES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "root": (("hips",), ("body",)),
    "trunk": (("chest",), ("torso3",)),
    "head": (("head",), ("head",)),
    "tail_base": (("tailstart",), ("tail1",)),
    "tail_mid": (("tail1",), ("tail2",)),
    "tail_tip": (("tail2",), ("tail3",)),
    "hind_shoulder_l": (("backleg",), ("backshoulderl",)),
    "hind_upper_l": (("backleg0",), ("backlegl",)),
    "hind_lower_l": (("backleg1",), ("backupperlegl",)),
    "hind_foot_l": (("backleg2",), ("backlowerlegl",)),
    "hind_shoulder_r": (("rbackleg",), ("backshoulderr",)),
    "hind_upper_r": (("rbackleg0",), ("backlegr",)),
    "hind_lower_r": (("rbackleg1",), ("backupperlegr",)),
    "hind_foot_r": (("rbackleg2",), ("backlowerlegr",)),
    "front_shoulder_l": (("frontleg",), ("frontshoulderl",)),
    "front_upper_l": (("frontleg0",), ("frontupperlegl",)),
    "front_lower_l": (("frontleg1",), ("frontlowerlegl",)),
    "front_shoulder_r": (("rfrontleg",), ("frontshoulderr",)),
    "front_upper_r": (("rfrontleg0",), ("frontupperlegr",)),
    "front_lower_r": (("rfrontleg1",), ("frontlowerlegr",)),
}

ROLE_PARENTS = {
    "trunk": "root",
    "head": "trunk",
    "tail_base": "root",
    "tail_mid": "tail_base",
    "tail_tip": "tail_mid",
    "hind_upper_l": "hind_shoulder_l",
    "hind_lower_l": "hind_upper_l",
    "hind_foot_l": "hind_lower_l",
    "hind_upper_r": "hind_shoulder_r",
    "hind_lower_r": "hind_upper_r",
    "hind_foot_r": "hind_lower_r",
    "front_upper_l": "front_shoulder_l",
    "front_lower_l": "front_upper_l",
    "front_upper_r": "front_shoulder_r",
    "front_lower_r": "front_upper_r",
}


@dataclass(frozen=True)
class SemanticBoneMap:
    roles: dict[str, tuple[str, str]]
    unmapped_source: tuple[str, ...]
    unmapped_donor: tuple[str, ...]


def resolve_semantic_bones(
    source_names: Sequence[str],
    donor_names: Sequence[str],
    source_parents: Mapping[str, str | None],
    donor_parents: Mapping[str, str | None],
) -> SemanticBoneMap:
    source = _unique_normalized(source_names, "source")
    donor = _unique_normalized(donor_names, "donor")
    roles: dict[str, tuple[str, str]] = {}
    for role, (source_aliases, donor_aliases) in ROLE_ALIASES.items():
        source_name = _one(role, "source", source_aliases, source)
        donor_name = _one(role, "donor", donor_aliases, donor)
        roles[role] = (source_name, donor_name)
    _validate_hierarchy(roles, source_parents, donor_parents)
    mapped_source = {value[0] for value in roles.values()}
    mapped_donor = {value[1] for value in roles.values()}
    return SemanticBoneMap(
        roles=roles,
        unmapped_source=tuple(sorted(set(source_names) - mapped_source, key=str.casefold)),
        unmapped_donor=tuple(sorted(set(donor_names) - mapped_donor, key=str.casefold)),
    )


def validate_required_clip_families(names: Sequence[str]) -> dict[str, tuple[str, ...]]:
    rules = {
        "idle": ("idle",), "eating": ("eating",), "walk": ("walk",),
        "gallop": ("gallop",), "jump": ("jump",), "hit": ("hit", "react"),
        "attack": ("attack", "kick"), "death": ("death",),
    }
    coverage = {
        family: tuple(name for name in names if any(token in name.casefold() for token in tokens))
        for family, tokens in rules.items()
    }
    missing = sorted(family for family, values in coverage.items() if not values)
    if missing:
        raise FoundryError(f"Donor animation clips are missing required families: {missing}")
    return coverage


def validate_finite_transform(values: Sequence[float]) -> None:
    if not values or not all(math.isfinite(float(value)) for value in values):
        raise FoundryError("Retarget transform contains a nonfinite value")


def require_bind_preserved(before: str, after: str) -> None:
    if not before or before != after:
        raise FoundryError("Native source bind signature changed during retargeting")


def _unique_normalized(names: Sequence[str], side: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for name in names:
        normalized = normalize_bone_name(name)
        if not normalized:
            raise FoundryError(f"{side} rig contains an empty normalized bone name")
        if normalized in values:
            raise FoundryError(
                f"{side} rig has ambiguous normalized bones: {values[normalized]!r}, {name!r}"
            )
        values[normalized] = name
    return values


def _one(
    role: str, side: str, aliases: Sequence[str], values: Mapping[str, str]
) -> str:
    matches = [values[alias] for alias in aliases if alias in values]
    if len(matches) != 1:
        raise FoundryError(
            f"Semantic role {role!r} requires exactly one {side} bone; found {matches}"
        )
    return matches[0]


def _validate_hierarchy(
    roles: Mapping[str, tuple[str, str]],
    source_parents: Mapping[str, str | None],
    donor_parents: Mapping[str, str | None],
) -> None:
    for child_role, parent_role in ROLE_PARENTS.items():
        source_child, donor_child = roles[child_role]
        source_parent, donor_parent = roles[parent_role]
        if not _is_ancestor(source_parent, source_child, source_parents):
            raise FoundryError(
                f"Source hierarchy is incompatible: {source_parent!r} is not an ancestor of {source_child!r}"
            )
        if not _is_ancestor(donor_parent, donor_child, donor_parents):
            raise FoundryError(
                f"Donor hierarchy is incompatible: {donor_parent!r} is not an ancestor of {donor_child!r}"
            )


def _is_ancestor(parent: str, child: str, parents: Mapping[str, str | None]) -> bool:
    seen: set[str] = set()
    current = parents.get(child)
    while current is not None and current not in seen:
        if current == parent:
            return True
        seen.add(current)
        current = parents.get(current)
    return False
