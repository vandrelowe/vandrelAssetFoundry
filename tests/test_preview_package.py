import json
import stat
import zipfile
from pathlib import Path

import pytest

from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.services.preview_package import (
    _safe_zip_path,
    prepare_package_preview,
    validate_package_preview,
)
from vandrel_foundry.services.validate_godot import ProcessResult


def _write_zip(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, value in entries.items():
            archive.writestr(name, value)


def test_prepares_candidate_free_preview_without_recording_source_path(
    config, tmp_path: Path
) -> None:
    package = tmp_path / "bear package.zip"
    _write_zip(
        package,
        {
            "animations/walk.glb": b"walk",
            "animations/idle.fbx": b"idle",
            "animations/bear.png": b"texture",
            "notes.txt": b"not extracted",
        },
    )

    result = prepare_package_preview(config, package)

    assert result.sandbox.parent == config.foundry.workspace_root / "temp" / "package_previews"
    assert result.models == ("package/animations/walk.glb", "package/animations/idle.fbx")
    assert (result.sandbox / "package/animations/bear.png").read_bytes() == b"texture"
    assert not (result.sandbox / "package/notes.txt").exists()
    report_text = result.report.read_text(encoding="utf-8")
    report = json.loads(report_text)
    assert report["authority"] == "local_visual_preview_only"
    assert report["viewer_version"] == 4
    assert report["safety"]["skipped_entries"] == ["notes.txt"]
    assert str(package.parent) not in report_text


def test_existing_deterministic_preview_is_not_overwritten(config, tmp_path: Path) -> None:
    package = tmp_path / "bear.zip"
    _write_zip(package, {"bear.glb": b"first"})
    first = prepare_package_preview(config, package)

    with pytest.raises(FoundryError, match="already exists"):
        prepare_package_preview(config, package)

    assert (first.sandbox / "package/bear.glb").read_bytes() == b"first"


@pytest.mark.parametrize("unsafe", ["../bear.glb", "/bear.glb", "C:/bear.glb"])
def test_rejects_unsafe_archive_paths(config, tmp_path: Path, unsafe: str) -> None:
    package = tmp_path / "unsafe.zip"
    _write_zip(package, {unsafe: b"model"})

    with pytest.raises(FoundryError, match="unsafe path"):
        prepare_package_preview(config, package)


def test_rejects_backslash_archive_path() -> None:
    with pytest.raises(FoundryError, match="unsafe path"):
        _safe_zip_path("a\\bear.glb")


def test_rejects_case_collisions(config, tmp_path: Path) -> None:
    package = tmp_path / "collision.zip"
    _write_zip(package, {"Bear.glb": b"one", "bear.glb": b"two"})

    with pytest.raises(FoundryError, match="case-colliding"):
        prepare_package_preview(config, package)


def test_rejects_symbolic_links(config, tmp_path: Path) -> None:
    package = tmp_path / "link.zip"
    with zipfile.ZipFile(package, "w") as archive:
        link = zipfile.ZipInfo("bear.glb")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, "target")

    with pytest.raises(FoundryError, match="symbolic link"):
        prepare_package_preview(config, package)


def test_requires_a_supported_model(config, tmp_path: Path) -> None:
    package = tmp_path / "textures.zip"
    _write_zip(package, {"bear.png": b"texture"})

    with pytest.raises(FoundryError, match="supported 3D model"):
        prepare_package_preview(config, package)


def test_validation_requires_loaded_mesh_readiness(config, tmp_path: Path) -> None:
    executable = tmp_path / "godot.exe"
    executable.write_bytes(b"fake")
    configured = config.model_copy(
        update={"tools": config.tools.model_copy(update={"godot_executable": executable})}
    )
    sandbox = tmp_path / "preview"
    sandbox.mkdir()

    def failed_runner(*_args, **_kwargs) -> ProcessResult:
        return ProcessResult(0, "Godot started", "", False, False, 0.1)

    with pytest.raises(FoundryError, match="render readiness"):
        validate_package_preview(configured, sandbox, failed_runner)


def test_validation_accepts_ready_scene_with_meshes(config, tmp_path: Path) -> None:
    executable = tmp_path / "godot.exe"
    executable.write_bytes(b"fake")
    configured = config.model_copy(
        update={"tools": config.tools.model_copy(update={"godot_executable": executable})}
    )
    sandbox = tmp_path / "preview"
    sandbox.mkdir()

    def ready_runner(*_args, **_kwargs) -> ProcessResult:
        return ProcessResult(
            0,
            "FOUNDRY_PREVIEW_READY models=4 selected=package/bear.glb meshes=1 animations=1",
            "",
            False,
            False,
            0.1,
        )

    result = validate_package_preview(configured, sandbox, ready_runner)

    assert result.return_code == 0
