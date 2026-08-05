import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.services.validate_godot import ProcessResult, run_bounded_process

PREVIEW_SCHEMA_VERSION = 1
VIEWER_VERSION = 4
MAX_ENTRIES = 512
MAX_ENTRY_BYTES = 1_000_000_000
MAX_TOTAL_BYTES = 2_000_000_000
MAX_COMPRESSION_RATIO = 500
MODEL_SUFFIXES = {".fbx", ".glb", ".gltf", ".obj"}
SIDECAR_SUFFIXES = {".bin", ".jpeg", ".jpg", ".png", ".tga", ".webp"}
PROJECT_TEXT = """; Generated local package preview. Not a Vandrel runtime project.
config_version=5

[application]
config/name="Vandrel Foundry Package Preview"
run/main_scene="res://Main.tscn"

[display]
window/size/viewport_width=1280
window/size/viewport_height=800

[rendering]
renderer/rendering_method="gl_compatibility"
renderer/rendering_method.mobile="gl_compatibility"
"""
SCENE_TEXT = """[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://package_preview.gd" id="1"]

[node name="PackagePreview" type="Node3D"]
script = ExtResource("1")
"""


@dataclass(frozen=True)
class PackagePreviewResult:
    sandbox: Path
    report: Path
    models: tuple[str, ...]


@dataclass(frozen=True)
class ValidatedPackagePreview:
    sandbox: Path
    process: ProcessResult


class PreviewProcessRunner(Protocol):
    def __call__(
        self,
        arguments: list[str],
        cwd: Path,
        environment: dict[str, str],
        timeout_seconds: float,
        maximum_output_bytes: int,
    ) -> ProcessResult: ...


def prepare_package_preview(
    config: FoundryConfig,
    archive: Path,
    output_root: Path | None = None,
) -> PackagePreviewResult:
    archive = archive.resolve(strict=True)
    if not archive.is_file() or archive.suffix.lower() != ".zip":
        raise FoundryError("Package preview currently requires a ZIP archive.")
    archive_sha256, archive_size = _hash_file(archive)
    root = (output_root or config.foundry.workspace_root / "temp" / "package_previews").resolve()
    root.mkdir(parents=True, exist_ok=True)
    sandbox = root / f"{_safe_stem(archive.stem)}-{archive_sha256[:12]}-v{VIEWER_VERSION}"
    if sandbox.exists():
        raise FoundryError(f"Package preview sandbox already exists: {sandbox}")

    try:
        with zipfile.ZipFile(archive) as package:
            entries, models, skipped, total_bytes = _inspect_entries(package)
            temporary = Path(tempfile.mkdtemp(prefix=f".{sandbox.name}-", dir=root))
            try:
                package_root = temporary / "package"
                for info, relative in entries:
                    destination = package_root.joinpath(*relative.parts)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with package.open(info) as source, destination.open("xb") as target:
                        shutil.copyfileobj(source, target, length=1024 * 1024)
                viewer_source = Path(__file__).resolve().parents[1] / "godot" / "package_preview.gd"
                _write_new(temporary / "project.godot", PROJECT_TEXT)
                _write_new(temporary / "Main.tscn", SCENE_TEXT)
                _copy_new(viewer_source, temporary / "package_preview.gd")
                catalog = {"schema_version": 1, "models": models}
                _write_json(temporary / "preview_catalog.json", catalog)
                report = {
                    "schema_version": PREVIEW_SCHEMA_VERSION,
                    "viewer_version": VIEWER_VERSION,
                    "archive": {
                        "name": archive.name,
                        "sha256": archive_sha256,
                        "size_bytes": archive_size,
                    },
                    "safety": {
                        "entry_count": len(package.infolist()),
                        "extracted_file_count": len(entries),
                        "uncompressed_bytes": total_bytes,
                        "skipped_entries": skipped,
                    },
                    "models": models,
                    "authority": "local_visual_preview_only",
                }
                _write_json(temporary / "preview-report.json", report)
                try:
                    os.rename(temporary, sandbox)
                except FileExistsError as exc:
                    raise FoundryError(
                        f"Package preview sandbox already exists: {sandbox}"
                    ) from exc
            except BaseException:
                shutil.rmtree(temporary, ignore_errors=True)
                raise
    except (OSError, zipfile.BadZipFile) as exc:
        raise FoundryError(f"Could not prepare package preview: {exc}") from exc
    return PackagePreviewResult(sandbox, sandbox / "preview-report.json", tuple(models))


def validate_package_preview(
    config: FoundryConfig,
    sandbox: Path,
    runner: PreviewProcessRunner | None = None,
) -> ValidatedPackagePreview:
    executable = config.tools.godot_executable
    if executable is None:
        raise FoundryError("tools.godot_executable is not configured.")
    executable = executable.resolve(strict=True)
    sandbox = sandbox.resolve(strict=True)
    console_executable = executable.with_name(f"{executable.stem}_console{executable.suffix}")
    if console_executable.is_file():
        executable = console_executable
    process_runner = runner or run_bounded_process
    import_result = process_runner(
        [str(executable), "--headless", "--path", str(sandbox), "--import"],
        sandbox,
        _safe_environment(),
        config.tools.godot_timeout_seconds,
        config.tools.maximum_output_bytes,
    )
    _require_clean_process(import_result, "Godot package import failed.")
    result = process_runner(
        [str(executable), "--headless", "--path", str(sandbox), "--quit-after", "3"],
        sandbox,
        _safe_environment(),
        config.tools.godot_timeout_seconds,
        config.tools.maximum_output_bytes,
    )
    output = f"{result.stdout}\n{result.stderr}"
    ready = re.search(r"FOUNDRY_PREVIEW_READY .* meshes=([1-9][0-9]*) ", output)
    _require_clean_process(result, "Godot package preview runtime failed.")
    if ready is None:
        raise FoundryError("Godot package preview did not reach verified render readiness.")
    return ValidatedPackagePreview(sandbox=sandbox, process=result)


def launch_package_preview(config: FoundryConfig, preview: ValidatedPackagePreview) -> None:
    executable = config.tools.godot_executable
    if executable is None:
        raise FoundryError("tools.godot_executable is not configured.")
    executable = executable.resolve(strict=True)
    sandbox = preview.sandbox.resolve(strict=True)
    try:
        subprocess.Popen(
            [str(executable), "--path", str(sandbox)],
            cwd=sandbox,
            env=_safe_environment(),
            shell=False,
        )
    except OSError as exc:
        raise FoundryError(f"Could not launch package preview: {exc}") from exc


def _inspect_entries(
    package: zipfile.ZipFile,
) -> tuple[list[tuple[zipfile.ZipInfo, PurePosixPath]], list[str], list[str], int]:
    infos = package.infolist()
    if len(infos) > MAX_ENTRIES:
        raise FoundryError(f"ZIP contains too many entries (maximum {MAX_ENTRIES}).")
    accepted: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
    models: list[str] = []
    skipped: list[str] = []
    seen: set[str] = set()
    total = 0
    for info in infos:
        relative = _safe_zip_path(info.filename)
        collision_key = relative.as_posix().casefold()
        if collision_key in seen:
            raise FoundryError(f"ZIP contains duplicate or case-colliding path: {info.filename}")
        seen.add(collision_key)
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise FoundryError(f"ZIP contains a symbolic link: {info.filename}")
        if info.is_dir():
            continue
        if info.file_size > MAX_ENTRY_BYTES:
            raise FoundryError(f"ZIP entry exceeds the size limit: {info.filename}")
        if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
            raise FoundryError(f"ZIP entry exceeds the compression-ratio limit: {info.filename}")
        total += info.file_size
        if total > MAX_TOTAL_BYTES:
            raise FoundryError("ZIP exceeds the total uncompressed size limit.")
        suffix = relative.suffix.lower()
        if suffix not in MODEL_SUFFIXES | SIDECAR_SUFFIXES:
            skipped.append(relative.as_posix())
            continue
        accepted.append((info, relative))
        if suffix in MODEL_SUFFIXES:
            models.append(f"package/{relative.as_posix()}")
    if not models:
        raise FoundryError("ZIP does not contain a supported 3D model.")
    models.sort(
        key=lambda item: (
            _model_priority(PurePosixPath(item).suffix),
            _motion_priority(item),
            item.casefold(),
        )
    )
    return accepted, models, skipped, total


def _safe_zip_path(value: str) -> PurePosixPath:
    if not value or "\\" in value or value.startswith(("/", "\\")):
        raise FoundryError(f"ZIP contains an unsafe path: {value!r}")
    path = PurePosixPath(value)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise FoundryError(f"ZIP contains an unsafe path: {value!r}")
    if path.parts and (":" in path.parts[0] or path.parts[0].startswith("~")):
        raise FoundryError(f"ZIP contains an unsafe path: {value!r}")
    return path


def _safe_stem(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip(".-")
    return (safe or "package")[:80]


def _model_priority(suffix: str) -> int:
    return {".glb": 0, ".gltf": 1, ".fbx": 2, ".obj": 3}.get(suffix.lower(), 9)


def _motion_priority(path: str) -> int:
    normalized = f"/{path.casefold()}/"
    for priority, marker in enumerate(("/walk/", "/idle/", "/run/", "/final_rig/")):
        if marker in normalized:
            return priority
    return 9


def _require_clean_process(result: ProcessResult, message: str) -> None:
    output = f"{result.stdout}\n{result.stderr}"
    if (
        result.return_code != 0
        or result.timed_out
        or result.output_limited
        or "SCRIPT ERROR:" in output
        or "Parse Error:" in output
    ):
        raise FoundryError(message)


def _write_json(path: Path, value: object) -> None:
    _write_new(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def _write_new(path: Path, value: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(value)


def _copy_new(source: Path, destination: Path) -> None:
    with source.open("rb") as input_stream, destination.open("xb") as output_stream:
        shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _safe_environment() -> dict[str, str]:
    allowed = ("APPDATA", "LOCALAPPDATA", "PATH", "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE")
    return {name: os.environ[name] for name in allowed if name in os.environ}
