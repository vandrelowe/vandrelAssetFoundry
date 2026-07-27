from pathlib import Path

from vandrel_foundry.domain.manifest import Artifact
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.inspect_assets import initialize_workspace
from vandrel_foundry.services.render_missing_previews import render_missing_previews
from vandrel_foundry.storage.manifests import ManifestRepository


def test_render_missing_previews_selects_only_eligible_missing_candidates(
    config, lanes, prompt: Path
) -> None:
    initialize_workspace(config.foundry.workspace_root)
    repository = ManifestRepository(config.foundry.workspace_root)
    for asset_id, state in (
        ("missing_preview_001", WorkflowState.REVIEW),
        ("existing_preview_001", WorkflowState.REVIEW),
        ("draft_preview_001", WorkflowState.DRAFT),
    ):
        manifest = create_asset(config, lanes, asset_id, "static_prop", asset_id, prompt)
        manifest.workflow.state = state
        if asset_id == "existing_preview_001":
            manifest.artifacts.append(
                Artifact(
                    artifact_id="local_preview_001",
                    role="local_preview",
                    stage="review",
                    format="png",
                    path="preview/existing.png",
                    sha256="0" * 64,
                    size_bytes=0,
                )
            )
        manifest.revision += 1
        repository.save(manifest, "test.state", expected_revision=1)

    called: list[str] = []

    def fake_renderer(settings, asset_id: str) -> Artifact:
        called.append(asset_id)
        return Artifact(
            artifact_id="local_preview_001",
            role="local_preview",
            stage="review",
            format="png",
            path="preview/generated.png",
            sha256="1" * 64,
            size_bytes=1,
        )

    result = render_missing_previews(config, renderer=fake_renderer)

    assert called == ["missing_preview_001"]
    assert len(result) == 1
