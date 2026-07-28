import hashlib
from pathlib import Path

import pytest

from tests.test_custody_inventory import _policy
from vandrel_foundry.domain.custody import PortableCustodyPath
from vandrel_foundry.domain.custody_assertion import custody_freshness
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.build_custody_inventory import build_custody_inventory
from vandrel_foundry.services.candidate_custody import bind_candidate_custody
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.review_asset import approve_asset
from vandrel_foundry.storage.manifests import ManifestRepository


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _candidate(config, lanes, prompt: Path, tmp_path: Path, *, rights="documented"):
    outside = tmp_path / "outside"
    package = outside / "Source" / "Pack"
    package.mkdir(parents=True)
    source = b"candidate source"
    license_bytes = b"documented license"
    (package / "model.glb").write_bytes(source)
    (package / "LICENSE.txt").write_bytes(license_bytes)
    create_asset(config, lanes, "custody_asset_001", "static_prop", "Custody", prompt)
    asset_root = config.foundry.workspace_root / "assets" / "custody_asset_001"
    (asset_root / "source").mkdir(exist_ok=True)
    (asset_root / "source" / "model.glb").write_bytes(source)
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load("custody_asset_001")
    manifest.artifacts.append(
        Artifact(
            artifact_id="source-model-001",
            role="provider_source_model",
            stage="source",
            format="glb",
            path="source/model.glb",
            sha256=_sha(source),
            size_bytes=len(source),
        )
    )
    manifest.revision += 1
    repository.save(manifest, expected_revision=manifest.revision - 1)
    config.foundry.asset_library_root.mkdir(parents=True)
    policy = _policy(
        tmp_path / "policy.json",
        _sha(license_bytes),
        rights=rights,
    )
    inventory = build_custody_inventory(
        config,
        outside,
        config.foundry.workspace_root,
        policy,
    )
    register = tmp_path / "register.json"
    register.write_bytes(inventory.register_bytes)
    package_id = inventory.register["packages"][0]["package_id"]
    return outside, policy, register, package_id, asset_root


def test_bind_candidate_custody_retains_exact_evidence_and_semantic_binding(
    config, lanes, prompt, tmp_path
):
    outside, policy, register, package_id, asset_root = _candidate(config, lanes, prompt, tmp_path)

    manifest = bind_candidate_custody(
        config,
        "custody_asset_001",
        outside,
        register,
        policy,
        [package_id],
    )

    assert manifest.schema_version == 2
    assert manifest.custody is not None
    assert manifest.custody.schema_version == "vandrel_foundry_candidate_custody/1.1"
    assert manifest.custody.assessment_status == "evaluated"
    assert manifest.custody.effective_rights_status == "documented"
    assert manifest.custody.register_schema_version == "vandrel_foundry_custody_register/1.1"
    assert manifest.custody.register_root_fingerprints is not None
    assert manifest.custody.evidence_fingerprint_sha256 is not None
    contribution = manifest.custody.source_contributions[0]
    assert contribution.package_root == PortableCustodyPath(
        logical_root="outside_assets",
        path="Source/Pack",
    )
    assert [item.artifact_id for item in contribution.source_inputs] == ["source-model-001"]
    evidence = contribution.license_evidence[0]
    assert evidence.original_evidence_path == PortableCustodyPath(
        logical_root="outside_assets",
        path="Source/Pack/LICENSE.txt",
    )
    assert evidence.scope_root == PortableCustodyPath(
        logical_root="outside_assets",
        path="Source/Pack",
    )
    retained = next(
        item
        for item in manifest.artifacts
        if item.artifact_id == evidence.candidate_evidence_artifact_id
    )
    assert (asset_root / retained.path).read_bytes() == b"documented license"
    assert retained.sha256 == evidence.evidence_sha256
    assert custody_freshness(manifest) == (True, [])


def test_stale_evidence_fingerprint_is_an_explicit_custody_blocker(
    config, lanes, prompt, tmp_path
) -> None:
    outside, policy, register, package_id, _ = _candidate(config, lanes, prompt, tmp_path)
    manifest = bind_candidate_custody(
        config,
        "custody_asset_001",
        outside,
        register,
        policy,
        [package_id],
    )
    assert manifest.custody is not None
    assert manifest.custody.register_root_fingerprints is not None
    manifest.custody.register_root_fingerprints["outside_assets"] = "f" * 64

    fresh, blockers = custody_freshness(manifest)

    assert not fresh
    assert "custody_evidence_fingerprint_stale" in blockers


@pytest.mark.parametrize("rights", ["missing", "disputed"])
def test_ineligible_rights_evaluate_but_approval_fails_closed(
    config, lanes, prompt, tmp_path, rights
):
    outside, policy, register, package_id, _ = _candidate(
        config, lanes, prompt, tmp_path, rights=rights
    )
    manifest = bind_candidate_custody(
        config,
        "custody_asset_001",
        outside,
        register,
        policy,
        [package_id],
    )

    assert manifest.custody is not None
    assert manifest.custody.effective_rights_status == rights
    manifest.workflow.state = WorkflowState.REVIEW
    manifest.validation.result = "passed"
    manifest.validation.checks = [
        {"name": name, "passed": True}
        for name in (
            "glb_structure",
            "geometry_present",
            "triangle_budget",
            "materials_required",
            "skeleton_required",
            "godot_sandbox_import",
        )
    ]
    manifest.revision += 1
    ManifestRepository(config.foundry.workspace_root).save(
        manifest, expected_revision=manifest.revision - 1
    )
    with pytest.raises(FoundryError, match="documented, fresh custody"):
        approve_asset(config, "custody_asset_001", "Reviewer")


def test_unrelated_register_change_does_not_stale_semantic_approval_binding(
    config, lanes, prompt, tmp_path
):
    outside, policy, register, package_id, _ = _candidate(config, lanes, prompt, tmp_path)
    first = bind_candidate_custody(
        config,
        "custody_asset_001",
        outside,
        register,
        policy,
        [package_id],
    )
    assert first.custody is not None
    first.approval.approved = True
    first.approval.custody_assertion_sha256 = first.custody.semantic_assertion_sha256
    first.approval.custody_source_inputs = first.custody.source_contributions[0].source_inputs
    first.revision += 1
    ManifestRepository(config.foundry.workspace_root).save(
        first, expected_revision=first.revision - 1
    )
    (outside / "Source" / "unrelated.bin").write_bytes(b"unrelated")
    rebuilt = build_custody_inventory(
        config,
        outside,
        config.foundry.workspace_root,
        policy,
    )
    register.write_bytes(rebuilt.register_bytes)

    second = bind_candidate_custody(
        config,
        "custody_asset_001",
        outside,
        register,
        policy,
        [package_id],
    )

    assert second.approval.approved
    assert second.custody is not None
    assert second.approval.custody_assertion_sha256 == second.custody.semantic_assertion_sha256
