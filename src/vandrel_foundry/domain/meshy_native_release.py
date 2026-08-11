from typing import Literal

from pydantic import Field, model_validator

from vandrel_foundry.domain.manifest import StrictModel


class MeshyNativeReleaseReport(StrictModel):
    schema_name: Literal["vandrel_foundry_meshy_native_character_release/1.0"] = Field(
        alias="schema"
    )
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
        if len(names) != 29 or len(set(names)) != 29 or any(
            not isinstance(name, str) or not name for name in names
        ):
            raise ValueError("Meshy-native release evidence requires 29 unique clips")
        if len(self.source_union) != 28 or len(set(self.source_union)) != 28:
            raise ValueError("Meshy-native release evidence requires the exact 28-root union")
        if len(self.playback_evidence) != 13:
            raise ValueError("Meshy-native release evidence requires 13 playback artifacts")
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
