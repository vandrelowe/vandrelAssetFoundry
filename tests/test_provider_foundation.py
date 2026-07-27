from pathlib import Path

import pytest

from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import ProviderTask
from vandrel_foundry.domain.provider import ProviderTaskStatus
from vandrel_foundry.providers.redaction import REDACTED, redact_provider_evidence
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.inspect_assets import initialize_workspace
from vandrel_foundry.services.prepare_submission import prepare_text_preview_submission


def test_redaction_removes_nested_credentials_and_signed_queries() -> None:
    evidence = {
        "Authorization": "Bearer secret",
        "nested": {
            "api_key": "secret",
            "model_url": "https://assets.meshy.ai/task/model.glb?Expires=1&Signature=secret",
        },
        "safe": "value",
    }
    redacted = redact_provider_evidence(evidence)
    assert redacted["Authorization"] == REDACTED
    assert redacted["nested"]["api_key"] == REDACTED
    assert redacted["nested"]["model_url"] == ("https://assets.meshy.ai/task/model.glb?[REDACTED]")
    assert redacted["safe"] == "value"
    assert "secret" not in str(redacted)


def test_preview_preparation_is_deterministic_and_local(config, lanes, prompt: Path) -> None:
    initialize_workspace(config.foundry.workspace_root)
    manifest = create_asset(
        config,
        lanes,
        "stone_knife_001",
        "static_prop",
        "Stone Knife",
        prompt,
    )
    first = prepare_text_preview_submission(config.foundry.workspace_root, manifest)
    second = prepare_text_preview_submission(config.foundry.workspace_root, manifest)
    assert first == second
    assert first.task_key == "meshy_preview_001"
    assert first.request.model_dump() == {
        "mode": "preview",
        "prompt": "a rough stone knife",
        "target_formats": ["glb"],
    }
    assert len(first.request_fingerprint) == 64
    assert manifest.generation.tasks == []


def test_preview_preparation_increments_append_only_attempt(config, lanes, prompt: Path) -> None:
    initialize_workspace(config.foundry.workspace_root)
    manifest = create_asset(
        config,
        lanes,
        "stone_knife_001",
        "static_prop",
        "Stone Knife",
        prompt,
    )
    manifest.generation.tasks.append(
        ProviderTask(
            task_key="meshy_preview_001",
            provider="meshy",
            operation="text_to_3d_preview",
            attempt=1,
            status=ProviderTaskStatus.AMBIGUOUS,
        )
    )
    prepared = prepare_text_preview_submission(config.foundry.workspace_root, manifest)
    assert prepared.task_key == "meshy_preview_002"
    assert prepared.attempt == 2


def test_preview_preparation_rejects_empty_prompt(config, lanes, prompt: Path) -> None:
    initialize_workspace(config.foundry.workspace_root)
    manifest = create_asset(
        config,
        lanes,
        "stone_knife_001",
        "static_prop",
        "Stone Knife",
        prompt,
    )
    asset_prompt = (
        config.foundry.workspace_root / "assets" / "stone_knife_001" / "input" / "prompt.txt"
    )
    asset_prompt.write_text("   ", encoding="utf-8")
    with pytest.raises(FoundryError, match="prompt is empty"):
        prepare_text_preview_submission(config.foundry.workspace_root, manifest)
