import json
from pathlib import Path

import jsonschema
import pytest

from vandrel_foundry.domain.manifest import AssetManifest


def test_new_manifest_matches_checked_in_schema() -> None:
    manifest = AssetManifest.initial("stone_knife_001", "Stone Knife", "static_prop", "meshy")
    schema_path = Path(__file__).parents[1] / "schemas" / "asset-manifest-v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.validate(manifest.model_dump(mode="json"), schema)
    assert schema == AssetManifest.model_json_schema()


@pytest.mark.parametrize(
    "malicious",
    [
        "../escape",
        "safe/../escape",
        "C:/private/file",
        "//server/share/file",
        "safe\\file",
        ".",
    ],
)
def test_checked_in_schema_rejects_malicious_portable_custody_paths(
    malicious: str,
) -> None:
    schema_path = Path(__file__).parents[1] / "schemas" / "asset-manifest-v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    portable_path_schema = {
        "$defs": schema["$defs"],
        "$ref": "#/$defs/PortableCustodyPath",
    }

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {"logical_root": "outside_assets", "path": malicious},
            portable_path_schema,
        )


@pytest.mark.parametrize(
    "fingerprints",
    [
        {
            "outside_assets": "bad",
            "foundry_workspace": "4" * 64,
            "asset_library": "5" * 64,
        },
        {
            "outside_assets": "3" * 64,
            "foundry_workspace": "4" * 64,
        },
        {
            "outside_assets": "3" * 64,
            "foundry_workspace": "4" * 64,
            "asset_library": "5" * 64,
            "unexpected": "6" * 64,
        },
    ],
)
def test_checked_in_schema_rejects_malformed_root_fingerprints(
    fingerprints: dict[str, str],
) -> None:
    manifest = AssetManifest.initial(
        "stone_knife_001",
        "Stone Knife",
        "static_prop",
        "meshy",
    ).model_dump(mode="json")
    manifest["custody"]["register_root_fingerprints"] = fingerprints
    schema_path = Path(__file__).parents[1] / "schemas" / "asset-manifest-v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(manifest, schema)
