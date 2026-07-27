import tomllib
from pathlib import Path

import vandrel_foundry


def test_runtime_and_project_versions_match() -> None:
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    with pyproject.open("rb") as stream:
        project = tomllib.load(stream)["project"]
    assert vandrel_foundry.__version__ == project["version"]


def test_required_runtime_data_is_packaged_with_the_module() -> None:
    package_root = Path(vandrel_foundry.__file__).parent
    assert (package_root / "data/lanes.toml").is_file()
    assert (package_root / "blender/process_glb.py").is_file()
