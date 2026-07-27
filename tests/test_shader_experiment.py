import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.experiment_shaders import VARIANTS, experiment_shader_variants
from vandrel_foundry.services.inspect_assets import initialize_workspace
from vandrel_foundry.services.validate_godot import ProcessResult
from vandrel_foundry.storage.manifests import ManifestRepository


def test_shader_experiment_records_immutable_variant_evidence(
    config, lanes, prompt: Path, tmp_path: Path
) -> None:
    initialize_workspace(config.foundry.workspace_root)
    manifest = create_asset(
        config,
        lanes,
        "shader_asset_001",
        "static_prop",
        "Shader Asset",
        prompt,
    )
    asset_root = config.foundry.workspace_root / "assets/shader_asset_001"
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
        manifest, "test.processed", expected_revision=1
    )
    executable = tmp_path / "blender.exe"
    executable.write_bytes(b"fixture")
    config.tools.blender_executable = executable

    def fake_runner(arguments, cwd, environment, timeout_seconds, maximum_output_bytes):
        assert "--disable-autoexec" in arguments
        assert "MESHY_API_KEY" not in environment
        input_path, output_root, measurement_path = map(Path, arguments[-3:])
        assert input_path.read_bytes() == b"immutable glb"
        for name in VARIANTS:
            Image.new("RGBA", (16, 16), (120, 80, 40, 255)).save(output_root / f"{name}.png")
        measurement_path.write_text(
            json.dumps(
                {
                    "blender_version": "fixture",
                    "resolution": [512, 512],
                    "variants": list(VARIANTS),
                    "variant_definitions": {name: name for name in VARIANTS},
                    "measured_material_facts": {
                        "unique_material_count": 1,
                        "image_texture_node_count": 2,
                    },
                }
            ),
            encoding="utf-8",
        )
        return ProcessResult(0, "rendered", "", False, False, 0.1)

    contact_sheet = experiment_shader_variants(config, "shader_asset_001", runner=fake_runner)

    updated = ManifestRepository(config.foundry.workspace_root).load("shader_asset_001")
    assert contact_sheet.role == "shader_experiment_contact_sheet"
    assert updated.workflow.state is WorkflowState.REVIEW
    assert source.read_bytes() == b"immutable glb"
    assert sum(item.role == "shader_variant_preview" for item in updated.artifacts) == 4
    report_artifact = next(
        item for item in updated.artifacts if item.role == "shader_experiment_report"
    )
    report = json.loads((asset_root / str(report_artifact.path)).read_text(encoding="utf-8"))
    assert report["source_sha256"] == digest
    assert report["measured_material_facts"]["unique_material_count"] == 1
    assert "single material atlas" in report["interpretation"]


def test_shader_experiment_removes_partial_outputs_after_failure(
    config, lanes, prompt: Path, tmp_path: Path
) -> None:
    initialize_workspace(config.foundry.workspace_root)
    manifest = create_asset(
        config,
        lanes,
        "shader_failure_001",
        "static_prop",
        "Shader Failure",
        prompt,
    )
    asset_root = config.foundry.workspace_root / "assets/shader_failure_001"
    source = asset_root / "processed/model.glb"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"glb")
    manifest.artifacts.append(
        Artifact(
            artifact_id="processed_glb_001",
            role="processed_model",
            stage="processed",
            format="glb",
            path="processed/model.glb",
            sha256=hashlib.sha256(b"glb").hexdigest(),
            size_bytes=3,
        )
    )
    manifest.workflow.state = WorkflowState.PROCESSED
    manifest.revision += 1
    ManifestRepository(config.foundry.workspace_root).save(
        manifest, "test.processed", expected_revision=1
    )
    executable = tmp_path / "blender.exe"
    executable.write_bytes(b"fixture")
    config.tools.blender_executable = executable

    def failed_runner(arguments, cwd, environment, timeout_seconds, maximum_output_bytes):
        return ProcessResult(1, "", "failed", False, False, 0.1)

    with pytest.raises(FoundryError, match="shader experiment failed"):
        experiment_shader_variants(config, "shader_failure_001", runner=failed_runner)
    assert not (asset_root / "preview/shader-experiment-001").exists()
    assert not (asset_root / "reports/shader-experiment-001.json").exists()
