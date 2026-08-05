from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.lanes import LaneConfiguration
from vandrel_foundry.domain.manifest import AssetManifest, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.domain.workflow_policy import invalidate_approval, transition_workflow
from vandrel_foundry.storage.manifests import ManifestRepository


def reclassify_asset_lane(
    config: FoundryConfig,
    lanes: LaneConfiguration,
    asset_id: str,
    lane: str,
    reason: str,
) -> AssetManifest:
    reason = reason.strip()
    if lane not in lanes.lanes:
        raise FoundryError(f"Unknown asset lane: {lane}")
    if not reason:
        raise FoundryError("Lane reclassification requires a reason.")
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.release.released:
        raise FoundryError("Released candidates require a new revision before reclassification.")
    if not any(item.role == "processed_model" for item in manifest.artifacts):
        raise FoundryError("Lane reclassification requires a processed candidate.")
    previous = manifest.asset.lane
    if previous == lane:
        raise FoundryError(f"Asset is already in lane: {lane}")
    invalidate_approval(manifest)
    manifest.asset.lane = lane
    manifest.validation.result = "not_run"
    manifest.validation.checks = []
    manifest.quality.targets["lane_reclassification"] = {
        "from": previous,
        "to": lane,
        "reason": reason,
    }
    transition_workflow(manifest, WorkflowState.PROCESSED)
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    repository.save(
        manifest,
        "asset.lane_reclassified",
        expected_revision=manifest.revision - 1,
    )
    return manifest
