import subprocess
from pathlib import Path

import pytest

from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.services.init_library import initialize_asset_library

EXPECTED_GIT_ATTRIBUTES = """\
*.glb filter=lfs diff=lfs merge=lfs -text
*.fbx filter=lfs diff=lfs merge=lfs -text
*.bin filter=lfs diff=lfs merge=lfs -text
*.png filter=lfs diff=lfs merge=lfs -text
*.jpg filter=lfs diff=lfs merge=lfs -text
*.jpeg filter=lfs diff=lfs merge=lfs -text
*.webp filter=lfs diff=lfs merge=lfs -text

catalog.json text eol=lf
assets/**/asset-release.json text eol=lf
assets/**/godot/*.tscn text eol=lf
assets/**/custody/evidence/*.json text eol=lf
"""


class FakeGit:
    def __init__(self, fail_on: tuple[str, ...] | None = None) -> None:
        self.commands: list[list[str]] = []
        self.fail_on = fail_on

    def __call__(
        self,
        command: list[str],
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        if self.fail_on and tuple(command[: len(self.fail_on)]) == self.fail_on:
            return subprocess.CompletedProcess(command, 1, "", "simulated failure")
        if command[:2] == ["status", "--porcelain=v1"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 0, "", "")


def test_initialize_library_creates_committed_baseline(config) -> None:
    git = FakeGit()

    result = initialize_asset_library(config, git_runner=git)

    root = result.destination
    assert root.is_dir()
    assert (root / "catalog.json").read_text().endswith("\n")
    assert (root / ".gitattributes").read_bytes() == EXPECTED_GIT_ATTRIBUTES.encode()
    assert ".foundry-staging/" in (root / ".gitignore").read_text()
    assert git.commands[0] == ["init", "--initial-branch=main"]
    assert git.commands[1] == ["lfs", "install", "--local"]
    assert any("commit" in command for command in git.commands)


def test_initialize_library_refuses_existing_destination(config) -> None:
    root = config.foundry.asset_library_root
    root.mkdir()
    marker = root / "owned.txt"
    marker.write_text("preserve")
    git = FakeGit()

    with pytest.raises(FoundryError, match="already exists"):
        initialize_asset_library(config, git_runner=git)

    assert marker.read_text() == "preserve"
    assert git.commands == []


def test_initialize_library_cleans_only_its_staging_on_git_failure(config) -> None:
    git = FakeGit(fail_on=("lfs", "install"))

    with pytest.raises(FoundryError, match="initialize Git LFS"):
        initialize_asset_library(config, git_runner=git)

    assert not config.foundry.asset_library_root.exists()
    assert not list(config.foundry.asset_library_root.parent.glob(".library-init-*"))
