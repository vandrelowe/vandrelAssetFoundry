import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.inspect_glb import inspect_glb
from vandrel_foundry.services.validate_godot import ProcessRunner, run_bounded_process
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path

MAX_EXTERNAL_GLB_BYTES = 4_000_000_000
IMPORTER_VERSION = "1"
SUPPORTED_SIDECAR_SUFFIXES = {".bin", ".png", ".jpg", ".jpeg"}
SUPPORTED_PACKAGE_MODEL_SUFFIXES = {".fbx", ".gltf"}


def add_external_glb(
    config: FoundryConfig,
    asset_id: str,
    source: Path,
) -> Artifact:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.workflow.state is not WorkflowState.DRAFT:
        raise FoundryError(f"External sources may only be added in draft state: {asset_id}")
    if not source.is_file() or source.suffix.lower() != ".glb":
        raise FoundryError("External source must be an existing .glb file.")
    size = source.stat().st_size
    if size <= 0 or size > MAX_EXTERNAL_GLB_BYTES:
        raise FoundryError(f"External GLB size must be 1-{MAX_EXTERNAL_GLB_BYTES} bytes: {size}")
    inspect_glb(source)

    number = sum(item.role == "source_model" for item in manifest.artifacts) + 1
    artifact_id = f"source_glb_{number:03d}"
    relative = RelativeManifestPath(f"source/external/{artifact_id}.glb")
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    destination = contained_path(asset_root, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_value = tempfile.mkstemp(
        prefix=f".{artifact_id}-",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_value)
    try:
        digest = hashlib.sha256()
        copied_size = 0
        with os.fdopen(descriptor, "wb") as output_stream, source.open("rb") as input_stream:
            while chunk := input_stream.read(1024 * 1024):
                output_stream.write(chunk)
                digest.update(chunk)
                copied_size += len(chunk)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError as exc:
            raise FoundryError(f"External source destination exists: {relative}") from exc
    except OSError as exc:
        raise FoundryError(f"Could not copy external GLB: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)
    if copied_size != size:
        destination.unlink(missing_ok=True)
        raise FoundryError("External GLB changed while it was being copied.")
    copied_digest, verified_size = _hash_file(destination)
    if copied_digest != digest.hexdigest() or verified_size != copied_size:
        destination.unlink(missing_ok=True)
        raise FoundryError("Copied external GLB failed verification.")

    artifact = Artifact(
        artifact_id=artifact_id,
        role="source_model",
        stage="source",
        format="glb",
        path=relative,
        sha256=copied_digest,
        size_bytes=verified_size,
        derived_from=[],
        processor=Processor(name="external_glb_import", version=IMPORTER_VERSION),
    )
    manifest.artifacts.append(artifact)
    manifest.input.kind = "external"
    manifest.workflow.state = WorkflowState.DOWNLOADED
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    repository.save(
        manifest,
        "source.external_added",
        expected_revision=manifest.revision - 1,
    )
    return artifact


def add_external_fbx(
    config: FoundryConfig,
    asset_id: str,
    source: Path,
    runner: ProcessRunner | None = None,
) -> Artifact:
    return add_external_package(config, asset_id, source, runner)


def add_external_package(
    config: FoundryConfig,
    asset_id: str,
    source: Path,
    runner: ProcessRunner | None = None,
) -> Artifact:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.workflow.state is not WorkflowState.DRAFT:
        raise FoundryError(f"External sources may only be added in draft state: {asset_id}")
    source_suffix = source.suffix.lower()
    if not source.is_file() or source_suffix not in SUPPORTED_PACKAGE_MODEL_SUFFIXES:
        raise FoundryError("External package source must be an existing FBX or glTF file.")
    executable = config.tools.blender_executable
    if executable is None or not executable.is_absolute() or not executable.is_file():
        raise FoundryError("Configure tools.blender_executable as an existing absolute file.")
    sidecars = (
        _gltf_sidecars(source)
        if source_suffix == ".gltf"
        else [
            item
            for item in source.parent.iterdir()
            if item.is_file() and item.suffix.lower() in SUPPORTED_SIDECAR_SUFFIXES
        ]
    )
    package_files = [source] + sorted(sidecars, key=lambda item: item.name.casefold())
    if len({item.name.casefold() for item in package_files}) != len(package_files):
        raise FoundryError("External package contains case-insensitive filename collisions.")
    total_size = sum(item.stat().st_size for item in package_files)
    if total_size <= 0 or total_size > MAX_EXTERNAL_GLB_BYTES:
        raise FoundryError(
            f"External package size must be 1-{MAX_EXTERNAL_GLB_BYTES} bytes: {total_size}"
        )

    asset_root = config.foundry.workspace_root / "assets" / asset_id
    packages_root = asset_root / "source" / "packages"
    packages_root.mkdir(parents=True, exist_ok=True)
    package_number = sum(item.role == "external_source_model" for item in manifest.artifacts) + 1
    package_name = f"package_{package_number:03d}"
    final_directory = packages_root / package_name
    if final_directory.exists():
        raise FoundryError(f"External package destination exists: {package_name}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{package_name}-", dir=packages_root))
    try:
        copied_paths: list[Path] = []
        for item in package_files:
            destination = temporary / item.name
            _copy_new(item, destination)
            copied_paths.append(destination)
        copied_source = temporary / source.name
        converted = temporary / "converted.glb"
        report = temporary / "blender-conversion.json"
        script = Path(__file__).parents[1] / "blender" / "process_glb.py"
        arguments = [
            str(executable),
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "--python-exit-code",
            "1",
            "--python",
            str(script),
            "--",
            str(copied_source),
            str(converted),
            str(report),
        ]
        result = (runner or run_bounded_process)(
            arguments,
            temporary,
            _safe_tool_environment(),
            config.tools.blender_timeout_seconds,
            config.tools.maximum_output_bytes,
        )
        if result.return_code != 0 or result.timed_out or result.output_limited:
            raise FoundryError("Bounded external-package conversion failed.")
        if not converted.is_file() or not report.is_file():
            raise FoundryError("Blender did not create converted GLB and report files.")
        inspect_glb(converted)
        report_data = json.loads(report.read_text(encoding="utf-8"))
        expected_format = source_suffix.removeprefix(".")
        if report_data.get("input_format") != expected_format:
            raise FoundryError("Blender conversion report has an unexpected input format.")
        warnings = _extract_warnings(result.stdout, result.stderr)
        report_data["warnings"] = warnings
        _rewrite_json(report, report_data)
        log = temporary / "blender-conversion.log"
        _write_new_bytes(
            log,
            f"STDOUT\n{result.stdout}\n\nSTDERR\n{result.stderr}\n".encode(
                "utf-8", errors="replace"
            ),
        )
        os.rename(temporary, final_directory)
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise

    processor = Processor(
        name=f"external_{source_suffix.removeprefix('.')}_import",
        version=f"{IMPORTER_VERSION}+blender-{report_data['blender_version']}",
    )
    package_prefix = f"source/packages/{package_name}"
    raw_artifacts: list[Artifact] = []
    for index, copied in enumerate(copied_paths, start=1):
        final_path = final_directory / copied.name
        digest, size = _hash_file(final_path)
        relative = RelativeManifestPath(f"{package_prefix}/{copied.name}")
        is_source = copied.name == source.name
        is_buffer = copied.suffix.lower() == ".bin"
        sidecar_role = "source_buffer" if is_buffer else "source_texture"
        sidecar_prefix = "source_buffer" if is_buffer else "source_texture"
        raw_artifacts.append(
            Artifact(
                artifact_id=(
                    f"external_source_{source_suffix.removeprefix('.')}_{package_number:03d}"
                    if is_source
                    else f"{sidecar_prefix}_{package_number:03d}_{index:03d}"
                ),
                role="external_source_model" if is_source else sidecar_role,
                stage="source",
                format=copied.suffix.lower().removeprefix("."),
                path=relative,
                sha256=digest,
                size_bytes=size,
                derived_from=[],
                processor=processor,
            )
        )
    converted_path = final_directory / "converted.glb"
    converted_digest, converted_size = _hash_file(converted_path)
    source_artifact = Artifact(
        artifact_id=f"source_glb_{package_number:03d}",
        role="source_model",
        stage="source",
        format="glb",
        path=RelativeManifestPath(f"{package_prefix}/converted.glb"),
        sha256=converted_digest,
        size_bytes=converted_size,
        derived_from=[item.artifact_id for item in raw_artifacts],
        processor=processor,
    )
    evidence_artifacts = []
    for role, filename, artifact_prefix in (
        ("blender_conversion_report", "blender-conversion.json", "fbx_conversion_report"),
        ("blender_conversion_log", "blender-conversion.log", "fbx_conversion_log"),
    ):
        evidence_path = final_directory / filename
        digest, size = _hash_file(evidence_path)
        evidence_artifacts.append(
            Artifact(
                artifact_id=f"{artifact_prefix}_{package_number:03d}",
                role=role,
                stage="source",
                format=evidence_path.suffix.removeprefix("."),
                path=RelativeManifestPath(f"{package_prefix}/{filename}"),
                sha256=digest,
                size_bytes=size,
                derived_from=[source_artifact.artifact_id],
                processor=processor,
            )
        )
    manifest.artifacts.extend([*raw_artifacts, source_artifact, *evidence_artifacts])
    manifest.input.kind = "external"
    manifest.quality.observed["source_conversion_warnings"] = warnings
    manifest.workflow.state = WorkflowState.DOWNLOADED
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    repository.save(
        manifest,
        "source.external_package_added",
        expected_revision=manifest.revision - 1,
    )
    return source_artifact


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _copy_new(source: Path, destination: Path) -> None:
    try:
        with source.open("rb") as input_stream, destination.open("xb") as output_stream:
            while chunk := input_stream.read(1024 * 1024):
                output_stream.write(chunk)
            output_stream.flush()
            os.fsync(output_stream.fileno())
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise FoundryError(f"Could not copy external package file: {exc}") from exc


def _write_new_bytes(path: Path, value: bytes) -> None:
    try:
        with path.open("xb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        path.unlink(missing_ok=True)
        raise FoundryError(f"Could not write external conversion log: {exc}") from exc


def _safe_tool_environment() -> dict[str, str]:
    allowed = {
        "APPDATA",
        "HOME",
        "LOCALAPPDATA",
        "PATH",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    }
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


def _extract_warnings(stdout: str, stderr: str) -> list[str]:
    return [
        line.strip() for line in f"{stdout}\n{stderr}".splitlines() if "WARNING" in line.upper()
    ]


def _rewrite_json(path: Path, value: object) -> None:
    try:
        with path.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise FoundryError(f"Could not finalize external conversion report: {exc}") from exc


def _gltf_sidecars(source: Path) -> list[Path]:
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FoundryError(f"Could not read external glTF package: {exc}") from exc
    if not isinstance(document, dict):
        raise FoundryError("External glTF document must be a JSON object.")
    uris: set[str] = set()
    for collection_name in ("buffers", "images"):
        collection = document.get(collection_name, [])
        if not isinstance(collection, list):
            raise FoundryError(f"glTF {collection_name} must be an array.")
        for item in collection:
            uri = item.get("uri") if isinstance(item, dict) else None
            if isinstance(uri, str) and not uri.startswith("data:"):
                uris.add(uri)
    sidecars: list[Path] = []
    source_root = source.parent.resolve()
    for uri in sorted(uris):
        split = urlsplit(uri)
        if split.scheme or split.netloc or split.query or split.fragment:
            raise FoundryError(f"External glTF URI is not a local sidecar: {uri}")
        decoded = unquote(split.path)
        relative = Path(decoded)
        candidate = (source_root / relative).resolve()
        if (
            relative.is_absolute()
            or candidate.parent != source_root
            or candidate.suffix.lower() not in SUPPORTED_SIDECAR_SUFFIXES
            or not candidate.is_file()
        ):
            raise FoundryError(f"External glTF sidecar is missing or unsafe: {uri}")
        sidecars.append(candidate)
    return sidecars
