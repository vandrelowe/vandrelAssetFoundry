import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.experiment_semantic_mask import (
    VARIANTS,
    experiment_semantic_mask,
)
from vandrel_foundry.services.inspect_assets import initialize_workspace
from vandrel_foundry.services.validate_godot import ProcessResult
from vandrel_foundry.storage.manifests import ManifestRepository


def _processed_asset(config, lanes, prompt: Path, asset_id: str) -> tuple[Path, str]:
    initialize_workspace(config.foundry.workspace_root)
    manifest = create_asset(
        config,
        lanes,
        asset_id,
        "static_prop",
        "Semantic Mask Asset",
        prompt,
    )
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    source = asset_root / "processed/model.glb"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"immutable glb")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest.artifacts.append(
        Artifact(
            artifact_id="processed_glb_001",
            role="processed_model",
            stage="processed",
            format="glb",
            path="processed/model.glb",
            sha256=digest,
            size_bytes=source.stat().st_size,
        )
    )
    manifest.workflow.state = WorkflowState.REVIEW
    manifest.revision += 1
    ManifestRepository(config.foundry.workspace_root).save(
        manifest,
        "test.processed",
        expected_revision=1,
    )
    return asset_root, digest


def _strict_mask(path: Path) -> None:
    image = Image.new("RGB", (4, 4))
    image.putdata(
        [(255, 0, 0)] * 4
        + [(0, 255, 0)] * 4
        + [(0, 0, 255)] * 4
        + [(255, 255, 255)] * 4
    )
    image.save(path)


def test_semantic_mask_experiment_records_candidate_and_isolation_evidence(
    config, lanes, prompt: Path, tmp_path: Path
) -> None:
    asset_root, digest = _processed_asset(
        config,
        lanes,
        prompt,
        "semantic_mask_asset_001",
    )
    candidate = tmp_path / "candidate.png"
    _strict_mask(candidate)
    executable = tmp_path / "blender.exe"
    executable.write_bytes(b"fixture")
    config.tools.blender_executable = executable

    def fake_runner(arguments, cwd, environment, timeout_seconds, maximum_output_bytes):
        assert "--disable-autoexec" in arguments
        assert "MESHY_API_KEY" not in environment
        input_path, mask_path, output_root, measurement_path = map(Path, arguments[-4:])
        assert input_path.read_bytes() == b"immutable glb"
        assert mask_path.read_bytes() == candidate.read_bytes()
        for name in VARIANTS:
            Image.new("RGBA", (16, 16), (120, 80, 40, 255)).save(
                output_root / f"{name}.png"
            )
        measurement_path.write_text(
            json.dumps(
                {
                    "blender_version": "fixture",
                    "resolution": [512, 512],
                    "variants": list(VARIANTS),
                    "mask_sampling": "Non-Color, Closest",
                }
            ),
            encoding="utf-8",
        )
        return ProcessResult(0, "rendered", "", False, False, 0.1)

    contact_sheet = experiment_semantic_mask(
        config,
        "semantic_mask_asset_001",
        candidate,
        runner=fake_runner,
    )

    updated = ManifestRepository(config.foundry.workspace_root).load(
        "semantic_mask_asset_001"
    )
    assert contact_sheet.role == "semantic_mask_experiment_contact_sheet"
    assert updated.workflow.state is WorkflowState.REVIEW
    assert sum(
        item.role == "semantic_mask_variant_preview" for item in updated.artifacts
    ) == len(VARIANTS)
    mask_artifact = next(
        item for item in updated.artifacts if item.role == "semantic_mask_candidate"
    )
    assert (asset_root / str(mask_artifact.path)).read_bytes() == candidate.read_bytes()
    report_artifact = next(
        item
        for item in updated.artifacts
        if item.role == "semantic_mask_experiment_report"
    )
    report = json.loads(
        (asset_root / str(report_artifact.path)).read_text(encoding="utf-8")
    )
    assert report["source_sha256"] == digest
    assert report["mask_facts"]["strict_palette_passed"] is True
    assert report["usable_for_material_authoring"] is False
    assert "semantic crossing" in report["interpretation"]


def test_semantic_mask_experiment_rejects_non_palette_pixels(
    config, lanes, prompt: Path, tmp_path: Path
) -> None:
    _processed_asset(config, lanes, prompt, "semantic_mask_invalid_001")
    candidate = tmp_path / "invalid.png"
    Image.new("RGB", (4, 4), (12, 34, 56)).save(candidate)
    executable = tmp_path / "blender.exe"
    executable.write_bytes(b"fixture")
    config.tools.blender_executable = executable

    with pytest.raises(FoundryError, match="outside the strict palette"):
        experiment_semantic_mask(config, "semantic_mask_invalid_001", candidate)

    asset_root = config.foundry.workspace_root / "assets/semantic_mask_invalid_001"
    assert not (asset_root / "masks/semantic-mask-experiment-001.png").exists()


def test_semantic_mask_experiment_removes_partial_outputs_after_runner_failure(
    config, lanes, prompt: Path, tmp_path: Path
) -> None:
    asset_root, _ = _processed_asset(
        config,
        lanes,
        prompt,
        "semantic_mask_failure_001",
    )
    candidate = tmp_path / "candidate.png"
    _strict_mask(candidate)
    executable = tmp_path / "blender.exe"
    executable.write_bytes(b"fixture")
    config.tools.blender_executable = executable

    def failed_runner(arguments, cwd, environment, timeout_seconds, maximum_output_bytes):
        return ProcessResult(1, "", "failed", False, False, 0.1)

    with pytest.raises(FoundryError, match="semantic-mask experiment failed"):
        experiment_semantic_mask(
            config,
            "semantic_mask_failure_001",
            candidate,
            runner=failed_runner,
        )

    assert not (asset_root / "masks/semantic-mask-experiment-001.png").exists()
    assert not (asset_root / "preview/semantic-mask-experiment-001").exists()
    assert not (asset_root / "reports/semantic-mask-experiment-001.json").exists()
