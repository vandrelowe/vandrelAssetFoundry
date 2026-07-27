from collections.abc import Callable

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.inspect_assets import discover_assets
from vandrel_foundry.services.render_preview import render_local_preview

PreviewRenderer = Callable[[FoundryConfig, str], Artifact]
ELIGIBLE_STATES = {
    WorkflowState.PROCESSED,
    WorkflowState.REVIEW,
    WorkflowState.APPROVED,
}


def render_missing_previews(
    config: FoundryConfig,
    renderer: PreviewRenderer = render_local_preview,
) -> list[Artifact]:
    manifests, warnings = discover_assets(config.foundry.workspace_root)
    if warnings:
        raise FoundryError(f"Preview batch requires valid manifests: {warnings[0]}")
    rendered: list[Artifact] = []
    for manifest in manifests:
        if manifest.workflow.state not in ELIGIBLE_STATES:
            continue
        if any(artifact.role == "local_preview" for artifact in manifest.artifacts):
            continue
        rendered.append(renderer(config, manifest.asset.asset_id))
    return rendered
