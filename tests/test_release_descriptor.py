import hashlib
import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.release_descriptor import (
    ReleaseDescriptorV1,
    ReleaseDescriptorV2,
    format_release_revision,
    validate_release_descriptor,
)

FIXTURES = Path(__file__).parent / "fixtures" / "release_descriptors"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_historical_v1_fixture_is_parseable_and_byte_stable() -> None:
    path = FIXTURES / "release-v1.json"
    before = path.read_bytes()
    descriptor = validate_release_descriptor(json.loads(before))

    assert isinstance(descriptor, ReleaseDescriptorV1)
    assert descriptor.technical["historical_extension"] == "preserved"
    assert path.read_bytes() == before
    assert hashlib.sha256(before).hexdigest() == (
        "b3fcd30b949bb6c5196b160eb47d13375352bc68c38be68c6ae291d58cde4f77"
    )


def test_planned_v2_fixture_is_strict_and_valid() -> None:
    descriptor = validate_release_descriptor(_fixture("release-v2.json"))

    assert isinstance(descriptor, ReleaseDescriptorV2)
    assert descriptor.custody.custody_register.root_fingerprints["outside_assets"] == "3" * 64


@pytest.mark.parametrize(
    ("schema_name", "model", "fixture_name"),
    [
        (
            "release-descriptor-v1.compat.schema.json",
            ReleaseDescriptorV1,
            "release-v1.json",
        ),
        (
            "release-descriptor-v2.planned.schema.json",
            ReleaseDescriptorV2,
            "release-v2.json",
        ),
    ],
)
def test_checked_schemas_match_models_and_accept_compatibility_fixtures(
    schema_name: str,
    model,
    fixture_name: str,
) -> None:
    schema = json.loads((Path(__file__).parents[1] / "schemas" / schema_name).read_text())

    assert schema == model.model_json_schema()
    jsonschema.validate(_fixture(fixture_name), schema)


def test_checked_v2_schema_rejects_malformed_fingerprints_and_traversal() -> None:
    schema = json.loads(
        (
            Path(__file__).parents[1]
            / "schemas"
            / "release-descriptor-v2.planned.schema.json"
        ).read_text()
    )
    malformed = _fixture("release-v2.json")
    malformed["custody"]["register"]["root_fingerprints"]["outside_assets"] = "bad"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(malformed, schema)

    traversal = _fixture("release-v2.json")
    traversal["custody"]["source_contributions"][0]["package_root"]["path"] = "../escape"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(traversal, schema)


def test_v2_rejects_arbitrary_technical_field() -> None:
    value = _fixture("release-v2.json")
    value["technical"]["workspace_report"] = "C:/private/report.json"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ReleaseDescriptorV2.model_validate(value)


@pytest.mark.parametrize(
    ("field_path", "malicious"),
    [
        (("custody", "source_contributions", 0, "package_root", "path"), "../escape"),
        (
            (
                "custody",
                "source_contributions",
                0,
                "license_evidence",
                0,
                "original_evidence_path",
                "path",
            ),
            "C:/private/license.txt",
        ),
        (("files", 0, "path"), "//server/share/model.glb"),
    ],
)
def test_v2_rejects_traversal_absolute_and_unc_paths(
    field_path: tuple[object, ...],
    malicious: str,
) -> None:
    value = _fixture("release-v2.json")
    target = value
    for part in field_path[:-1]:
        target = target[part]
    target[field_path[-1]] = malicious

    with pytest.raises(ValidationError):
        ReleaseDescriptorV2.model_validate(value)


def test_v2_rejects_lost_logical_root_and_stale_freshness() -> None:
    value = _fixture("release-v2.json")
    contribution = value["custody"]["source_contributions"][0]
    contribution["package_root"] = "Provider/Package"
    with pytest.raises(ValidationError):
        ReleaseDescriptorV2.model_validate(value)

    stale = _fixture("release-v2.json")
    stale["custody"]["register"]["root_fingerprints"]["outside_assets"] = "f" * 64
    with pytest.raises(ValidationError, match="freshness fingerprint is stale"):
        ReleaseDescriptorV2.model_validate(stale)


def test_v2_rejects_workspace_humanoid_report_reference() -> None:
    value = _fixture("release-v2.json")
    value["humanoid_compatibility"] = {
        "evidence_route": "retarget_mapping",
        "candidate_only": True,
        "vandrel_runtime_accepted": False,
        "mapping_profile": "profile/v1",
        "report": "reports/workspace-only.json",
        "animation_donor_asset_id": "donor_asset_001",
        "direct_skeleton_match": True,
        "direct_rest_transform_match": True,
        "humanoid_retarget_candidate": True,
    }

    with pytest.raises(ValidationError):
        ReleaseDescriptorV2.model_validate(value)


def test_v2_rejects_model_substituted_for_custody_evidence() -> None:
    value = _fixture("release-v2.json")
    model = value["files"][0]
    evidence = value["custody"]["source_contributions"][0]["license_evidence"][0]
    evidence.update(
        {
            "release_path": model["path"],
            "sha256": model["sha256"],
            "size_bytes": model["size_bytes"],
            "source_artifact_id": model["source_artifact_id"],
        }
    )

    with pytest.raises(ValidationError, match="Custody evidence role and source"):
        ReleaseDescriptorV2.model_validate(value)


def test_v2_rejects_custody_evidence_source_mismatch() -> None:
    value = _fixture("release-v2.json")
    evidence = value["custody"]["source_contributions"][0]["license_evidence"][0]
    evidence["source_artifact_id"] = "different-evidence-artifact"

    with pytest.raises(ValidationError, match="Custody evidence role and source"):
        ReleaseDescriptorV2.model_validate(value)


def test_v2_rejects_model_substituted_for_humanoid_report() -> None:
    value = _fixture("release-v2.json")
    model = value["files"][0]
    value["humanoid_compatibility"] = {
        "evidence_route": "retarget_mapping",
        "candidate_only": True,
        "vandrel_runtime_accepted": False,
        "mapping_profile": "profile/v1",
        "report": {
            "release_path": model["path"],
            "sha256": model["sha256"],
            "size_bytes": model["size_bytes"],
            "source_artifact_id": model["source_artifact_id"],
        },
        "animation_donor_asset_id": "donor_asset_001",
        "direct_skeleton_match": True,
        "direct_rest_transform_match": True,
        "humanoid_retarget_candidate": True,
    }

    with pytest.raises(ValidationError, match="Humanoid report role and source"):
        ReleaseDescriptorV2.model_validate(value)


def test_v2_rejects_static_file_role_confusion() -> None:
    value = _fixture("release-v2.json")
    value["files"][1]["role"] = "model"

    with pytest.raises(ValidationError, match="exactly one model"):
        ReleaseDescriptorV2.model_validate(value)


@pytest.mark.parametrize("schema_version", [1, 2])
@pytest.mark.parametrize("revision", [0, 1000])
def test_v1_and_v2_reject_out_of_range_revisions(
    schema_version: int,
    revision: int,
) -> None:
    value = _fixture(f"release-v{schema_version}.json")
    value["release_revision"] = revision

    with pytest.raises(ValidationError):
        validate_release_descriptor(value)


@pytest.mark.parametrize("revision", [0, 1000])
def test_layout_rejects_out_of_range_revisions(revision: int) -> None:
    with pytest.raises(FoundryError, match="range 1..999"):
        format_release_revision(revision)
