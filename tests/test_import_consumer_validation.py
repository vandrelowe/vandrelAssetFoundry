import hashlib
import json
from pathlib import Path

import pytest

from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.import_consumer_validation import (
    import_vandrel_character_validation,
)
from vandrel_foundry.services.inspect_assets import initialize_workspace
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath


def _candidate(config, humanoid_lanes, prompt: Path, asset_id: str = "consumer_test") -> str:
    initialize_workspace(config.foundry.workspace_root)
    manifest = create_asset(
        config,
        humanoid_lanes,
        asset_id,
        "humanoid",
        "Consumer Test",
        prompt,
    )
    content = b"processed-character"
    digest = hashlib.sha256(content).hexdigest()
    relative = RelativeManifestPath("processed/model.fbx")
    path = config.foundry.workspace_root / "assets" / asset_id / str(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    manifest.artifacts.append(
        Artifact(
            artifact_id="processed_fbx_001",
            role="processed_model",
            stage="processed",
            format="fbx",
            path=relative,
            sha256=digest,
            size_bytes=len(content),
        )
    )
    manifest.workflow.state = WorkflowState.REVIEW
    manifest.validation.result = "passed"
    manifest.revision += 1
    ManifestRepository(config.foundry.workspace_root).save(
        manifest,
        "fixture.processed",
        expected_revision=manifest.revision - 1,
    )
    return digest


def _ledger(
    path: Path,
    asset_id: str,
    digest: str | None,
    severity: str,
    *,
    exact_provenance: bool = False,
) -> None:
    evidence = {
        "character_id": "consumer_character",
        "consumer_scene_path": "res://character.tscn",
        "status": "fail",
        "generic_asset_defects": [
            {
                "code": "rig.visible_mesh_not_skinned",
                "severity": severity,
                "detail": "Visible mesh is not driven by the rig.",
                "owner": "asset_foundry",
            }
        ],
        "vandrel_runtime_corrections": [],
        "evidence": {"animation_csv": "debug_output/run/animation_grounding.csv"},
    }
    if digest is not None:
        evidence["foundry_binding"] = {
            "asset_id": asset_id,
            "model_sha256": digest,
        }
        if exact_provenance:
            evidence["foundry_binding"].update(
                {
                    "manifest_revision": 84,
                    "model_artifact_id": "processed_fbx_012",
                    "walk_artifact_id": "processed_animation_walk_006",
                    "walk_sha256": "4" * 64,
                    "run_artifact_id": "processed_animation_run_006",
                    "run_sha256": "f" * 64,
                    "provider_task_key": "meshy_rigging_001",
                    "provider_task_id": "provider-task-id",
                    "matching_library_revision": None,
                }
            )
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "consumer": "vandrel",
                "assets": {"consumer_character": evidence},
            }
        ),
        encoding="utf-8",
    )


def _ground_audit(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "tolerance_m": 0.03,
                "characters": [
                    {
                        "character_id": "consumer_character",
                        "scene_path": "res://character.tscn",
                        "scale": 1.0,
                        "current_base_offset_y": -0.12,
                        "sampled_animation_count": 99,
                        "residual_min_y_m": -0.02,
                        "residual_max_y_m": 0.02,
                        "within_tolerance": 99,
                        "recommended_base_offset_y": -0.12,
                        "review_directory": "C:/consumer/debug_output/review",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_hash_bound_generic_blocker_blocks_candidate(
    config,
    humanoid_lanes,
    prompt: Path,
    tmp_path: Path,
) -> None:
    digest = _candidate(config, humanoid_lanes, prompt)
    ledger = tmp_path / "acceptance.json"
    ground_audit = tmp_path / "ground-audit.json"
    _ledger(ledger, "consumer_test", digest, "blocker", exact_provenance=True)
    _ground_audit(ground_audit)

    result = import_vandrel_character_validation(
        config,
        "consumer_test",
        ledger,
        "consumer_character",
        ground_audit_path=ground_audit,
    )

    assert result.hash_bound
    assert result.generic_gate_passed is False
    saved = ManifestRepository(config.foundry.workspace_root).load("consumer_test")
    assert saved.workflow.state is WorkflowState.BLOCKED
    assert saved.validation.result == "failed"
    assert saved.approval.approved is False
    report_path = config.foundry.workspace_root / "assets/consumer_test" / str(result.report.path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["consumer_contract_revision"] == "vandrel@16cbf78d"
    assert report["asset_evidence"]["foundry_binding"]["manifest_revision"] == 84
    assert (
        report["asset_evidence"]["foundry_binding"]["walk_artifact_id"]
        == "processed_animation_walk_006"
    )
    assert report["grounding_audit_records"][0]["within_tolerance"] == 99


def test_unbound_evidence_requires_explicit_diagnostic_mode(
    config,
    humanoid_lanes,
    prompt: Path,
    tmp_path: Path,
) -> None:
    _candidate(config, humanoid_lanes, prompt)
    ledger = tmp_path / "acceptance.json"
    _ledger(ledger, "consumer_test", None, "blocker")

    with pytest.raises(FoundryError, match="not bound"):
        import_vandrel_character_validation(
            config,
            "consumer_test",
            ledger,
            "consumer_character",
        )

    result = import_vandrel_character_validation(
        config,
        "consumer_test",
        ledger,
        "consumer_character",
        allow_unbound_diagnostic=True,
    )
    assert not result.hash_bound
    assert result.generic_gate_passed is None
    saved = ManifestRepository(config.foundry.workspace_root).load("consumer_test")
    assert saved.workflow.state is WorkflowState.REVIEW
    assert saved.validation.result == "passed"
