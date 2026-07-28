import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

import vandrel_foundry.services.publish_release as publication
from tests.conftest import bind_documented_test_custody, write_config
from vandrel_foundry.cli import app
from vandrel_foundry.domain.custody_assertion import semantic_assertion_sha256
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.lanes import LaneConfiguration
from vandrel_foundry.domain.manifest import (
    Artifact,
    CustodyLicenseEvidence,
    CustodySourceContribution,
    CustodySourceInput,
    utc_now,
)
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.plan_release import plan_release
from vandrel_foundry.services.publish_release import publish_release
from vandrel_foundry.storage.manifests import ManifestRepository


class FakeGit:
    def __init__(self, status: str = "", lfs: bool = True) -> None:
        self.status = status
        self.lfs = lfs

    def __call__(
        self,
        command: list[str],
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        if command[:2] == ["rev-parse", "--is-inside-work-tree"]:
            return subprocess.CompletedProcess(command, 0, "true\n", "")
        if command[:2] == ["status", "--porcelain=v1"]:
            return subprocess.CompletedProcess(command, 0, self.status, "")
        if command[:2] == ["check-attr", "filter"]:
            value = "lfs" if self.lfs else "unspecified"
            return subprocess.CompletedProcess(command, 0, f"{command[-1]}: filter: {value}\n", "")
        raise AssertionError(command)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _approved_asset(config, lanes, prompt: Path) -> None:
    create_asset(config, lanes, "stone_knife_001", "static_prop", "Stone Knife", prompt)
    root = config.foundry.workspace_root / "assets" / "stone_knife_001"
    model = b"fixture glb"
    wrapper = b"[gd_scene format=3]\n"
    (root / "processed").mkdir(exist_ok=True)
    (root / "processed" / "model.glb").write_bytes(model)
    (root / "review").mkdir(exist_ok=True)
    (root / "review" / "wrapper.tscn").write_bytes(wrapper)
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load("stone_knife_001")
    manifest.artifacts.extend(
        [
            Artifact(
                artifact_id="processed-model-001",
                role="processed_model",
                stage="processed",
                format="glb",
                path="processed/model.glb",
                sha256=_sha256(model),
                size_bytes=len(model),
            ),
            Artifact(
                artifact_id="godot-wrapper-001",
                role="godot_wrapper_scene",
                stage="review",
                format="tscn",
                path="review/wrapper.tscn",
                sha256=_sha256(wrapper),
                size_bytes=len(wrapper),
            ),
        ]
    )
    manifest.validation.result = "passed"
    manifest.validation.checks = [{"name": "godot_sandbox_import", "passed": True}]
    bind_documented_test_custody(manifest, root)
    manifest.approval.approved = True
    manifest.approval.approved_at = utc_now()
    manifest.approval.reviewer = "Test Reviewer"
    manifest.approval.approved_artifact_hashes = {
        "processed_model": _sha256(model),
        "godot_wrapper_scene": _sha256(wrapper),
    }
    manifest.workflow.state = WorkflowState.APPROVED
    manifest.revision += 1
    repository.save(manifest, expected_revision=manifest.revision - 1)


def _library(config) -> Path:
    root = config.foundry.asset_library_root
    (root / ".git").mkdir(parents=True)
    return root


def _humanoid_lanes() -> LaneConfiguration:
    return LaneConfiguration.model_validate(
        {
            "lanes": {
                "humanoid": {
                    "wrapper_template": "humanoid_candidate",
                    "collision_policy": "manual_review",
                    "requires_skeleton": True,
                    "release_enabled": True,
                }
            }
        }
    )


def _approved_humanoid(config, prompt: Path, compatibility: dict | None) -> None:
    lanes = _humanoid_lanes()
    asset_id = "meshy_shaman_001"
    create_asset(config, lanes, asset_id, "humanoid", "Meshy Shaman", prompt)
    root = config.foundry.workspace_root / "assets" / asset_id
    model = b"humanoid fixture glb"
    wrapper = b"[gd_scene format=3]\n"
    (root / "processed").mkdir(exist_ok=True)
    (root / "processed" / "model.glb").write_bytes(model)
    (root / "review").mkdir(exist_ok=True)
    (root / "review" / "wrapper.tscn").write_bytes(wrapper)
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    manifest.artifacts.extend(
        [
            Artifact(
                artifact_id="processed-humanoid-001",
                role="processed_model",
                stage="processed",
                format="glb",
                path="processed/model.glb",
                sha256=_sha256(model),
                size_bytes=len(model),
            ),
            Artifact(
                artifact_id="humanoid-wrapper-001",
                role="godot_wrapper_scene",
                stage="review",
                format="tscn",
                path="review/wrapper.tscn",
                sha256=_sha256(wrapper),
                size_bytes=len(wrapper),
            ),
        ]
    )
    manifest.validation.result = "passed"
    manifest.validation.checks = [{"name": "godot_sandbox_import", "passed": True}]
    bind_documented_test_custody(manifest, root)
    if compatibility is not None:
        manifest.validation.checks.append(compatibility)
    manifest.approval.approved = True
    manifest.approval.approved_at = utc_now()
    manifest.approval.reviewer = "Test Reviewer"
    manifest.approval.approved_artifact_hashes = {
        "processed_model": _sha256(model),
        "godot_wrapper_scene": _sha256(wrapper),
    }
    manifest.workflow.state = WorkflowState.APPROVED
    manifest.revision += 1
    repository.save(manifest, expected_revision=manifest.revision - 1)


def test_humanoid_release_requires_compatibility_evidence(config, prompt: Path) -> None:
    _approved_humanoid(config, prompt, compatibility=None)

    with pytest.raises(FoundryError, match="humanoid retarget compatibility evidence"):
        plan_release(config, _humanoid_lanes(), "meshy_shaman_001")


def test_humanoid_release_is_explicitly_candidate_only(config, prompt: Path) -> None:
    _approved_humanoid(
        config,
        prompt,
        compatibility={
            "name": "humanoid_retarget_compatibility",
            "passed": True,
            "report": "reports/humanoid-retarget-compatibility-001.json",
            "animation_donor_asset_id": "meshy_animations_001",
            "mapping_profile": "meshy_humanoid/v1",
            "direct_skeleton_match": True,
            "direct_rest_transform_match": False,
            "humanoid_retarget_candidate": True,
        },
    )

    plan = plan_release(config, _humanoid_lanes(), "meshy_shaman_001")

    evidence = plan.descriptor["humanoid_compatibility"]
    assert evidence["candidate_only"]
    assert not evidence["vandrel_runtime_accepted"]
    assert evidence["mapping_profile"] == "meshy_humanoid/v1"
    assert not evidence["direct_rest_transform_match"]


def test_publish_creates_immutable_release_catalog_and_manifest_record(
    config,
    lanes,
    prompt: Path,
) -> None:
    _approved_asset(config, lanes, prompt)
    root = _library(config)

    result = publish_release(config, lanes, "stone_knife_001", git_runner=FakeGit())

    assert result.release_revision == 1
    assert not result.recovered
    descriptor = json.loads((result.destination / "asset-release.json").read_text())
    assert (result.destination / "model.glb").read_bytes() == b"fixture glb"
    catalog = json.loads((root / "catalog.json").read_text())
    entry = catalog["assets"]["stone_knife_001"]["releases"][0]
    assert entry["revision"] == 1
    assert entry["descriptor_sha256"] == _sha256(
        (result.destination / "asset-release.json").read_bytes()
    )
    assert descriptor["asset_id"] == "stone_knife_001"
    assert descriptor["schema_version"] == 2
    assert descriptor["custody"]["assessment_status"] == "evaluated"
    custody_evidence = descriptor["custody"]["source_contributions"][0]["license_evidence"][0]
    assert custody_evidence["original_evidence_path"] == "licenses/fixture.txt"
    assert (result.destination / custody_evidence["release_path"]).read_bytes() == (
        b"license fixture"
    )
    manifest = ManifestRepository(config.foundry.workspace_root).load("stone_knife_001")
    assert manifest.release.released
    assert manifest.release.release_revision == 1


def test_publish_allows_new_approved_candidate_after_prior_release(
    config,
    lanes,
    prompt: Path,
) -> None:
    _approved_asset(config, lanes, prompt)
    _library(config)
    publish_release(config, lanes, "stone_knife_001", git_runner=FakeGit())
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load("stone_knife_001")
    root = config.foundry.workspace_root / "assets" / "stone_knife_001"
    model = b"second immutable candidate"
    path = root / "processed/model-r002.glb"
    path.write_bytes(model)
    manifest.artifacts.append(
        Artifact(
            artifact_id="processed-model-002",
            role="processed_model",
            stage="processed",
            format="glb",
            path="processed/model-r002.glb",
            sha256=_sha256(model),
            size_bytes=len(model),
        )
    )
    manifest.approval.approved = True
    manifest.approval.approved_at = utc_now()
    manifest.approval.approved_artifact_hashes["processed_model"] = _sha256(model)
    manifest.workflow.state = WorkflowState.APPROVED
    manifest.revision += 1
    repository.save(manifest, expected_revision=manifest.revision - 1)

    result = publish_release(config, lanes, "stone_knife_001", git_runner=FakeGit())

    assert result.release_revision == 2
    assert (result.destination / "model.glb").read_bytes() == model
    catalog = json.loads((config.foundry.asset_library_root / "catalog.json").read_text())
    assert [item["revision"] for item in catalog["assets"]["stone_knife_001"]["releases"]] == [1, 2]


def test_cli_list_and_status_show_published_revision(
    config,
    config_data: dict,
    lanes,
    prompt: Path,
    tmp_path: Path,
) -> None:
    _approved_asset(config, lanes, prompt)
    _library(config)
    publish_release(config, lanes, "stone_knife_001", git_runner=FakeGit())
    config_path = tmp_path / "foundry.toml"
    write_config(config_path, config_data)
    runner = CliRunner()

    listing = runner.invoke(app, ["list", "--config", str(config_path)])
    status = runner.invoke(
        app,
        ["status", "stone_knife_001", "--config", str(config_path)],
    )

    assert listing.exit_code == 0
    assert "r001" in listing.output
    assert status.exit_code == 0
    assert "r001" in status.output


def test_publish_rejects_unrelated_dirty_tree(config, lanes, prompt: Path) -> None:
    _approved_asset(config, lanes, prompt)
    _library(config)

    with pytest.raises(FoundryError, match="unrelated changes"):
        publish_release(
            config,
            lanes,
            "stone_knife_001",
            git_runner=FakeGit(" M README.md\n"),
        )


def test_publish_rejects_missing_lfs_policy(config, lanes, prompt: Path) -> None:
    _approved_asset(config, lanes, prompt)
    _library(config)

    with pytest.raises(FoundryError, match="Git LFS"):
        publish_release(
            config,
            lanes,
            "stone_knife_001",
            git_runner=FakeGit(lfs=False),
        )
    assert not (config.foundry.asset_library_root / "assets").exists()


def test_publish_recovers_after_release_rename_before_catalog(
    config,
    lanes,
    prompt: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _approved_asset(config, lanes, prompt)
    root = _library(config)
    original = publication._update_catalog

    def interrupt(*args, **kwargs):
        raise FoundryError("simulated interruption")

    monkeypatch.setattr(publication, "_update_catalog", interrupt)
    with pytest.raises(FoundryError, match="simulated interruption"):
        publish_release(config, lanes, "stone_knife_001", git_runner=FakeGit())

    release = root / "assets" / "stone_knife_001" / "r001"
    status = "".join(
        f"?? {path.relative_to(root).as_posix()}\n"
        for path in sorted(release.rglob("*"))
        if path.is_file()
    )
    monkeypatch.setattr(publication, "_update_catalog", original)
    result = publish_release(
        config,
        lanes,
        "stone_knife_001",
        git_runner=FakeGit(status),
    )

    assert result.recovered
    assert result.release_revision == 1
    assert (root / "catalog.json").is_file()


def test_release_plan_rejects_stale_custody_source_binding(config, lanes, prompt: Path) -> None:
    _approved_asset(config, lanes, prompt)
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load("stone_knife_001")
    source = next(item for item in manifest.artifacts if item.stage == "source")
    source.sha256 = "f" * 64
    manifest.revision += 1
    repository.save(manifest, expected_revision=manifest.revision - 1)

    with pytest.raises(FoundryError, match="custody_source_inputs_stale_or_incomplete"):
        plan_release(config, lanes, "stone_knife_001")


def test_release_plan_rejects_tampered_retained_custody_evidence(
    config, lanes, prompt: Path
) -> None:
    _approved_asset(config, lanes, prompt)
    manifest = ManifestRepository(config.foundry.workspace_root).load("stone_knife_001")
    evidence = next(item for item in manifest.artifacts if item.role == "custody_license_evidence")
    asset_root = config.foundry.workspace_root / "assets" / "stone_knife_001"
    (asset_root / evidence.path).write_bytes(b"tampered license")

    with pytest.raises(FoundryError, match="Approved release artifact changed"):
        plan_release(config, lanes, "stone_knife_001")


def test_release_plan_rejects_stale_semantic_and_approval_snapshots(
    config, lanes, prompt: Path
) -> None:
    _approved_asset(config, lanes, prompt)
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load("stone_knife_001")
    assert manifest.custody is not None
    manifest.custody.semantic_assertion_sha256 = "0" * 64
    manifest.revision += 1
    repository.save(manifest, expected_revision=manifest.revision - 1)
    with pytest.raises(FoundryError, match="custody_semantic_hash_stale"):
        plan_release(config, lanes, "stone_knife_001")

    manifest = repository.load("stone_knife_001")
    manifest.custody.semantic_assertion_sha256 = semantic_assertion_sha256(
        manifest.custody.source_contributions
    )
    manifest.approval.custody_assertion_sha256 = "0" * 64
    manifest.revision += 1
    repository.save(manifest, expected_revision=manifest.revision - 1)
    with pytest.raises(FoundryError, match="approval_custody_assertion_stale"):
        plan_release(config, lanes, "stone_knife_001")


def test_compound_exact_source_union_emits_multiple_evidence_files(
    config, lanes, prompt: Path
) -> None:
    _approved_asset(config, lanes, prompt)
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load("stone_knife_001")
    root = config.foundry.workspace_root / "assets" / "stone_knife_001"
    source_bytes = b"second source"
    evidence_bytes = b"second license"
    (root / "source/second.glb").write_bytes(source_bytes)
    (root / "custody/evidence/second-license.txt").write_bytes(evidence_bytes)
    source = Artifact(
        artifact_id="source-fixture-002",
        role="provider_source_model",
        stage="source",
        format="glb",
        path="source/second.glb",
        sha256=_sha256(source_bytes),
        size_bytes=len(source_bytes),
    )
    evidence_artifact = Artifact(
        artifact_id="custody-evidence-002",
        role="custody_license_evidence",
        stage="custody",
        format="txt",
        path="custody/evidence/second-license.txt",
        sha256=_sha256(evidence_bytes),
        size_bytes=len(evidence_bytes),
    )
    manifest.artifacts.extend([source, evidence_artifact])
    assert manifest.custody is not None
    second_input = CustodySourceInput(
        artifact_id=source.artifact_id,
        role=source.role,
        sha256=source.sha256,
        size_bytes=source.size_bytes,
    )
    second = CustodySourceContribution(
        contribution_id="fixture-contribution-002",
        source_id="fixture-provider-002",
        package_id="fixture-package-002",
        package_root="fixture-package-002",
        source_inputs=[second_input],
        rights_status="documented",
        license_evidence=[
            CustodyLicenseEvidence(
                binding_id="fixture-license-002",
                original_evidence_path="licenses/fixture-002.txt",
                evidence_sha256=evidence_artifact.sha256,
                size_bytes=evidence_artifact.size_bytes,
                scope_root="fixture-package-002",
                rights_semantics="documented",
                candidate_evidence_artifact_id=evidence_artifact.artifact_id,
            )
        ],
    )
    manifest.custody.source_contributions.append(second)
    assertion_sha = semantic_assertion_sha256(manifest.custody.source_contributions)
    manifest.custody.semantic_assertion_sha256 = assertion_sha
    manifest.approval.custody_assertion_sha256 = assertion_sha
    manifest.approval.custody_source_inputs.append(second_input)
    manifest.revision += 1
    repository.save(manifest, expected_revision=manifest.revision - 1)

    plan = plan_release(config, lanes, "stone_knife_001")
    assert len(plan.descriptor["custody"]["source_contributions"]) == 2
    evidence_files = [
        item for item in plan.descriptor["files"] if item["role"] == "custody_license_evidence"
    ]
    assert len(evidence_files) == 2
