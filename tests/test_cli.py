from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.conftest import write_config
from vandrel_foundry import cli
from vandrel_foundry.cli import app
from vandrel_foundry.domain.errors import ConfigurationError

runner = CliRunner()


@pytest.fixture
def cli_config(tmp_path: Path, config_data: dict) -> Path:
    path = tmp_path / "foundry.toml"
    write_config(path, config_data)
    return path


def invoke(command: list[str], config: Path):
    return runner.invoke(app, [*command, "--config", str(config)])


def test_all_cli_commands_smoke(cli_config: Path, prompt: Path, config_data: dict) -> None:
    assert invoke(["init"], cli_config).exit_code == 0
    assert invoke(["lanes"], cli_config).exit_code == 0
    create = invoke(
        [
            "create",
            "--id",
            "stone_knife_001",
            "--lane",
            "static_prop",
            "--display-name",
            "Stone Knife",
            "--prompt-file",
            str(prompt),
        ],
        cli_config,
    )
    assert create.exit_code == 0, create.output
    listing = invoke(["list"], cli_config)
    assert listing.exit_code == 0 and "stone_knife_001" in listing.output
    shown = invoke(["show", "stone_knife_001"], cli_config)
    assert shown.exit_code == 0 and '"schema_version": 1' in shown.output
    status = invoke(["status", "stone_knife_001"], cli_config)
    assert status.exit_code == 0 and "submit" in status.output
    guarded_submit = invoke(["submit", "stone_knife_001"], cli_config)
    assert guarded_submit.exit_code != 0
    assert "--confirm-spend" in guarded_submit.output
    guarded_image_submit = invoke(["submit-image", "stone_knife_001"], cli_config)
    assert guarded_image_submit.exit_code != 0
    assert "--confirm-spend" in guarded_image_submit.output
    poll = invoke(["poll", "stone_knife_001"], cli_config)
    assert poll.exit_code != 0 and "Provider task not found" in poll.output
    guarded_refine = invoke(
        ["refine", "stone_knife_001", "--from", "meshy_preview_001"],
        cli_config,
    )
    assert guarded_refine.exit_code != 0
    assert "--confirm-spend" in guarded_refine.output
    guarded_remesh = invoke(["remesh", "stone_knife_001"], cli_config)
    assert guarded_remesh.exit_code != 0
    assert "--confirm-spend" in guarded_remesh.output
    guarded_approval = invoke(
        ["approve", "stone_knife_001", "--reviewer", "Reviewer"],
        cli_config,
    )
    assert guarded_approval.exit_code != 0
    assert "--all-required-checks" in guarded_approval.output
    blocked_release_apply = invoke(
        ["release", "stone_knife_001", "--apply"],
        cli_config,
    )
    assert blocked_release_apply.exit_code != 0
    assert "dry-run only" in blocked_release_apply.output
    download = invoke(["download", "stone_knife_001"], cli_config)
    assert download.exit_code != 0 and "Provider task not found" in download.output

    marker = Path(config_data["vandrel"]["reference_repo_root"]) / "project.godot"
    marker.parent.mkdir(parents=True)
    marker.write_text("", encoding="utf-8")
    doctor = invoke(["doctor"], cli_config)
    assert doctor.exit_code == 0, doctor.output


def test_doctor_rejects_write_enabled(tmp_path: Path, config_data: dict) -> None:
    config_data["vandrel"]["write_enabled"] = True
    path = tmp_path / "unsafe.toml"
    write_config(path, config_data)
    result = invoke(["doctor"], path)
    assert result.exit_code != 0
    assert "must be false" in result.output


@pytest.mark.parametrize(
    "command", [["init"], ["list"], ["show", "missing"], ["status", "missing"]]
)
def test_commands_unrelated_to_lanes_do_not_load_them(
    monkeypatch: pytest.MonkeyPatch, cli_config: Path, command: list[str]
) -> None:
    def unexpected_lane_load():
        raise ConfigurationError("lane loader should not be called")

    monkeypatch.setattr(cli, "load_lanes", unexpected_lane_load)
    result = invoke(command, cli_config)
    assert "lane loader should not be called" not in result.output
