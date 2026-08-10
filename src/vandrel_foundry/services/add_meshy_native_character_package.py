import hashlib
import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.domain.workflow_policy import transition_workflow
from vandrel_foundry.services.windows_acl_policy import apply_candidate_acl
from vandrel_foundry.storage.atomic import json_bytes
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path

PROCESSOR = Processor(name="local_meshy_native_character_intake", version="1")
MAX_MEMBER_BYTES = 64 * 1024 * 1024


def add_meshy_native_character_package(
    config: FoundryConfig,
    asset_id: str,
    archive_path: Path,
    expected_archive_sha256: str,
    provider_metadata: dict[str, str],
) -> list[Artifact]:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.asset.lane != "humanoid" or manifest.workflow.state is not WorkflowState.DRAFT:
        raise FoundryError("Meshy native character intake requires a draft humanoid candidate.")
    if not archive_path.is_file() or archive_path.suffix.lower() != ".zip":
        raise FoundryError("Meshy native character intake requires one ZIP archive.")
    _require_sha256(expected_archive_sha256)
    archive_hash, archive_size = _hash(archive_path)
    if archive_hash != expected_archive_sha256.casefold():
        raise FoundryError("Meshy native character ZIP hash does not match the authorized source.")
    _require_metadata(provider_metadata)
    asset_root = repository.asset_directory(asset_id)
    destination = asset_root / "source" / "meshy_native_character_package_001"
    if destination.exists():
        raise FoundryError("Meshy native character source destination already exists.")
    temporary = Path(tempfile.mkdtemp(prefix=".meshy-native-character-", dir=asset_root / "source"))
    try:
        apply_candidate_acl(config, temporary)
        copied_archive = temporary / "source.zip"
        _copy_new(archive_path, copied_archive)
        if _hash(copied_archive) != (archive_hash, archive_size):
            raise FoundryError("Meshy native character ZIP changed while it was copied.")
        members = _members(copied_archive)
        for key, info in members.items():
            suffix = ".png" if key == "texture" else ".fbx"
            filename = f"{key}{suffix}"
            with zipfile.ZipFile(copied_archive) as archive, archive.open(info, "r") as source:
                target = temporary / filename
                with target.open("xb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                    output.flush()
                    os.fsync(output.fileno())
            if target.stat().st_size != info.file_size:
                raise FoundryError(f"Extracted Meshy native character member is truncated: {key}")
        report = {
            "schema": "vandrel_foundry_meshy_native_character_intake/1.0",
            "authority_basis": "user_authorized_local_provider_native_download",
            "provider_metadata_observation": "user_observed_provider_metadata",
            "provider_metadata": provider_metadata,
            "excluded_provider_task_ids": [provider_metadata["excluded_duplicate_rig_task_id"]]
            if provider_metadata["excluded_duplicate_rig_task_id"]
            else [],
            "archive_sha256": archive_hash,
            "archive_size_bytes": archive_size,
            "members": {
                key: {
                    "archive_member": info.filename,
                    "crc32": f"{info.CRC:08x}",
                    "size_bytes": info.file_size,
                    "sha256": _hash(temporary / f"{key}{'.png' if key == 'texture' else '.fbx'}")[0],
                }
                for key, info in members.items()
            },
            "provider_lookup": "not_performed_by_intake_service",
            "license_metadata": "not_inspected",
            "provider_download": "not_performed_by_intake_service",
        }
        _write_new(temporary / "intake-report.json", json_bytes(report))
        os.rename(temporary, destination)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    records = [
        ("meshy_native_character_archive_root_001", "meshy_native_character_archive", "zip", "source.zip"),
        ("meshy_native_character_fbx_root_001", "meshy_native_character_fbx", "fbx", "character.fbx"),
        ("meshy_native_walking_fbx_root_001", "meshy_native_walking_fbx", "fbx", "walking.fbx"),
        ("meshy_native_character_texture_root_001", "meshy_native_character_texture", "png", "texture.png"),
    ]
    roots = []
    for artifact_id, role, fmt, filename in records:
        digest, size = _hash(destination / filename)
        roots.append(
            Artifact(
                artifact_id=artifact_id,
                role=role,
                stage="source",
                format=fmt,
                path=RelativeManifestPath(f"source/meshy_native_character_package_001/{filename}"),
                sha256=digest,
                size_bytes=size,
                derived_from=[],
                processor=PROCESSOR,
            )
        )
    report_digest, report_size = _hash(destination / "intake-report.json")
    intake_report = Artifact(
        artifact_id="meshy_native_character_intake_report_001",
        role="meshy_native_character_intake_report",
        stage="source",
        format="json",
        path=RelativeManifestPath("source/meshy_native_character_package_001/intake-report.json"),
        sha256=report_digest,
        size_bytes=report_size,
        derived_from=[item.artifact_id for item in roots],
        processor=PROCESSOR,
    )
    targets = [*roots, intake_report]
    try:
        _verify_all(asset_root, targets)
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    source_revision = manifest.revision
    manifest.artifacts.extend(targets)
    manifest.input.kind = "external"
    manifest.notes = (
        "User-authorized local Meshy provider-native biped download. Provider task metadata is "
        "user-observed; this intake service performed no provider lookup or download."
    )
    transition_workflow(manifest, WorkflowState.DOWNLOADED)
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    try:
        repository.save(
            manifest,
            "source.meshy_native_character_package_added",
            expected_revision=source_revision,
        )
    except BaseException:
        live = repository.load(asset_id)
        if live.revision == manifest.revision and _references(live, targets):
            diagnosis = repository.diagnose_pending_save(asset_id)
            if diagnosis.status in {"event_missing", "event_partial", "event_complete"}:
                repository.reconcile_pending_save(asset_id)
            _verify_all(asset_root, targets)
            return targets
        if live.revision == source_revision and not _references(live, targets):
            shutil.rmtree(destination, ignore_errors=True)
        raise
    _verify_all(asset_root, targets)
    return targets


def _members(path: Path) -> dict[str, zipfile.ZipInfo]:
    try:
        with zipfile.ZipFile(path) as archive:
            entries = [item for item in archive.infolist() if not item.is_dir()]
    except (OSError, zipfile.BadZipFile) as exc:
        raise FoundryError(f"Meshy native character ZIP is invalid: {exc}") from exc
    if len(entries) != 3:
        raise FoundryError("Meshy native character ZIP must contain exactly three files.")
    found: dict[str, zipfile.ZipInfo] = {}
    for item in entries:
        name = PurePosixPath(item.filename.replace("\\", "/"))
        mode = item.external_attr >> 16
        if (
            name.is_absolute()
            or ".." in name.parts
            or not name.name
            or (mode and stat.S_ISLNK(mode))
            or item.flag_bits & 0x1
            or item.file_size <= 0
            or item.file_size > MAX_MEMBER_BYTES
            or item.compress_size <= 0
            or item.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
        ):
            raise FoundryError("Meshy native character ZIP contains an unsafe entry.")
        lowered = name.name.casefold()
        key = (
            "character"
            if lowered.endswith("character_output.fbx")
            else "walking"
            if lowered.endswith("animation_walking_withskin.fbx")
            else "texture"
            if lowered.endswith(".png")
            else None
        )
        if key is None or key in found:
            raise FoundryError("Meshy native character ZIP has unexpected member names.")
        found[key] = item
    if set(found) != {"character", "walking", "texture"}:
        raise FoundryError("Meshy native character ZIP is missing required members.")
    return found


def _require_metadata(value: dict[str, str]) -> None:
    expected = {
        "source_task_id",
        "source_display_name",
        "remesh_task_id",
        "remesh_face_count",
        "rig_task_id",
        "excluded_duplicate_rig_task_id",
    }
    if set(value) != expected or any(not isinstance(item, str) for item in value.values()):
        raise FoundryError("Meshy native character provider metadata is incomplete.")


def _require_sha256(value: str) -> None:
    if len(value) != 64 or any(item not in "0123456789abcdefABCDEF" for item in value):
        raise FoundryError("Expected Meshy native character ZIP hash must be SHA-256.")


def _hash(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _copy_new(source: Path, destination: Path) -> None:
    with source.open("rb") as input_stream, destination.open("xb") as output_stream:
        shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
        output_stream.flush()
        os.fsync(output_stream.fileno())


def _write_new(path: Path, value: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def _verify_all(asset_root: Path, artifacts: list[Artifact]) -> None:
    for artifact in artifacts:
        path = contained_path(asset_root, artifact.path)
        if not path.is_file() or _hash(path) != (artifact.sha256, artifact.size_bytes):
            raise FoundryError(f"Meshy native character intake byte mismatch: {artifact.artifact_id}")


def _references(manifest, artifacts: list[Artifact]) -> bool:
    existing = {item.artifact_id: item for item in manifest.artifacts}
    return all(
        existing.get(item.artifact_id) is not None
        and existing[item.artifact_id].model_dump(mode="json") == item.model_dump(mode="json")
        for item in artifacts
    )
