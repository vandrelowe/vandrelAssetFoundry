import hashlib
import json

import pytest
from pydantic import ValidationError

from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, ScaleCalibration
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.calibrate_scale import calibrate_asset_scale
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.storage.manifests import ManifestRepository


def _candidate(config, lanes, prompt):
    manifest = create_asset(config, lanes, "scale_tree_001", "static_prop", "Scale Tree", prompt)
    asset_root = config.foundry.workspace_root / "assets" / "scale_tree_001"
    model_bytes = b"processed-model"
    model_path = asset_root / "processed/model.glb"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_bytes(model_bytes)
    report = {
        "schema_version": 1,
        "blender_version": "fixture",
        "geometry_bounds": {
            "minimum": [-0.5, -0.25, 0.0],
            "maximum": [0.5, 0.25, 2.0],
            "dimensions": [1.0, 0.5, 2.0],
            "height_axis": "z",
        },
    }
    report_bytes = (json.dumps(report) + "\n").encode()
    report_path = asset_root / "reports/local-preview-001.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_bytes(report_bytes)
    model = Artifact(
        artifact_id="processed_model_001",
        role="processed_model",
        stage="processed",
        format="glb",
        path="processed/model.glb",
        sha256=hashlib.sha256(model_bytes).hexdigest(),
        size_bytes=len(model_bytes),
        processor=Processor(name="fixture", version="1"),
    )
    preview_report = Artifact(
        artifact_id="local_preview_report_001",
        role="local_preview_report",
        stage="review",
        format="json",
        path="reports/local-preview-001.json",
        sha256=hashlib.sha256(report_bytes).hexdigest(),
        size_bytes=len(report_bytes),
        derived_from=[model.artifact_id],
        processor=Processor(name="blender_preview", version="1"),
    )
    manifest.artifacts.extend([model, preview_report])
    manifest.workflow.state = WorkflowState.REVIEW
    manifest.revision += 1
    ManifestRepository(config.foundry.workspace_root).save(
        manifest, expected_revision=manifest.revision - 1
    )
    return model, report_path


def _replace_preview_bounds(config, report_path, bounds):
    report = {
        "schema_version": 1,
        "blender_version": "fixture",
        "geometry_bounds": {**bounds, "height_axis": "z"},
    }
    report_bytes = (json.dumps(report) + "\n").encode()
    report_path.write_bytes(report_bytes)
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load("scale_tree_001")
    artifact = next(item for item in manifest.artifacts if item.role == "local_preview_report")
    artifact.sha256 = hashlib.sha256(report_bytes).hexdigest()
    artifact.size_bytes = len(report_bytes)
    manifest.revision += 1
    repository.save(manifest, expected_revision=manifest.revision - 1)


def test_scale_calibration_binds_bounds_and_computes_baseline(config, lanes, prompt):
    model, _ = _candidate(config, lanes, prompt)

    result = calibrate_asset_scale(
        config,
        "scale_tree_001",
        14.0,
        "Art reviewer",
        variation_min_multiplier=0.8,
        variation_max_multiplier=1.2,
        notes="Compared with the 1.8 m human reference.",
    )

    assert result.status == "approved"
    assert result.processed_model_sha256 == model.sha256
    assert result.source_dimensions == [1.0, 0.5, 2.0]
    assert result.target_height_meters == 14.0
    assert result.baseline_uniform_scale == 7.0
    assert result.variation_min_multiplier == 0.8
    assert result.variation_max_multiplier == 1.2
    saved = ManifestRepository(config.foundry.workspace_root).load("scale_tree_001")
    assert any(check["name"] == "scale_calibration" for check in saved.validation.checks)


def test_scale_calibration_rejects_changed_preview_evidence(config, lanes, prompt):
    _, report_path = _candidate(config, lanes, prompt)
    report_path.write_text("{}", encoding="utf-8")

    with pytest.raises(FoundryError, match="changed after registration"):
        calibrate_asset_scale(config, "scale_tree_001", 14.0, "Reviewer")


def test_scale_calibration_rejects_invalid_variation(config, lanes, prompt):
    _candidate(config, lanes, prompt)

    with pytest.raises(FoundryError, match="minimum cannot exceed maximum"):
        calibrate_asset_scale(
            config,
            "scale_tree_001",
            14.0,
            "Reviewer",
            variation_min_multiplier=1.2,
            variation_max_multiplier=0.8,
        )


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_scale_calibration_rejects_non_finite_inputs(config, lanes, prompt, invalid):
    _candidate(config, lanes, prompt)

    with pytest.raises(FoundryError, match="finite and positive"):
        calibrate_asset_scale(config, "scale_tree_001", invalid, "Reviewer")


@pytest.mark.parametrize(
    "bounds, message",
    [
        (
            {
                "minimum": [float("nan"), 0.0, 0.0],
                "maximum": [1.0, 1.0, 2.0],
                "dimensions": [1.0, 1.0, 2.0],
            },
            "geometry bounds are invalid",
        ),
        (
            {
                "minimum": [1.0, 0.0, 0.0],
                "maximum": [0.0, 1.0, 2.0],
                "dimensions": [1.0, 1.0, 2.0],
            },
            "minimum cannot exceed maximum",
        ),
        (
            {
                "minimum": [0.0, 0.0, 0.0],
                "maximum": [1.0, 1.0, 2.0],
                "dimensions": [1.01, 1.0, 2.0],
            },
            "must equal bounds maximum minus minimum",
        ),
    ],
)
def test_scale_calibration_rejects_invalid_report_geometry(config, lanes, prompt, bounds, message):
    _, report_path = _candidate(config, lanes, prompt)
    _replace_preview_bounds(config, report_path, bounds)

    with pytest.raises(FoundryError, match=message):
        calibrate_asset_scale(config, "scale_tree_001", 14.0, "Reviewer")


def test_scale_calibration_accepts_dimension_rounding_within_tolerance(config, lanes, prompt):
    _, report_path = _candidate(config, lanes, prompt)
    _replace_preview_bounds(
        config,
        report_path,
        {
            "minimum": [0.0, 0.0, 0.0],
            "maximum": [1.0, 1.0, 2.0],
            "dimensions": [1.0000005, 1.0, 2.0],
        },
    )

    result = calibrate_asset_scale(config, "scale_tree_001", 14.0, "Reviewer")

    assert result.status == "approved"


@pytest.mark.parametrize(
    "value, message",
    [
        ({"target_height_meters": float("nan")}, "greater than 0"),
        (
            {
                "source_bounds_min": [0.0, 0.0, 0.0],
                "source_bounds_max": [1.0, 1.0, 2.0],
                "source_dimensions": [1.0, 1.1, 2.0],
            },
            "must equal bounds maximum minus minimum",
        ),
    ],
)
def test_manifest_scale_domain_rejects_invalid_partial_evidence(value, message):
    with pytest.raises(ValidationError, match=message):
        ScaleCalibration.model_validate(value)
