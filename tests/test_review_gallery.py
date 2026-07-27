import hashlib
from pathlib import Path

import pytest

from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact
from vandrel_foundry.services.build_review_gallery import build_review_gallery
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.inspect_assets import initialize_workspace
from vandrel_foundry.storage.manifests import ManifestRepository


def test_review_gallery_embeds_preview_and_never_overwrites(config, lanes, prompt: Path) -> None:
    initialize_workspace(config.foundry.workspace_root)
    manifest = create_asset(
        config, lanes, "gallery_prop_001", "static_prop", "<Gallery & Prop>", prompt
    )
    asset_root = config.foundry.workspace_root / "assets/gallery_prop_001"
    preview = asset_root / "preview/local-preview-001.png"
    preview.parent.mkdir(parents=True, exist_ok=True)
    content = b"\x89PNG\r\n\x1a\nfixture"
    preview.write_bytes(content)
    manifest.artifacts.append(
        Artifact(
            artifact_id="local_preview_001",
            role="local_preview",
            stage="review",
            format="png",
            path="preview/local-preview-001.png",
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
        )
    )
    manifest.revision += 1
    ManifestRepository(config.foundry.workspace_root).save(
        manifest, "test.preview", expected_revision=1
    )

    first = build_review_gallery(config)
    second = build_review_gallery(config)
    rendered = first.read_text(encoding="utf-8")

    assert first.name == "review-gallery-001.html"
    assert second.name == "review-gallery-002.html"
    assert "&lt;Gallery &amp; Prop&gt;" in rendered
    assert "data:image/png;base64," in rendered
    assert ManifestRepository(config.foundry.workspace_root).load("gallery_prop_001").revision == 2

    preview.write_bytes(content[:8] + b"x" * (len(content) - 8))
    with pytest.raises(FoundryError, match="Recorded preview changed"):
        build_review_gallery(config)
