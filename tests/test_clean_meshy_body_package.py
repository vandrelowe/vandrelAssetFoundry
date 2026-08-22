import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from vandrel_foundry.domain.clean_meshy_body import (
    CleanBodyPackagePolicy,
    canonical_policy_sha256,
)
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.lanes import LaneConfiguration
from vandrel_foundry.services.add_clean_meshy_body_package import add_clean_meshy_body_package
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.storage.manifests import ManifestRepository

MEMBERS = (
    ("running_evidence", "provider/Animation_Running_withSkin.fbx", b"run-evidence"),
    ("walking_evidence", "provider/Animation_Walking_withSkin.fbx", b"walk-evidence"),
    ("body", "provider/Character_output.fbx", b"body-rest-only"),
    ("albedo", "provider/texture_0.png", b"albedo"),
)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _lanes() -> LaneConfiguration:
    return LaneConfiguration.model_validate(
        {"lanes": {"humanoid": {"wrapper_template": "humanoid_candidate", "collision_policy": "manual_review", "requires_materials": True, "requires_skeleton": True, "release_enabled": True}}}
    )


def _candidate(config, prompt: Path) -> None:
    create_asset(config, _lanes(), "clean_body_test_001", "humanoid", "Clean body", prompt)


def _request(tmp_path: Path, *, order=MEMBERS, forbidden=("d" * 64,)) -> Path:
    archive = tmp_path / "body.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for _, name, payload in order:
            package.writestr(name, payload)
    bone_map = tmp_path / "bone_map.tres"
    sidecar = tmp_path / "accepted.fbx.import"
    bone_map.write_bytes(b"accepted-bone-map")
    sidecar.write_bytes(b"accepted-policy-evidence")
    exact = [
        {"role": role, "archive_member": name, "sha256": _sha(payload), "size_bytes": len(payload)}
        for role, name, payload in MEMBERS
    ]
    policy_value = {
        "schema_version": "vandrel_foundry_clean_meshy_body_package_policy/1.0",
        "exact_ordered_members": exact,
        "forbidden_output_sha256s": list(forbidden),
        "forbidden_route_ids": ["meshy_native", "historical_61_clip_aggregate"],
    }
    policy = CleanBodyPackagePolicy.model_validate(policy_value)
    value = {
        "schema_version": "vandrel_foundry_clean_meshy_body_intake/1.0",
        "asset_id": "clean_body_test_001",
        "archive": {"path": str(archive), "sha256": _sha(archive.read_bytes()), "size_bytes": archive.stat().st_size},
        "provider_rig_task_id": "provider-task",
        "selected_body_sha256": _sha(MEMBERS[2][2]),
        "selected_albedo_sha256": _sha(MEMBERS[3][2]),
        "accepted_bone_map": {"path": str(bone_map), "sha256": _sha(bone_map.read_bytes()), "size_bytes": bone_map.stat().st_size},
        "accepted_import_sidecar_policy": {"path": str(sidecar), "sha256": _sha(sidecar.read_bytes()), "size_bytes": sidecar.stat().st_size},
        "package_policy": policy_value,
        "package_policy_sha256": canonical_policy_sha256(policy),
    }
    path = tmp_path / "request.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_intake_retains_archive_as_sole_root_and_excludes_motion_outputs(config, prompt, tmp_path):
    _candidate(config, prompt)
    artifacts = add_clean_meshy_body_package(config, "clean_body_test_001", _request(tmp_path))
    assert [item.role for item in artifacts if not item.derived_from] == ["clean_meshy_body_archive"]
    assert {item.role for item in artifacts} == {"clean_meshy_body_archive", "clean_meshy_body_fbx", "clean_meshy_body_albedo", "clean_meshy_body_intake_report"}
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load("clean_body_test_001")
    assert manifest.workflow.state.value == "downloaded"
    root = repository.asset_directory("clean_body_test_001") / "source/clean_meshy_body_package_001"
    assert {path.name for path in root.iterdir()} == {"provider.zip", "body.fbx", "albedo.png", "intake-report.json"}
    report = json.loads((root / "intake-report.json").read_text())
    assert [item["output_disposition"] for item in report["ordered_members"]] == ["forbidden", "forbidden", "derived", "derived"]
    assert report["accepted_import_sidecar_policy"]["copied"] is False


@pytest.mark.parametrize("mutation,match", [("wrong_order", "exact ordered inventory"), ("extra", "exact ordered inventory"), ("wrong_member", "member bytes differ"), ("wrong_archive", "archive does not match")])
def test_intake_rejects_nonexact_archive_without_mutation(config, prompt, tmp_path, mutation, match):
    _candidate(config, prompt)
    order = list(MEMBERS)
    if mutation == "wrong_order":
        order[0], order[1] = order[1], order[0]
    elif mutation == "extra":
        order.append(("body", "provider/extra.bin", b"extra"))
    request = _request(tmp_path, order=order)
    value = json.loads(request.read_text())
    if mutation == "wrong_member":
        value["package_policy"]["exact_ordered_members"][0]["sha256"] = "f" * 64
        policy = CleanBodyPackagePolicy.model_validate(value["package_policy"])
        value["package_policy_sha256"] = canonical_policy_sha256(policy)
    elif mutation == "wrong_archive":
        value["archive"]["sha256"] = "f" * 64
    request.write_text(json.dumps(value))
    repository = ManifestRepository(config.foundry.workspace_root)
    before = repository.load("clean_body_test_001").model_dump(mode="json")
    with pytest.raises(FoundryError, match=match):
        add_clean_meshy_body_package(config, "clean_body_test_001", request)
    assert repository.load("clean_body_test_001").model_dump(mode="json") == before
    assert not list((repository.asset_directory("clean_body_test_001") / "source").glob("*"))


def test_policy_rejects_selected_historical_output():
    forbidden = _sha(MEMBERS[2][2])
    with pytest.raises(ValueError, match="forbidden historical outputs"):
        # Build through the helper's exact request model.
        from vandrel_foundry.domain.clean_meshy_body import CleanMeshyBodyIntakeRequest

        policy = CleanBodyPackagePolicy.model_validate({"schema_version": "vandrel_foundry_clean_meshy_body_package_policy/1.0", "exact_ordered_members": [{"role": role, "archive_member": name, "sha256": _sha(payload), "size_bytes": len(payload)} for role, name, payload in MEMBERS], "forbidden_output_sha256s": [forbidden], "forbidden_route_ids": ["meshy_native"]})
        CleanMeshyBodyIntakeRequest.model_validate({"schema_version": "vandrel_foundry_clean_meshy_body_intake/1.0", "asset_id": "clean_body_test_001", "archive": {"path": "x.zip", "sha256": "a" * 64, "size_bytes": 1}, "selected_body_sha256": forbidden, "selected_albedo_sha256": _sha(MEMBERS[3][2]), "accepted_bone_map": {"path": "b", "sha256": "b" * 64, "size_bytes": 1}, "accepted_import_sidecar_policy": {"path": "s", "sha256": "c" * 64, "size_bytes": 1}, "package_policy": policy.model_dump(mode="json"), "package_policy_sha256": canonical_policy_sha256(policy)})


@pytest.mark.parametrize("binding", ["accepted_bone_map", "accepted_import_sidecar_policy"])
def test_intake_rejects_changed_policy_evidence_before_copy(config, prompt, tmp_path, binding):
    _candidate(config, prompt); request=_request(tmp_path); value=json.loads(request.read_text()); value[binding]["sha256"]="f"*64; request.write_text(json.dumps(value))
    with pytest.raises(FoundryError,match="does not match exact request bytes"):
        add_clean_meshy_body_package(config,"clean_body_test_001",request)
    root=ManifestRepository(config.foundry.workspace_root).asset_directory("clean_body_test_001")
    assert not list((root/"source").glob("*"))
