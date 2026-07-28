import subprocess
from pathlib import Path

from vandrel_foundry.storage.git_worktree import run_git


def test_run_git_scopes_safe_directory_to_exact_worktree(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: list[object] = []

    def fake_run(command, **kwargs):
        captured.extend([command, kwargs])
        return subprocess.CompletedProcess(command, 0, "true\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = run_git(["rev-parse", "--is-inside-work-tree"], tmp_path)

    assert result.returncode == 0
    assert captured[0] == [
        "git",
        "-c",
        f"safe.directory={tmp_path.resolve().as_posix()}",
        "rev-parse",
        "--is-inside-work-tree",
    ]
    assert captured[1]["cwd"] == tmp_path
