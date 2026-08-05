from pathlib import Path

from vandrel_foundry.domain.lanes import LaneConfiguration
from vandrel_foundry.domain.manifest import Artifact
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.reclassify_asset import reclassify_asset_lane
from vandrel_foundry.storage.manifests import ManifestRepository


def test_reclassify_processed_asset_resets_lane_validation_with_audit_reason(
    config, lanes, prompt: Path
) -> None:
    create_asset(config, lanes, "hero_rock_001", "static_prop", "Hero Rock", prompt)
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load("hero_rock_001")
    manifest.artifacts.append(
        Artifact(
            artifact_id="processed_glb_001",
            role="processed_model",
            stage="processed",
            format="glb",
            path="processed/model.glb",
            sha256="a" * 64,
            size_bytes=1,
        )
    )
    manifest.workflow.state = WorkflowState.REVIEW
    manifest.validation.result = "passed"
    manifest.validation.checks = [{"name": "triangle_budget", "passed": True}]
    manifest.revision += 1
    repository.save(manifest, expected_revision=manifest.revision - 1)
    expanded = LaneConfiguration.model_validate(
        {
            "lanes": {
                **lanes.model_dump(mode="json")["lanes"],
                "environment_near": {
                    "wrapper_template": "environment_near",
                    "maximum_triangles": 20000,
                    "collision_policy": "manual_review",
                },
            }
        }
    )

    saved = reclassify_asset_lane(
        config,
        expanded,
        "hero_rock_001",
        "environment_near",
        "Unique hero outcropping.",
    )

    assert saved.asset.lane == "environment_near"
    assert saved.workflow.state is WorkflowState.PROCESSED
    assert saved.validation.result == "not_run"
    assert saved.validation.checks == []
    assert saved.quality.targets["lane_reclassification"] == {
        "from": "static_prop",
        "to": "environment_near",
        "reason": "Unique hero outcropping.",
    }
