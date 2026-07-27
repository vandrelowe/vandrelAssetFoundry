import tomllib
from pathlib import Path

import vandrel_foundry


def test_runtime_and_project_versions_match() -> None:
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    with pyproject.open("rb") as stream:
        project = tomllib.load(stream)["project"]
    assert vandrel_foundry.__version__ == project["version"]
