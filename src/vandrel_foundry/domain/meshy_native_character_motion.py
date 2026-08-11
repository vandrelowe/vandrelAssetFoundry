from typing import Literal

from pydantic import Field, model_validator

from vandrel_foundry.domain.manifest import StrictModel

SEMANTIC_MAPPING = {
    "target_character|019fe8d7-ed16-7b82-a594-728d821ee711": "squat_butcher",
    "target_character|019fe8d4-0feb-798a-bcbb-81126f26e17f": "squat_butcher",
    "target_character|019fe8ca-a6c4-7968-822f-92efebbab5a4": "squat_eat",
    "target_character|019fe8c8-1952-7ce9-a611-33851c9cf0b2": "squat_eat",
}


class MeshyNativeMotionSemanticEvidence(StrictModel):
    schema_name: Literal["vandrel_foundry_meshy_native_motion_semantics/1.0"] = Field(
        alias="schema"
    )
    observation_basis: Literal["user_observed_provider_metadata"]
    provider_api_verification: Literal["not_performed"]
    mappings: dict[str, Literal["squat_butcher", "squat_eat"]]

    @model_validator(mode="after")
    def require_exact_mapping(self) -> "MeshyNativeMotionSemanticEvidence":
        if self.mappings != SEMANTIC_MAPPING:
            raise ValueError(
                "Meshy-native semantic evidence must retain the exact observed mapping"
            )
        return self


class MeshyNativeCharacterMotionReport(StrictModel):
    schema_name: Literal[
        "vandrel_foundry_meshy_native_character_motion/1.1",
        "vandrel_foundry_meshy_native_character_motion/1.2",
        "vandrel_foundry_meshy_native_character_motion/1.3",
    ] = Field(alias="schema")
    asset_id: str
    processor: dict[str, object]
    source_union: list[str]
    source_bindings: list[dict[str, object]]
    semantic_evidence: dict[str, object]
    transformation_facts: dict[str, object]
    clips: list[dict[str, object]]
    playback: list[dict[str, object]]
    comparison: dict[str, object]
    runtime_readiness: dict[str, object]
    output: dict[str, object]
    process_logs: list[dict[str, object]]

    @model_validator(mode="after")
    def require_bounded_shape(self) -> "MeshyNativeCharacterMotionReport":
        expected_roots = 28 if self.schema_name.endswith("/1.2") else 6
        if self.schema_name.endswith("/1.3"):
            expected_roots = len(self.source_union)
            if expected_roots < 28:
                raise ValueError("Expanded character motion report requires at least 28 roots")
        if len(self.source_union) != expected_roots or len(set(self.source_union)) != expected_roots:
            raise ValueError(
                f"Character motion report requires the exact {expected_roots}-root union"
            )
        if self.schema_name.endswith("/1.1"):
            if len(self.clips) != 10 or len(self.playback) != 10:
                raise ValueError("Character motion report requires all ten canary actions")
        elif self.schema_name.endswith("/1.2") and not (
            25 <= len(self.clips) <= 29 and 1 <= len(self.playback) <= len(self.clips)
        ):
            raise ValueError(
                "Extended character motion report requires 25-29 unique actions and bounded playback"
            )
        elif self.schema_name.endswith("/1.3") and not (
            len(self.clips) >= 29 and 13 <= len(self.playback) <= len(self.clips)
        ):
            raise ValueError(
                "Expanded character motion report requires at least 29 unique actions and bounded playback"
            )
        if self.runtime_readiness.get("vandrel_ready") is not False:
            raise ValueError("This package must remain explicitly not Vandrel-ready")
        return self
