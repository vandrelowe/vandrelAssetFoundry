from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import Field, model_validator

from vandrel_foundry.domain.manifest import StrictModel

RELEASE_REVIEW_CLIPS = (
    "target_character|019fe8ca-a6c4-7968-822f-92efebbab5a4",
    "target_character|019fe8d7-ed16-7b82-a594-728d821ee711",
    "target_character|Idle_6",
    "target_character|Dead",
    "target_character|Stand_To_Side_Lying",
    "target_character|Walking",
    "target_character|Running",
    "target_character|Angry_Ground_Stomp",
    "target_character|Hit_Reaction_1",
    "target_character|Carry_Heavy_Object_Walk",
    "target_character|Collect_Object",
    "target_character|Female_Crouch_Pick_Fruit_Basket_Stand",
    "target_character|Female_Stand_Pick_Fruit_Basket",
)
REPRESENTATIVE_IDLE = "target_character|Idle_6"
REPRESENTATIVE_WALK = "target_character|Walking"
REPRESENTATIVE_WORK = "target_character|Pull_Radish"
REPRESENTATIVE_WORK_FALLBACK = "target_character|Collect_Object"
REPRESENTATIVE_ASSEMBLY_SCHEMA = "vandrel_foundry_meshy_native_character_motion/1.4"
REPRESENTATIVE_PROFILE = "representative_batch"


def representative_review_clips(clip_names: Sequence[str]) -> tuple[str, str, str]:
    """Return the one closed representative selection for a complete inventory."""
    names = set(clip_names)
    work = (
        REPRESENTATIVE_WORK
        if REPRESENTATIVE_WORK in names
        else REPRESENTATIVE_WORK_FALLBACK
        if REPRESENTATIVE_WORK_FALLBACK in names
        else None
    )
    if REPRESENTATIVE_IDLE not in names or REPRESENTATIVE_WALK not in names or work is None:
        raise ValueError("Meshy-native representative release clips are unavailable")
    return REPRESENTATIVE_IDLE, REPRESENTATIVE_WALK, work


def release_check_playback_policy_passes(check: Mapping[str, object]) -> bool:
    """Evaluate the closed legacy or representative release-evidence policy."""
    clip_count = check.get("clip_count")
    playback_count = check.get("playback_evidence_count")
    source_root_count = check.get("source_root_count")
    if (
        not isinstance(clip_count, int)
        or isinstance(clip_count, bool)
        or not isinstance(playback_count, int)
        or isinstance(playback_count, bool)
    ):
        return False
    if playback_count >= 13:
        return clip_count >= 29 and (
            clip_count == 29
            or (
                isinstance(source_root_count, int)
                and not isinstance(source_root_count, bool)
                and source_root_count >= 28
            )
        )
    names = check.get("playback_clip_names")
    try:
        expected_names = list(
            representative_review_clips(names if isinstance(names, list) else [])
        )
    except ValueError:
        return False
    return (
        clip_count == 61
        and playback_count == 3
        and isinstance(source_root_count, int)
        and not isinstance(source_root_count, bool)
        and source_root_count >= 28
        and check.get("assembly_evidence_schema") == REPRESENTATIVE_ASSEMBLY_SCHEMA
        and check.get("playback_evidence_profile") == REPRESENTATIVE_PROFILE
        and isinstance(names, list)
        and names == expected_names
    )


class MeshyNativeReleaseReport(StrictModel):
    schema_name: Literal[
        "vandrel_foundry_meshy_native_character_release/1.0",
        "vandrel_foundry_meshy_native_character_release/1.1",
        "vandrel_foundry_meshy_native_character_release/1.2",
    ] = Field(alias="schema")
    asset_id: str = Field(min_length=1)
    processed_model: dict[str, object]
    assembly_report: dict[str, object]
    source_union: list[str]
    clip_inventory: list[dict[str, object]]
    playback_evidence: list[dict[str, object]]
    selected_review_clips: list[str]
    godot: dict[str, object]
    skin: dict[str, object]
    material_texture: dict[str, object]
    h4_transfer: dict[str, object]
    visual_debt: dict[str, object]
    readiness: dict[str, object]

    @model_validator(mode="after")
    def require_release_evidence(self) -> "MeshyNativeReleaseReport":
        names = [item.get("exact_name") for item in self.clip_inventory]
        expected_clips = (
            29
            if self.schema_name.endswith("/1.0")
            else 61
            if self.schema_name.endswith("/1.2")
            else len(names)
        )
        if (
            len(names) != expected_clips
            or (self.schema_name.endswith("/1.1") and expected_clips < 29)
            or len(set(names)) != len(names)
            or any(
            not isinstance(name, str) or not name for name in names
            )
        ):
            raise ValueError("Meshy-native release evidence requires unique clips")
        expected_roots = 28 if self.schema_name.endswith("/1.0") else len(self.source_union)
        if (
            len(self.source_union) != expected_roots
            or (
                self.schema_name.endswith(("/1.1", "/1.2"))
                and expected_roots < 28
            )
            or len(set(self.source_union)) != len(self.source_union)
        ):
            raise ValueError("Meshy-native release evidence requires an exact root union")
        if (
            self.schema_name.endswith("/1.0")
            and len(self.playback_evidence) != 13
        ) or (
            self.schema_name.endswith("/1.1")
            and not 13 <= len(self.playback_evidence) <= len(names)
        ) or (
            self.schema_name.endswith("/1.2")
            and len(self.playback_evidence) != 3
        ):
            raise ValueError("Meshy-native release evidence has invalid playback coverage")
        if self.schema_name.endswith("/1.2"):
            expected = list(representative_review_clips(names))
            playback_names = [item.get("exact_name") for item in self.playback_evidence]
            if playback_names != expected or self.selected_review_clips != expected:
                raise ValueError("Meshy-native representative release clips are invalid")
        else:
            required = {
                "target_character|019fe8ca-a6c4-7968-822f-92efebbab5a4",
                "target_character|019fe8d7-ed16-7b82-a594-728d821ee711",
                "target_character|Idle_6",
                "target_character|Dead",
                "target_character|Stand_To_Side_Lying",
                "target_character|Walking",
                "target_character|Running",
            }
            if not required.issubset(names) or not required.issubset(
                self.selected_review_clips
            ):
                raise ValueError("Meshy-native release evidence lacks selected clips")
        if (
            self.visual_debt.get("status") != "accepted_bounded_debt"
            or self.visual_debt.get("h4_additional_hand_corruption") is not False
            or self.readiness.get("vandrel_runtime_accepted") is not False
        ):
            raise ValueError("Meshy-native release authority markers are invalid")
        return self
