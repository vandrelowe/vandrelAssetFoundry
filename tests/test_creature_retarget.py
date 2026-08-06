import math

import pytest

from vandrel_foundry.domain.creature_retarget import (
    ROLE_ALIASES,
    ROLE_PARENTS,
    require_bind_preserved,
    resolve_semantic_bones,
    validate_finite_transform,
    validate_required_clip_families,
)
from vandrel_foundry.domain.errors import FoundryError


def _rigs():
    source = {role: aliases[0][0] for role, aliases in ROLE_ALIASES.items()}
    donor = {role: aliases[1][0] for role, aliases in ROLE_ALIASES.items()}
    source_parents = {name: None for name in source.values()}
    donor_parents = {name: None for name in donor.values()}
    for child, parent in ROLE_PARENTS.items():
        source_parents[source[child]] = source[parent]
        donor_parents[donor[child]] = donor[parent]
    return source, donor, source_parents, donor_parents


def test_semantic_mapping_is_name_based_complete_and_reports_unmapped():
    source, donor, source_parents, donor_parents = _rigs()
    result = resolve_semantic_bones(
        [*source.values(), "UnusedSource"],
        [*donor.values(), "UnusedDonor"],
        source_parents,
        donor_parents,
    )
    assert set(result.roles) == set(ROLE_ALIASES)
    assert result.unmapped_source == ("UnusedSource",)
    assert result.unmapped_donor == ("UnusedDonor",)


def test_missing_required_bone_fails_closed():
    source, donor, source_parents, donor_parents = _rigs()
    with pytest.raises(FoundryError, match="tail_tip"):
        resolve_semantic_bones(
            list(source.values()),
            [name for role, name in donor.items() if role != "tail_tip"],
            source_parents,
            donor_parents,
        )


def test_ambiguous_normalized_bones_fail_closed():
    source, donor, source_parents, donor_parents = _rigs()
    with pytest.raises(FoundryError, match="ambiguous normalized bones"):
        resolve_semantic_bones(
            [*source.values(), "H-ips"], list(donor.values()), source_parents, donor_parents
        )


def test_incompatible_hierarchy_fails_closed():
    source, donor, source_parents, donor_parents = _rigs()
    source_parents[source["tail_tip"]] = None
    with pytest.raises(FoundryError, match="Source hierarchy is incompatible"):
        resolve_semantic_bones(
            list(source.values()), list(donor.values()), source_parents, donor_parents
        )


def test_partial_mapping_is_rejected_even_when_other_chains_are_complete():
    source, donor, source_parents, donor_parents = _rigs()
    source_names = [name for role, name in source.items() if role != "front_lower_r"]
    with pytest.raises(FoundryError, match="front_lower_r"):
        resolve_semantic_bones(source_names, list(donor.values()), source_parents, donor_parents)


def test_missing_clip_family_is_rejected_without_inventing_motion():
    names = ["Idle", "Eating", "Walk", "Gallop", "Jump", "HitReact", "Attack"]
    with pytest.raises(FoundryError, match="death"):
        validate_required_clip_families(names)


def test_all_required_clip_families_retain_exact_donor_names():
    names = ["Idle", "Eating", "Walk", "Gallop", "Gallop_Jump", "Idle_HitReact1", "Attack_Kick", "Death"]
    coverage = validate_required_clip_families(names)
    assert coverage["walk"] == ("Walk",)
    assert coverage["death"] == ("Death",)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nonfinite_transform_is_rejected(value):
    with pytest.raises(FoundryError, match="nonfinite"):
        validate_finite_transform([0.0, value, 1.0])


def test_changed_or_missing_bind_signature_is_rejected():
    with pytest.raises(FoundryError, match="bind signature"):
        require_bind_preserved("before", "after")
    with pytest.raises(FoundryError, match="bind signature"):
        require_bind_preserved("", "")


def test_exact_bind_signature_is_accepted():
    require_bind_preserved("same", "same")
