import hashlib
import json
import os
import shutil
import stat
import struct
import tempfile
import zipfile
from dataclasses import dataclass
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
API_PROCESSOR = Processor(name="local_meshy_native_character_api_intake", version="1")
MAX_MEMBER_BYTES = 64 * 1024 * 1024

LEGACY_CHARACTER_ROOT_SPECS = {
    "meshy_native_character_archive_root_001": ("meshy_native_character_archive", "zip"),
    "meshy_native_character_fbx_root_001": ("meshy_native_character_fbx", "fbx"),
    "meshy_native_walking_fbx_root_001": ("meshy_native_walking_fbx", "fbx"),
    "meshy_native_character_texture_root_001": ("meshy_native_character_texture", "png"),
}
API_CHARACTER_ROOT_SPECS = {
    "meshy_native_character_fbx_root_001": ("meshy_native_character_fbx", "fbx"),
    "meshy_native_character_glb_root_001": ("meshy_native_character_glb", "glb"),
    "meshy_native_walking_fbx_root_001": ("meshy_native_walking_fbx", "fbx"),
    "meshy_native_running_fbx_root_001": ("meshy_native_running_fbx", "fbx"),
}


@dataclass(frozen=True)
class MeshyNativeCharacterSourceProfile:
    name: str
    root_specs: dict[str, tuple[str, str]]
    texture_artifact_id: str

    @property
    def root_ids(self) -> frozenset[str]:
        return frozenset(self.root_specs)


LEGACY_CHARACTER_SOURCE = MeshyNativeCharacterSourceProfile(
    "provider_ui_zip",
    LEGACY_CHARACTER_ROOT_SPECS,
    "meshy_native_character_texture_root_001",
)
API_CHARACTER_SOURCE = MeshyNativeCharacterSourceProfile(
    "provider_api_direct",
    API_CHARACTER_ROOT_SPECS,
    "meshy_native_character_texture_001",
)
CHARACTER_SOURCE_PROFILES = (LEGACY_CHARACTER_SOURCE, API_CHARACTER_SOURCE)


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


def add_meshy_native_character_api_package(
    config: FoundryConfig,
    asset_id: str,
    provider_outputs: dict[str, Path],
    expected_sha256: dict[str, str],
    provider_metadata: dict[str, object],
) -> list[Artifact]:
    """Intake exact outputs returned by one completed Meshy rigging API task.

    The API files remain the immutable roots.  The texture is extracted from the
    exact provider GLB and is therefore recorded as a derived artifact, never as
    a provider archive member or independent provider root.
    """
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.asset.lane != "humanoid" or manifest.workflow.state is not WorkflowState.DRAFT:
        raise FoundryError("Meshy native API intake requires a draft humanoid candidate.")
    expected_roles = {
        "character_fbx": ".fbx",
        "character_glb": ".glb",
        "walking_fbx": ".fbx",
        "running_fbx": ".fbx",
    }
    if set(provider_outputs) != set(expected_roles) or set(expected_sha256) != set(expected_roles):
        raise FoundryError("Meshy native API intake requires the exact four provider outputs.")
    _require_api_metadata(provider_metadata)
    source_facts: dict[str, tuple[str, int]] = {}
    for role, suffix in expected_roles.items():
        path = provider_outputs[role]
        _require_sha256(expected_sha256[role])
        if not path.is_file() or path.suffix.casefold() != suffix:
            raise FoundryError(f"Meshy native API {role} source is missing or has the wrong format.")
        source_facts[role] = _hash(path)
        if source_facts[role][0] != expected_sha256[role].casefold():
            raise FoundryError(f"Meshy native API {role} hash does not match the authorized output.")

    asset_root = repository.asset_directory(asset_id)
    destination = asset_root / "source" / "meshy_native_character_api_package_001"
    if destination.exists():
        raise FoundryError("Meshy native API source destination already exists.")
    temporary = Path(tempfile.mkdtemp(prefix=".meshy-native-character-api-", dir=asset_root / "source"))
    filenames = {
        "character_fbx": "character.fbx",
        "character_glb": "character.glb",
        "walking_fbx": "walking.fbx",
        "running_fbx": "running.fbx",
    }
    try:
        apply_candidate_acl(config, temporary)
        for role, filename in filenames.items():
            copied = temporary / filename
            _copy_new(provider_outputs[role], copied)
            if _hash(copied) != source_facts[role] or _hash(provider_outputs[role]) != source_facts[role]:
                raise FoundryError(f"Meshy native API {role} changed while it was copied.")
        embedded = _extract_embedded_png(temporary / "character.glb", temporary / "texture.png")
        report = {
            "schema": "vandrel_foundry_meshy_native_character_intake/1.1",
            "authority_basis": "user_authorized_zero_credit_provider_api_download",
            "provider_metadata_observation": "api_task_receipt_and_user_observed_identity_crosswalk",
            "provider_metadata": provider_metadata,
            "provider_outputs": {
                role: {
                    "sha256": source_facts[role][0],
                    "size_bytes": source_facts[role][1],
                    "format": expected_roles[role][1:],
                }
                for role in sorted(expected_roles)
            },
            "derived_texture": embedded,
            "provider_lookup": "completed_by_authorized_authenticated_api_read",
            "license_metadata": "not_inspected",
            "provider_download": "completed_by_authorized_authenticated_api_read",
            "signed_urls_retained": False,
            "secrets_retained": False,
        }
        _write_new(temporary / "intake-report.json", json_bytes(report))
        for role, filename in filenames.items():
            if _hash(temporary / filename) != source_facts[role]:
                raise FoundryError(f"Meshy native API {role} changed before promotion.")
        os.rename(temporary, destination)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    records = [
        ("meshy_native_character_fbx_root_001", "meshy_native_character_fbx", "fbx", "character.fbx"),
        ("meshy_native_character_glb_root_001", "meshy_native_character_glb", "glb", "character.glb"),
        ("meshy_native_walking_fbx_root_001", "meshy_native_walking_fbx", "fbx", "walking.fbx"),
        ("meshy_native_running_fbx_root_001", "meshy_native_running_fbx", "fbx", "running.fbx"),
    ]
    roots = [
        Artifact(
            artifact_id=artifact_id,
            role=role,
            stage="source",
            format=fmt,
            path=RelativeManifestPath(f"source/meshy_native_character_api_package_001/{filename}"),
            sha256=_hash(destination / filename)[0],
            size_bytes=_hash(destination / filename)[1],
            derived_from=[],
            processor=API_PROCESSOR,
        )
        for artifact_id, role, fmt, filename in records
    ]
    texture_hash, texture_size = _hash(destination / "texture.png")
    texture = Artifact(
        artifact_id=API_CHARACTER_SOURCE.texture_artifact_id,
        role="meshy_native_character_texture",
        stage="source",
        format="png",
        path=RelativeManifestPath("source/meshy_native_character_api_package_001/texture.png"),
        sha256=texture_hash,
        size_bytes=texture_size,
        derived_from=["meshy_native_character_glb_root_001"],
        processor=API_PROCESSOR,
    )
    report_hash, report_size = _hash(destination / "intake-report.json")
    intake_report = Artifact(
        artifact_id="meshy_native_character_intake_report_001",
        role="meshy_native_character_intake_report",
        stage="source",
        format="json",
        path=RelativeManifestPath("source/meshy_native_character_api_package_001/intake-report.json"),
        sha256=report_hash,
        size_bytes=report_size,
        derived_from=[*(item.artifact_id for item in roots), texture.artifact_id],
        processor=API_PROCESSOR,
    )
    targets = [*roots, texture, intake_report]
    try:
        _verify_all(asset_root, targets)
        _verify_api_sources(provider_outputs, source_facts)
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    source_revision = manifest.revision
    manifest.artifacts.extend(targets)
    manifest.input.kind = "external"
    manifest.notes = (
        "User-authorized zero-credit Meshy provider-native Biped outputs retrieved through the "
        "authenticated API. Exact task receipt and intended Vandrel identity crosswalk are bound "
        "without signed URLs, secrets, or redistribution claims."
    )
    transition_workflow(manifest, WorkflowState.DOWNLOADED)
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    try:
        repository.save(
            manifest,
            "source.meshy_native_character_api_package_added",
            expected_revision=source_revision,
        )
    except BaseException:
        live = repository.load(asset_id)
        if live.revision == manifest.revision and _references(live, targets):
            diagnosis = repository.diagnose_pending_save(asset_id)
            if diagnosis.status in {"event_missing", "event_partial", "event_complete"}:
                repository.reconcile_pending_save(asset_id)
            _verify_all(asset_root, targets)
            _verify_api_sources(provider_outputs, source_facts)
            return targets
        if live.revision == source_revision and not _references(live, targets):
            shutil.rmtree(destination, ignore_errors=True)
        raise
    _verify_all(asset_root, targets)
    _verify_api_sources(provider_outputs, source_facts)
    return targets


def resolve_meshy_native_character_source(
    artifacts: list[Artifact],
) -> tuple[MeshyNativeCharacterSourceProfile, dict[str, Artifact], Artifact]:
    roots = {
        item.artifact_id: item
        for item in artifacts
        if item.stage == "source" and not item.derived_from
    }
    matches = [profile for profile in CHARACTER_SOURCE_PROFILES if profile.root_ids <= roots.keys()]
    if len(matches) != 1:
        raise FoundryError(
            "Meshy native character source profile requires exact four character roots in "
            "the exact four-root union; the profile is missing or ambiguous."
        )
    profile = matches[0]
    selected = {artifact_id: roots[artifact_id] for artifact_id in profile.root_ids}
    if any(
        (selected[artifact_id].role, selected[artifact_id].format) != expected
        for artifact_id, expected in profile.root_specs.items()
    ):
        raise FoundryError("Meshy native character root roles or formats are invalid.")
    textures = [item for item in artifacts if item.artifact_id == profile.texture_artifact_id]
    if len(textures) != 1:
        raise FoundryError("Meshy native character texture artifact is missing or ambiguous.")
    texture = textures[0]
    if (texture.role, texture.format) != ("meshy_native_character_texture", "png"):
        raise FoundryError("Meshy native character texture role or format is invalid.")
    if profile is API_CHARACTER_SOURCE and texture.derived_from != ["meshy_native_character_glb_root_001"]:
        raise FoundryError("Meshy native API texture must derive only from the exact character GLB root.")
    return profile, selected, texture


def _require_api_metadata(value: dict[str, object]) -> None:
    expected = {
        "source_task_id",
        "source_display_name",
        "remesh_task_id",
        "remesh_face_count",
        "remesh_vertex_count",
        "rig_task_id",
        "stable_vandrel_character_id",
        "rig_status",
        "rig_progress",
        "consumed_credits",
        "provider_balance_before",
        "provider_balance_after",
        "created_at_epoch_ms",
        "started_at_epoch_ms",
        "finished_at_epoch_ms",
    }
    if set(value) != expected:
        raise FoundryError("Meshy native API provider metadata is incomplete.")
    text_keys = {
        "source_task_id",
        "source_display_name",
        "remesh_task_id",
        "rig_task_id",
        "stable_vandrel_character_id",
        "rig_status",
    }
    integer_keys = expected - text_keys
    if any(not isinstance(value[key], str) or not value[key] for key in text_keys):
        raise FoundryError("Meshy native API provider identity metadata is invalid.")
    if any(not isinstance(value[key], int) or isinstance(value[key], bool) for key in integer_keys):
        raise FoundryError("Meshy native API provider numeric metadata is invalid.")
    if (
        value["rig_status"] != "SUCCEEDED"
        or value["rig_progress"] != 100
        or value["consumed_credits"] != 0
        or value["provider_balance_before"] != value["provider_balance_after"]
    ):
        raise FoundryError("Meshy native API task is not a completed zero-credit rig operation.")


def _extract_embedded_png(glb_path: Path, destination: Path) -> dict[str, object]:
    try:
        with glb_path.open("rb") as stream:
            header = stream.read(12)
            if len(header) != 12:
                raise FoundryError("Meshy native character GLB header is truncated.")
            magic, version, declared_length = struct.unpack("<4sII", header)
            if magic != b"glTF" or version != 2 or declared_length != glb_path.stat().st_size:
                raise FoundryError("Meshy native character API output is not an exact GLB 2.0 file.")
            json_length, json_type = struct.unpack("<II", stream.read(8))
            if json_type != 0x4E4F534A or json_length > MAX_MEMBER_BYTES:
                raise FoundryError("Meshy native character GLB JSON chunk is invalid.")
            document = json.loads(stream.read(json_length).rstrip(b" \t\r\n\0").decode("utf-8"))
            binary_length, binary_type = struct.unpack("<II", stream.read(8))
            if binary_type != 0x004E4942 or binary_length > MAX_MEMBER_BYTES:
                raise FoundryError("Meshy native character GLB binary chunk is invalid.")
            binary = stream.read(binary_length)
            if len(binary) != binary_length:
                raise FoundryError("Meshy native character GLB binary chunk is truncated.")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, struct.error) as exc:
        raise FoundryError(f"Meshy native character GLB inspection failed: {exc}") from exc
    images = document.get("images")
    views = document.get("bufferViews")
    skins = document.get("skins")
    nodes = document.get("nodes")
    if (
        not isinstance(images, list)
        or len(images) != 1
        or not isinstance(views, list)
        or not isinstance(skins, list)
        or len(skins) != 1
        or not isinstance(nodes, list)
        or not isinstance(skins[0], dict)
        or len(skins[0].get("joints", [])) != 24
    ):
        raise FoundryError("Meshy native character GLB must contain one embedded image and one 24-joint skin.")
    image = images[0]
    if not isinstance(image, dict) or image.get("mimeType") != "image/png":
        raise FoundryError("Meshy native character GLB image must be an embedded PNG.")
    view_index = image.get("bufferView")
    if not isinstance(view_index, int) or isinstance(view_index, bool) or not 0 <= view_index < len(views):
        raise FoundryError("Meshy native character GLB image buffer view is invalid.")
    view = views[view_index]
    if not isinstance(view, dict):
        raise FoundryError("Meshy native character GLB image buffer view is invalid.")
    offset = view.get("byteOffset", 0)
    length = view.get("byteLength")
    if (
        not isinstance(offset, int)
        or isinstance(offset, bool)
        or not isinstance(length, int)
        or isinstance(length, bool)
        or offset < 0
        or length <= 0
        or offset + length > len(binary)
    ):
        raise FoundryError("Meshy native character GLB image byte range is invalid.")
    payload = binary[offset : offset + length]
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise FoundryError("Meshy native character GLB embedded texture is not PNG data.")
    _write_new(destination, payload)
    digest, size = _hash(destination)
    return {
        "artifact_id": API_CHARACTER_SOURCE.texture_artifact_id,
        "source_root_artifact_id": "meshy_native_character_glb_root_001",
        "image_name": image.get("name") if isinstance(image.get("name"), str) else "not_named",
        "mime_type": "image/png",
        "buffer_view": view_index,
        "sha256": digest,
        "size_bytes": size,
    }


def _verify_api_sources(
    paths: dict[str, Path],
    expected: dict[str, tuple[str, int]],
) -> None:
    for role, path in paths.items():
        if _hash(path) != expected[role]:
            raise FoundryError(f"Meshy native API source changed before transaction completion: {role}")


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
