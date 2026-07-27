import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.storage.git_worktree import GitRunner, changed_paths, run_git

GIT_ATTRIBUTES = """\
*.glb filter=lfs diff=lfs merge=lfs -text
*.fbx filter=lfs diff=lfs merge=lfs -text
*.bin filter=lfs diff=lfs merge=lfs -text
*.png filter=lfs diff=lfs merge=lfs -text
*.jpg filter=lfs diff=lfs merge=lfs -text
*.jpeg filter=lfs diff=lfs merge=lfs -text
*.webp filter=lfs diff=lfs merge=lfs -text
"""

GIT_IGNORE = """\
.foundry-staging/
"""

LIBRARY_README = """\
# Vandrel Asset Library

This repository contains immutable, reviewed asset release revisions published
by Vandrel Asset Foundry. It is not a Vandrel runtime-content repository.

Release files under `assets/<asset-id>/rNNN/` are immutable. `catalog.json` is
the discovery index. Foundry publication does not import content into Vandrel,
commit release changes, configure a remote, or push.
"""


@dataclass(frozen=True)
class LibraryInitializationResult:
    destination: Path


def initialize_asset_library(
    config: FoundryConfig,
    git_runner: GitRunner = run_git,
) -> LibraryInitializationResult:
    destination = config.foundry.asset_library_root
    if destination.exists():
        raise FoundryError(f"Asset-library destination already exists: {destination}")
    parent = destination.parent
    if not parent.is_dir():
        raise FoundryError(f"Asset-library parent does not exist: {parent}")
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}-init-", dir=parent))
    try:
        _write_baseline(staging)
        _run_required(git_runner, ["init", "--initial-branch=main"], staging, "initialize Git")
        _run_required(git_runner, ["lfs", "install", "--local"], staging, "initialize Git LFS")
        _run_required(git_runner, ["add", "--all"], staging, "stage library baseline")
        _run_required(
            git_runner,
            [
                "-c",
                "user.name=Vandrel Asset Foundry",
                "-c",
                "user.email=foundry@localhost",
                "commit",
                "-m",
                "chore: initialize asset library",
            ],
            staging,
            "commit library baseline",
        )
        if changed_paths(staging, git_runner):
            raise FoundryError("Initialized asset-library worktree is not clean.")
        os.replace(staging, destination)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return LibraryInitializationResult(destination)


def _write_baseline(root: Path) -> None:
    (root / ".gitattributes").write_text(GIT_ATTRIBUTES, encoding="utf-8", newline="\n")
    (root / ".gitignore").write_text(GIT_IGNORE, encoding="utf-8", newline="\n")
    (root / "README.md").write_text(LIBRARY_README, encoding="utf-8", newline="\n")
    (root / "catalog.json").write_text(
        json.dumps({"schema_version": 1, "assets": {}}, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _run_required(
    runner: GitRunner,
    command: list[str],
    cwd: Path,
    operation: str,
) -> None:
    result = runner(command, cwd)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown Git error"
        raise FoundryError(f"Could not {operation}: {detail}")
