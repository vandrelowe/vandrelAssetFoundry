import subprocess


def _is_ignored(path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", "--no-index", "--", path],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def test_only_root_output_directory_is_ignored() -> None:
    assert _is_ignored("output/generated.png")
    assert not _is_ignored("src/vandrel_foundry/output/generated.py")
    assert not _is_ignored("tests/output/generated.txt")
    assert not _is_ignored("docs/reports/output/generated.json")
