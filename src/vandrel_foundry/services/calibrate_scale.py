import hashlib
import json
import math

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import (
    ScaleCalibration,
    utc_now,
    validate_scale_measurements,
)
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.domain.workflow_policy import invalidate_approval
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import contained_path


def calibrate_asset_scale(
    config: FoundryConfig,
    asset_id: str,
    target_height_meters: float,
    reviewer: str,
    *,
    variation_min_multiplier: float = 0.9,
    variation_max_multiplier: float = 1.1,
    notes: str = "",
) -> ScaleCalibration:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.workflow.state not in {WorkflowState.PROCESSED, WorkflowState.REVIEW}:
        raise FoundryError(f"Scale calibration requires processed or review state: {asset_id}")
    if not math.isfinite(target_height_meters) or target_height_meters <= 0:
        raise FoundryError("Scale calibration target height must be finite and positive.")
    if any(
        not math.isfinite(value) or value <= 0
        for value in (variation_min_multiplier, variation_max_multiplier)
    ):
        raise FoundryError("Scale variation multipliers must be finite and positive.")
    if variation_min_multiplier > variation_max_multiplier:
        raise FoundryError("Scale variation minimum cannot exceed maximum.")
    reviewer = reviewer.strip()
    if not reviewer:
        raise FoundryError("Scale calibration requires a reviewer name.")

    processed = [item for item in manifest.artifacts if item.role == "processed_model"]
    reports = [item for item in manifest.artifacts if item.role == "local_preview_report"]
    if not processed or not reports:
        raise FoundryError("Scale calibration requires a processed model and local preview report.")
    model = processed[-1]
    report_artifact = reports[-1]
    if model.artifact_id not in report_artifact.derived_from:
        raise FoundryError("Latest preview report is not derived from the current processed model.")
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    report_path = contained_path(asset_root, report_artifact.path)
    digest = hashlib.sha256(report_path.read_bytes()).hexdigest()
    if digest != report_artifact.sha256:
        raise FoundryError("Scale calibration preview report changed after registration.")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    bounds = report.get("geometry_bounds")
    if not isinstance(bounds, dict) or bounds.get("height_axis") != "z":
        raise FoundryError("Scale calibration requires evaluated Blender geometry bounds.")
    minimum = _vector(bounds, "minimum")
    maximum = _vector(bounds, "maximum")
    dimensions = _vector(bounds, "dimensions")
    try:
        validate_scale_measurements(minimum, maximum, dimensions, require_bounds=True)
    except ValueError as exc:
        raise FoundryError(f"Scale calibration geometry bounds are invalid: {exc}") from exc
    source_height = dimensions[2]

    calibration = ScaleCalibration(
        status="approved",
        processed_model_sha256=model.sha256,
        preview_report_sha256=report_artifact.sha256,
        source_bounds_min=minimum,
        source_bounds_max=maximum,
        source_dimensions=dimensions,
        target_height_meters=target_height_meters,
        baseline_uniform_scale=target_height_meters / source_height,
        variation_min_multiplier=variation_min_multiplier,
        variation_max_multiplier=variation_max_multiplier,
        reference_standard="meter_grid_and_human_1_8m",
        reviewer=reviewer,
        approved_at=utc_now(),
        notes=notes.strip(),
    )
    invalidate_approval(manifest)
    manifest.scale_calibration = calibration
    manifest.validation.checks = [
        check for check in manifest.validation.checks if check.get("name") != "scale_calibration"
    ] + [
        {
            "name": "scale_calibration",
            "passed": True,
            "processed_model_sha256": model.sha256,
            "preview_report_sha256": report_artifact.sha256,
            "target_height_meters": target_height_meters,
            "baseline_uniform_scale": calibration.baseline_uniform_scale,
        }
    ]
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    repository.save(manifest, "scale.calibrated", expected_revision=manifest.revision - 1)
    return calibration


def _vector(bounds: dict[str, object], name: str) -> list[float]:
    value = bounds.get(name)
    if (
        not isinstance(value, list)
        or len(value) != 3
        or any(
            isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item)
            for item in value
        )
    ):
        raise FoundryError(f"Scale calibration geometry bounds are invalid: {name}")
    return [float(item) for item in value]
