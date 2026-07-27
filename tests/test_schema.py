import json
from pathlib import Path

import jsonschema

from vandrel_foundry.domain.manifest import AssetManifest


def test_new_manifest_matches_checked_in_schema() -> None:
    manifest = AssetManifest.initial("stone_knife_001", "Stone Knife", "static_prop", "meshy")
    schema_path = Path(__file__).parents[1] / "schemas" / "asset-manifest-v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.validate(manifest.model_dump(mode="json"), schema)
    assert schema == AssetManifest.model_json_schema()
