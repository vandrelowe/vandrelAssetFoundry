import json
from pathlib import Path

import pytest
from PIL import Image

from tests.test_humanoid_retarget import _add_processed_asset, _meshy_document
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.apply_texture_mask import apply_texture_mask
from vandrel_foundry.services.inspect_assets import initialize_workspace
from vandrel_foundry.services.validate_godot import ProcessResult
from vandrel_foundry.storage.manifests import ManifestRepository


def test_applies_mask_and_records_immutable_hash_bound_outputs(
    config,
    humanoid_lanes,
    prompt: Path,
    tmp_path: Path,
) -> None:
    initialize_workspace(config.foundry.workspace_root)
    _add_processed_asset(
        config,
        humanoid_lanes,
        prompt,
        "masked_character_001",
        _meshy_document(animations=2),
    )
    executable = tmp_path / "blender.exe"
    executable.write_bytes(b"fixture")
    config.tools.blender_executable = executable
    mask_source = tmp_path / "skull-mask.png"
    mask = Image.new("L", (8, 8), 0)
    for x in range(2, 6):
        for y in range(1, 4):
            mask.putpixel((x, y), 255)
    mask.save(mask_source)

    def fake_runner(arguments, cwd, environment, timeout_seconds, maximum_output_bytes):
        assert "--disable-autoexec" in arguments
        assert "MESHY_API_KEY" not in environment
        input_path, copied_mask, output_path, report_path = map(
            Path, arguments[-5:-1]
        )
        assert copied_mask != mask_source
        assert copied_mask.read_bytes() == mask_source.read_bytes()
        output_path.write_bytes(input_path.read_bytes())
        report_path.write_text(
            json.dumps(
                {
                    "blender_version": "fixture",
                    "coverage_fraction": 0.1875,
                    "animation_count_before": 2,
                }
            ),
            encoding="utf-8",
        )
        return ProcessResult(0, "recolored", "", False, False, 0.1)

    result = apply_texture_mask(
        config,
        "masked_character_001",
        mask_source,
        "#fae5b5",
        runner=fake_runner,
    )

    saved = ManifestRepository(config.foundry.workspace_root).load(
        "masked_character_001"
    )
    assert result.model.artifact_id == "processed_glb_002"
    assert result.model.processor.name == "blender_texture_mask_recolor"
    assert result.model.derived_from == [
        "processed_glb_001",
        "texture_region_mask_002",
    ]
    assert result.mask.role == "texture_region_mask"
    assert result.report.role == "texture_mask_processing_report"
    assert result.log.role == "texture_mask_processing_log"
    assert result.coverage_fraction == 0.1875
    assert saved.workflow.state is WorkflowState.PROCESSED
    assert saved.validation.result == "not_run"
    assert not saved.approval.approved


def test_rejects_empty_mask_before_creating_outputs(
    config,
    tmp_path: Path,
) -> None:
    mask_source = tmp_path / "empty.png"
    Image.new("L", (8, 8), 0).save(mask_source)

    with pytest.raises(FoundryError, match="nonempty"):
        apply_texture_mask(config, "missing", mask_source, "#fae5b5")


def test_failed_blender_run_removes_partial_outputs(
    config,
    humanoid_lanes,
    prompt: Path,
    tmp_path: Path,
) -> None:
    initialize_workspace(config.foundry.workspace_root)
    _add_processed_asset(
        config,
        humanoid_lanes,
        prompt,
        "failed_mask_character_001",
        _meshy_document(),
    )
    executable = tmp_path / "blender.exe"
    executable.write_bytes(b"fixture")
    config.tools.blender_executable = executable
    mask_source = tmp_path / "bounded-mask.png"
    mask = Image.new("L", (8, 8), 0)
    mask.putpixel((3, 3), 255)
    mask.save(mask_source)

    def failing_runner(arguments, cwd, environment, timeout_seconds, maximum_output_bytes):
        return ProcessResult(1, "", "failed", False, False, 0.1)

    with pytest.raises(FoundryError, match="processing failed"):
        apply_texture_mask(
            config,
            "failed_mask_character_001",
            mask_source,
            "#fae5b5",
            runner=failing_runner,
        )

    asset_root = (
        config.foundry.workspace_root
        / "assets"
        / "failed_mask_character_001"
    )
    assert not (asset_root / "processed" / "texture_mask").exists()
    assert not list((asset_root / "reports").glob("texture-mask-processing-*"))
