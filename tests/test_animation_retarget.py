import json
from pathlib import Path

from PIL import Image

from tests.test_humanoid_retarget import (
    _add_processed_asset,
    _meshy_document,
)
from vandrel_foundry.domain.manifest import Processor
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.inspect_assets import initialize_workspace
from vandrel_foundry.services.render_animation_samples import render_animation_samples
from vandrel_foundry.services.retarget_animations import retarget_animations
from vandrel_foundry.services.review_animation_samples import accept_animation_samples
from vandrel_foundry.services.review_asset import REQUIRED_CHECKS, approval_checks_pass
from vandrel_foundry.services.validate_godot import ProcessResult
from vandrel_foundry.storage.manifests import ManifestRepository


def test_retargets_and_records_hash_bound_blender_output(
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
        "target_character_001",
        _meshy_document(),
    )
    _add_processed_asset(
        config,
        humanoid_lanes,
        prompt,
        "animation_donor_001",
        _meshy_document(animations=3),
    )
    executable = tmp_path / "blender.exe"
    executable.write_bytes(b"fixture")
    config.tools.blender_executable = executable

    def fake_runner(arguments, cwd, environment, timeout_seconds, maximum_output_bytes):
        assert "--disable-autoexec" in arguments
        assert "MESHY_API_KEY" not in environment
        target_path, donor_path, output_path, report_path = map(Path, arguments[-4:])
        assert target_path.is_file()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(donor_path.read_bytes())
        report_path.write_text(
            json.dumps(
                {
                    "blender_version": "fixture",
                    "output_animation_count": 3,
                    "animations": [
                        {"name": "clip_1"},
                        {"name": "clip_2"},
                        {"name": "clip_3"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        return ProcessResult(0, "retargeted", "", False, False, 0.1)

    result = retarget_animations(
        config,
        "target_character_001",
        "animation_donor_001",
        runner=fake_runner,
    )

    saved = ManifestRepository(config.foundry.workspace_root).load(
        "target_character_001"
    )
    assert result.animation_count == 3
    assert result.animation_names == ("clip_1", "clip_2", "clip_3")
    assert result.model.derived_from == ["processed_glb_001"]
    assert result.report.role == "animation_retarget_report"
    assert result.log.role == "animation_retarget_log"
    assert saved.workflow.state is WorkflowState.PROCESSED
    assert saved.validation.result == "not_run"
    assert saved.quality.observed["animation_count"] == 3


def test_animation_samples_record_images_contact_sheet_and_evidence(
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
        "sample_character_001",
        _meshy_document(animations=2),
    )
    executable = tmp_path / "blender.exe"
    executable.write_bytes(b"fixture")
    config.tools.blender_executable = executable

    def fake_runner(arguments, cwd, environment, timeout_seconds, maximum_output_bytes):
        output_directory = Path(arguments[-2])
        report_path = Path(arguments[-1])
        output_directory.mkdir()
        samples = []
        for index in range(2):
            name = f"sample-{index + 1}.png"
            Image.new("RGBA", (384, 384), (100 + index, 80, 60, 255)).save(
                output_directory / name
            )
            samples.append(
                {
                    "animation": f"clip_{index + 1}",
                    "frame": index + 1,
                    "image": name,
                }
            )
        report_path.write_text(
            json.dumps(
                {
                    "blender_version": "fixture",
                    "sample_count": 2,
                    "samples": samples,
                }
            ),
            encoding="utf-8",
        )
        return ProcessResult(0, "rendered", "", False, False, 0.1)

    result = render_animation_samples(
        config,
        "sample_character_001",
        runner=fake_runner,
    )

    saved = ManifestRepository(config.foundry.workspace_root).load(
        "sample_character_001"
    )
    assert result.role == "animation_sample_contact_sheet"
    assert sum(item.role == "animation_sample_preview" for item in saved.artifacts) == 2
    assert any(item.role == "animation_sample_report" for item in saved.artifacts)
    assert saved.workflow.state is WorkflowState.REVIEW
    saved.artifacts[0].processor = Processor(
        name="blender_rest_pose_retarget",
        version="fixture",
    )
    saved.validation.result = "passed"
    saved.validation.checks = [
        {"name": name, "passed": True} for name in sorted(REQUIRED_CHECKS)
    ]
    saved.revision += 1
    ManifestRepository(config.foundry.workspace_root).save(
        saved,
        expected_revision=saved.revision - 1,
    )
    assert not approval_checks_pass(saved)

    review = accept_animation_samples(
        config,
        "sample_character_001",
        reviewer="Test Reviewer",
        notes="Reviewed all representative fixture poses.",
    )

    accepted = ManifestRepository(config.foundry.workspace_root).load(
        "sample_character_001"
    )
    assert review.role == "animation_visual_review"
    assert not approval_checks_pass(accepted)
