import subprocess
from pathlib import Path
from typing import Protocol

from vandrel_foundry.domain.errors import FoundryError


class GitRunner(Protocol):
    def __call__(self, command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]: ...


def run_git(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *command],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FoundryError(f"Could not inspect asset-library Git worktree: {exc}") from exc


def verify_git_worktree(root: Path, runner: GitRunner = run_git) -> None:
    if not root.is_dir():
        raise FoundryError(f"Asset-library root does not exist: {root}")
    result = runner(["rev-parse", "--is-inside-work-tree"], root)
    if result.returncode != 0 or result.stdout.strip() != "true":
        raise FoundryError(f"Asset-library root is not a Git worktree: {root}")


def changed_paths(root: Path, runner: GitRunner = run_git) -> set[str]:
    result = runner(["status", "--porcelain=v1", "--untracked-files=all"], root)
    if result.returncode != 0:
        raise FoundryError("Could not inspect asset-library Git status.")
    paths: set[str] = set()
    for line in result.stdout.splitlines():
        value = line[3:]
        if " -> " in value:
            value = value.split(" -> ", 1)[1]
        paths.add(value.replace("\\", "/").strip('"'))
    return paths


def verify_lfs_path(root: Path, relative_path: str, runner: GitRunner = run_git) -> None:
    result = runner(["check-attr", "filter", "--", relative_path], root)
    if result.returncode != 0:
        raise FoundryError(f"Could not verify Git LFS policy for {relative_path}.")
    if not result.stdout.rstrip().endswith(": lfs"):
        raise FoundryError(f"Asset-library Git LFS does not govern {relative_path}.")
