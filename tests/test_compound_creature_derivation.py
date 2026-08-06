import hashlib
import json
import os
import struct
from pathlib import Path

import pytest

import vandrel_foundry.storage.manifests as manifest_storage
from vandrel_foundry.domain.custody_assertion import current_source_inputs
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.lanes import LaneConfiguration
from vandrel_foundry.domain.manifest import Artifact, Processor
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.domain.workflow_policy import approval_checks_pass
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.derive_compound_creature import (
    _promote_new,
    derive_compound_creature,
)
from vandrel_foundry.services.validate_godot import ProcessResult
from vandrel_foundry.storage.locks import AssetLock
from vandrel_foundry.storage.manifests import ManifestRepository


def _glb(path: Path) -> None:
    document = {
        "asset": {"version": "2.0"},
        "accessors": [{"count": 6}],
        "meshes": [{"primitives": [{"indices": 0, "material": 0}]}],
        "materials": [{}],
        "nodes": [{}, {}],
        "skins": [{"joints": [0, 1]}],
        "animations": [{"name": "Walk"}, {"name": "Run"}],
    }
    payload = json.dumps(document, separators=(",", ":")).encode()
    payload += b" " * (-len(payload) % 4)
    path.write_bytes(
        struct.pack("<4sII", b"glTF", 2, 20 + len(payload))
        + struct.pack("<II", len(payload), 0x4E4F534A)
        + payload
    )


def _fixture(config, prompt: Path):
    config.tools.blender_executable = prompt
    lanes = LaneConfiguration.model_validate({"lanes": {"creature": {
        "wrapper_template": "creature_candidate", "collision_policy": "manual_review",
        "requires_materials": True, "requires_skeleton": True, "release_enabled": False,
    }}})
    manifest = create_asset(config, lanes, "compound_test_001", "creature", "Compound", prompt)
    root = config.foundry.workspace_root / "assets" / "compound_test_001"
    values = [
        ("mesh_001", "mesh.fbx", "fbx", b"mesh"),
        ("fur_001", "fur.png", "png", b"fur"),
        ("eyes_001", "eyes.jpg", "jpg", b"eyes"),
        ("rig_001", "rig.gltf", "gltf", b"rig"),
    ]
    for artifact_id, name, format_name, value in values:
        path = root / "source" / name; path.write_bytes(value)
        manifest.artifacts.append(Artifact(
            artifact_id=artifact_id, role="source_contribution", stage="source",
            format=format_name, path=f"source/{name}", sha256=hashlib.sha256(value).hexdigest(),
            size_bytes=len(value),
        ))
    manifest.workflow.state = WorkflowState.DOWNLOADED
    repo = ManifestRepository(config.foundry.workspace_root)
    manifest.revision += 1; repo.save(manifest, expected_revision=manifest.revision - 1)
    return root, repo


def _roles():
    return [
        ("mesh_material_source", "mesh_001"),
        ("material_dependency", "fur_001"),
        ("material_dependency", "eyes_001"),
        ("rig_animation_donor", "rig_001"),
    ]


def _runner(arguments, cwd, environment, timeout, maximum):
    separator = arguments.index("--")
    output = Path(arguments[separator + 3]); report = Path(arguments[separator + 4])
    _glb(output)
    report.write_text(json.dumps({
        "tool_version": "Blender-test",
        "transformation_facts": {
            "donor_armatures_retained": 1, "material_dependencies_declared": 2,
            "material_dependencies_used": 2,
            "animations_exported": True, "output_skin_count": 1, "output_animation_count": 2,
            "unweighted_exported_vertex_count": 0,
        },
    }), encoding="utf-8")
    return ProcessResult(0, "ok", "", False, False, 0.1)


def test_valid_derivation_binds_complete_union_and_invalidates(config, prompt):
    root, repo = _fixture(config, prompt)
    manifest = repo.load("compound_test_001")
    manifest.approval.approved = True; manifest.quality.observed = {"stale": True}
    manifest.revision += 1; repo.save(manifest, expected_revision=manifest.revision - 1)
    result = derive_compound_creature(config, "compound_test_001", _roles(), _runner)
    saved = repo.load("compound_test_001")
    assert set(result.model.derived_from) == {"mesh_001", "fur_001", "eyes_001", "rig_001"}
    report = json.loads((root / result.report.path).read_text())
    assert set(report["contribution_union"]) == set(result.model.derived_from)
    assert set(report["contribution_union"]) == {
        item.artifact_id for item in current_source_inputs(saved)
    }
    assert report["transformation_facts"]["independent_glb_inspection"]["animation_count"] == 2
    assert all("C:\\" not in item and ".compound-creature-" not in item for item in report["arguments"])
    assert saved.quality.observed == {} and not saved.approval.approved


@pytest.mark.parametrize("roles", [
    [("mesh_material_source", "mesh_001"), ("rig_animation_donor", "rig_001")],
    [*_roles(), ("material_dependency", "fur_001")],
    [*_roles()[:-1], ("rig_animation_donor", "missing_001")],
])
def test_omitted_duplicate_extra_or_ambiguous_union_fails_without_mutation(config, prompt, roles):
    root, _ = _fixture(config, prompt); before = (root / "manifest.json").read_bytes()
    with pytest.raises(FoundryError):
        derive_compound_creature(config, "compound_test_001", roles, _runner)
    assert (root / "manifest.json").read_bytes() == before


def test_wrong_hash_and_toctou_mutation_fail(config, prompt):
    root, _ = _fixture(config, prompt)
    def mutate(arguments, *args):
        result = _runner(arguments, *args)
        (root / "source" / "fur.png").write_bytes(b"changed")
        return result
    with pytest.raises(FoundryError, match="input changed"):
        derive_compound_creature(config, "compound_test_001", _roles(), mutate)
    assert not list((root / "processed").rglob("*.glb"))


def test_invalid_glb_and_reconciled_fact_mismatch_fail(config, prompt):
    root, _ = _fixture(config, prompt)
    def invalid(arguments, *args):
        separator = arguments.index("--")
        Path(arguments[separator + 3]).write_bytes(b"compound")
        Path(arguments[separator + 4]).write_text(json.dumps({
            "tool_version": "test", "transformation_facts": {}}))
        return ProcessResult(0, "", "", False, False, 0.1)
    with pytest.raises(FoundryError):
        derive_compound_creature(config, "compound_test_001", _roles(), invalid)
    assert not list((root / "processed").rglob("*.glb"))


def test_unsupported_format_and_wrong_lane_fail(config, prompt):
    root, repo = _fixture(config, prompt)
    manifest = repo.load("compound_test_001"); manifest.artifacts[0].format = "obj"
    manifest.revision += 1; repo.save(manifest, expected_revision=manifest.revision - 1)
    with pytest.raises(FoundryError, match="Unsupported"):
        derive_compound_creature(config, "compound_test_001", _roles(), _runner)
    manifest = repo.load("compound_test_001"); manifest.asset.lane = "static_prop"
    manifest.revision += 1; repo.save(manifest, expected_revision=manifest.revision - 1)
    with pytest.raises(FoundryError, match="creature lane"):
        derive_compound_creature(config, "compound_test_001", _roles(), _runner)
    assert not list((root / "processed").rglob("*.glb"))


def test_suspended_ancestry_cannot_be_laundered(config, prompt):
    _, repo = _fixture(config, prompt)
    result = derive_compound_creature(config, "compound_test_001", _roles(), _runner)
    manifest = repo.load("compound_test_001")
    manifest.artifacts.append(Artifact(
        artifact_id="cleaned_001", role="processed_model", stage="processed", format="glb",
        path=result.model.path, sha256=result.model.sha256, size_bytes=result.model.size_bytes,
        derived_from=[result.model.artifact_id], processor=Processor(name="blender_cleanup", version="1"),
    ))
    manifest.validation.result = "passed"
    assert not approval_checks_pass(manifest)
    manifest.artifacts[-1].derived_from = ["missing_parent"]
    assert not approval_checks_pass(manifest)


def test_existing_and_concurrent_destination_fail_without_overwrite(config, prompt, monkeypatch):
    root, _ = _fixture(config, prompt)
    destination = root / "processed" / "compound_creature" / "compound_creature_model_001.glb"
    destination.parent.mkdir(parents=True); destination.write_bytes(b"owned")
    with pytest.raises(FoundryError, match="already exists"):
        derive_compound_creature(config, "compound_test_001", _roles(), _runner)
    assert destination.read_bytes() == b"owned"
    temporary = root / "temporary"; temporary.write_bytes(b"new")
    with pytest.raises(FoundryError, match="concurrently"):
        _promote_new(temporary, destination)
    assert destination.read_bytes() == b"owned"


def test_hardlink_promotion_keeps_temporary_source(tmp_path):
    source = tmp_path / "source"; destination = tmp_path / "destination"; source.write_bytes(b"x")
    _promote_new(source, destination)
    assert source.is_file() and destination.is_file()
    assert os.path.samefile(source, destination)


def test_post_manifest_replace_failure_keeps_outputs_and_reconciles(config, prompt, monkeypatch):
    root, repo = _fixture(config, prompt); original = manifest_storage.os.replace
    def replace_then_fail(source, destination):
        original(source, destination)
        if Path(destination).name == "manifest.json":
            raise OSError("seeded post-replace failure")
    monkeypatch.setattr(manifest_storage.os, "replace", replace_then_fail)
    result = derive_compound_creature(config, "compound_test_001", _roles(), _runner)
    assert (root / result.model.path).is_file()
    assert repo.load("compound_test_001").artifacts[-2].artifact_id == result.model.artifact_id


def test_fully_committed_save_then_lock_exit_failure_preserves_exact_target(
    config, prompt, monkeypatch
):
    root, repo = _fixture(config, prompt)
    original_exit = AssetLock.__exit__
    def exit_then_fail(self, *args):
        original_exit(self, *args)
        raise OSError("seeded lock exit failure")
    monkeypatch.setattr(AssetLock, "__exit__", exit_then_fail)
    result = derive_compound_creature(config, "compound_test_001", _roles(), _runner)
    live = repo.load("compound_test_001")
    assert (root / result.model.path).is_file() and (root / result.report.path).is_file()
    assert live.artifacts[-2].model_dump() == result.model.model_dump()
    assert live.artifacts[-1].model_dump() == result.report.model_dump()


def test_temp_cleanup_failure_leaves_manifest_owned_final_outputs(config, prompt, monkeypatch):
    root, repo = _fixture(config, prompt)
    monkeypatch.setattr("vandrel_foundry.services.derive_compound_creature.shutil.rmtree", lambda *args, **kwargs: None)
    result = derive_compound_creature(config, "compound_test_001", _roles(), _runner)
    assert repo.load("compound_test_001").artifacts[-2].artifact_id == result.model.artifact_id
    assert (root / result.model.path).is_file()
    assert list(root.glob(".compound-creature-*"))


def test_partial_event_journal_keeps_outputs_and_reconciles(config, prompt, monkeypatch):
    root, repo = _fixture(config, prompt)
    def partial_event(path, value):
        with path.open("ab") as stream:
            stream.write(value[: len(value) // 2])
        raise OSError("seeded partial event")
    monkeypatch.setattr(manifest_storage, "append_event_bytes", partial_event)
    result = derive_compound_creature(config, "compound_test_001", _roles(), _runner)
    assert (root / result.model.path).is_file()
    assert repo.diagnose_pending_save("compound_test_001").status == "complete"


def test_interrupted_subprocess_rolls_back(config, prompt):
    root, _ = _fixture(config, prompt)
    with pytest.raises(FoundryError, match="failed"):
        derive_compound_creature(
            config, "compound_test_001", _roles(),
            lambda *args: ProcessResult(1, "", "interrupted", False, False, 0.1),
        )
    assert not list(root.glob(".compound-creature-*"))
