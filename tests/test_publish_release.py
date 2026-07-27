import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

import vandrel_foundry.services.publish_release as publication
from tests.conftest import write_config
from vandrel_foundry.cli import app
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.lanes import LaneConfiguration
from vandrel_foundry.domain.manifest import Artifact, utc_now
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
    manifest = ManifestRepository(config.foundry.workspace_root).load("stone_knife_001")
    assert manifest.release.released
    assert manifest.release.release_revision == 1


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
