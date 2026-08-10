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

INTAKE_PROCESSOR = Processor(name="local_meshy_native_animation_intake", version="1")
ARCHIVE_ID = "meshy_native_archive_root_001"
FBX_ID = "meshy_native_animation_fbx_root_001"
REPORT_ID = "meshy_native_source_intake_report_001"
MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_RATIO = 250


def add_meshy_native_animation_package(
    config: FoundryConfig,
    asset_id: str,
    archive_path: Path,
    expected_archive_sha256: str,
    expected_fbx_sha256: str,
) -> list[Artifact]:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    existing = _committed_artifacts(manifest)
    if existing:
        _verify_retry(
            repository.asset_directory(asset_id),
            existing,
            archive_path,
            expected_archive_sha256,
            expected_fbx_sha256,
        )
        return existing
    if manifest.asset.lane != "humanoid" or manifest.workflow.state is not WorkflowState.DRAFT:
        raise FoundryError("Meshy native source intake requires a draft humanoid candidate.")
    if not archive_path.is_file() or archive_path.suffix.lower() != ".zip":
        raise FoundryError("Meshy native source intake requires one ZIP archive.")
    _require_sha256(expected_archive_sha256)
    _require_sha256(expected_fbx_sha256)
    archive_hash, archive_size = _hash_file(archive_path)
    if archive_hash != expected_archive_sha256:
        raise FoundryError("Meshy native archive hash does not match the authorized source.")
    asset_root = repository.asset_directory(asset_id)
    destination = asset_root / "source" / "meshy_native_package_001"
    if destination.exists():
        raise FoundryError("Meshy native source destination already exists.")
    temporary = Path(
        tempfile.mkdtemp(prefix=".meshy-native-package-", dir=asset_root / "source")
    )
    try:
        apply_candidate_acl(config, temporary)
        archive_copy = temporary / "source.zip"
        _copy_new(archive_path, archive_copy)
        copied_archive_hash, copied_archive_size = _hash_file(archive_copy)
        if (copied_archive_hash, copied_archive_size) != (archive_hash, archive_size):
            raise FoundryError("Meshy native archive changed while it was copied.")
        info = _inspect_archive(archive_copy)
        with zipfile.ZipFile(archive_copy) as archive, archive.open(info, "r") as source:
            fbx_copy = temporary / "merged_animations.fbx"
            with fbx_copy.open("xb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
        fbx_hash, fbx_size = _hash_file(fbx_copy)
        if fbx_hash != expected_fbx_sha256 or fbx_size != info.file_size:
            raise FoundryError("Extracted Meshy FBX does not match the authorized source.")
        intake = {
            "schema": "vandrel_foundry_meshy_native_source_intake/1.0",
            "authority_basis": "user_selected_local_source",
            "archive_original_name": archive_path.name,
            "archive_sha256": archive_hash,
            "archive_size_bytes": archive_size,
            "archive_member": info.filename,
            "archive_member_crc32": f"{info.CRC:08x}",
            "fbx_sha256": fbx_hash,
            "fbx_size_bytes": fbx_size,
            "provider_task_metadata": "not_inspected",
            "license_metadata": "not_inspected",
            "external_provider_lookup": "not_performed_by_intake_service",
            "provider_download": "not_performed_by_intake_service",
            "semantic_policy": "retain_exact_action_names_and_unresolved_uuids",
            "permission_scope": "local_source_intake_and_unreleased_technical_canary_only",
        }
        report_copy = temporary / "intake-report.json"
        _write_new(report_copy, json_bytes(intake))
        os.rename(temporary, destination)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    fbx_final = destination / "merged_animations.fbx"
    report_final = destination / "intake-report.json"
    report_hash, report_size = _hash_file(report_final)
    roots = [
        Artifact(
            artifact_id=ARCHIVE_ID,
            role="meshy_native_archive",
            stage="source",
            format="zip",
            path=RelativeManifestPath("source/meshy_native_package_001/source.zip"),
            sha256=archive_hash,
            size_bytes=archive_size,
            derived_from=[],
            processor=INTAKE_PROCESSOR,
        ),
        Artifact(
            artifact_id=FBX_ID,
            role="meshy_native_animation_fbx",
            stage="source",
            format="fbx",
            path=RelativeManifestPath("source/meshy_native_package_001/merged_animations.fbx"),
            sha256=expected_fbx_sha256,
            size_bytes=fbx_final.stat().st_size,
            derived_from=[],
            processor=INTAKE_PROCESSOR,
        ),
    ]
    report_artifact = Artifact(
        artifact_id=REPORT_ID,
        role="meshy_native_source_intake_report",
        stage="source",
        format="json",
        path=RelativeManifestPath("source/meshy_native_package_001/intake-report.json"),
        sha256=report_hash,
        size_bytes=report_size,
        derived_from=[ARCHIVE_ID, FBX_ID],
        processor=INTAKE_PROCESSOR,
    )
    target_artifacts = [*roots, report_artifact]
    try:
        _verify_target_bytes(asset_root, target_artifacts)
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    source_revision = manifest.revision
    manifest.artifacts.extend(target_artifacts)
    manifest.input.kind = "external"
    manifest.notes = (
        "User-selected local Meshy animation package. This intake service performed no "
        "external provider or license lookup. Unreleased technical canary only."
    )
    transition_workflow(manifest, WorkflowState.DOWNLOADED)
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    try:
        repository.save(
            manifest,
            "source.meshy_native_animation_package_added",
            expected_revision=source_revision,
        )
    except BaseException:
        live = repository.load(asset_id)
        if _is_exact_target(live, manifest.revision, target_artifacts):
            diagnosis = repository.diagnose_pending_save(asset_id)
            if diagnosis.status in {"event_missing", "event_partial", "event_complete"}:
                repository.reconcile_pending_save(asset_id)
            _verify_target_bytes(asset_root, target_artifacts)
            return target_artifacts
        if live.revision == source_revision and not _references(live, target_artifacts):
            shutil.rmtree(destination, ignore_errors=True)
        raise
    _verify_target_bytes(asset_root, target_artifacts)
    return target_artifacts


def _inspect_archive(path: Path) -> zipfile.ZipInfo:
    try:
        with zipfile.ZipFile(path) as archive:
            members = [item for item in archive.infolist() if not item.is_dir()]
    except (OSError, zipfile.BadZipFile) as exc:
        raise FoundryError(f"Meshy native archive is invalid: {exc}") from exc
    if len(members) != 1 or not members[0].filename.lower().endswith(".fbx"):
        raise FoundryError("Meshy native archive must contain exactly one FBX file.")
    info = members[0]
    name = PurePosixPath(info.filename.replace("\\", "/"))
    mode = info.external_attr >> 16
    if (
        name.is_absolute()
        or ".." in name.parts
        or not name.name
        or (mode and stat.S_ISLNK(mode))
        or info.flag_bits & 0x1
        or info.file_size <= 0
        or info.file_size > MAX_MEMBER_BYTES
        or info.compress_size <= 0
        or info.file_size / info.compress_size > MAX_RATIO
        or info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
    ):
        raise FoundryError("Meshy native archive contains an unsafe FBX entry.")
    return info


def _verify_retry(
    asset_root: Path,
    artifacts: list[Artifact],
    archive_path: Path,
    expected_archive_sha256: str,
    expected_fbx_sha256: str,
) -> None:
    by_id = {item.artifact_id: item for item in artifacts}
    archive = by_id.get(ARCHIVE_ID)
    fbx = by_id.get(FBX_ID)
    report = by_id.get(REPORT_ID)
    if archive is None or fbx is None or report is None or len(artifacts) != 3:
        raise FoundryError("Existing Meshy native intake is incomplete.")
    if _hash_file(archive_path)[0] != expected_archive_sha256 or archive.sha256 != expected_archive_sha256:
        raise FoundryError("Retry archive does not match the committed Meshy root.")
    info = _inspect_archive(archive_path)
    with zipfile.ZipFile(archive_path) as value, value.open(info) as stream:
        digest = hashlib.sha256()
        size = 0
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    if digest.hexdigest() != expected_fbx_sha256 or (fbx.sha256, fbx.size_bytes) != (
        expected_fbx_sha256,
        size,
    ):
        raise FoundryError("Retry FBX does not match the committed Meshy root.")
    for artifact in artifacts:
        destination = contained_path(asset_root, artifact.path)
        if not destination.is_file() or _hash_file(destination) != (
            artifact.sha256,
            artifact.size_bytes,
        ):
            raise FoundryError("Manifest-owned Meshy native intake bytes are missing or changed.")


def _verify_target_bytes(asset_root: Path, artifacts: list[Artifact]) -> None:
    for artifact in artifacts:
        destination = contained_path(asset_root, artifact.path)
        if not destination.is_file() or _hash_file(destination) != (
            artifact.sha256,
            artifact.size_bytes,
        ):
            raise FoundryError(
                f"Promoted Meshy native intake bytes changed: {artifact.artifact_id}"
            )


def _committed_artifacts(manifest) -> list[Artifact]:
    ids = {ARCHIVE_ID, FBX_ID, REPORT_ID}
    values = [item for item in manifest.artifacts if item.artifact_id in ids]
    if values and manifest.workflow.state is not WorkflowState.DOWNLOADED:
        raise FoundryError("Existing Meshy native roots are not a committed intake target.")
    return values


def _require_sha256(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise FoundryError("Expected source hashes must be lowercase SHA-256 values.")


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


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _is_exact_target(manifest, revision: int, artifacts: list[Artifact]) -> bool:
    return manifest.revision == revision and _references(manifest, artifacts)


def _references(manifest, artifacts: list[Artifact]) -> bool:
    by_id = {item.artifact_id: item for item in manifest.artifacts}
    return all(
        by_id.get(expected.artifact_id) is not None
        and by_id[expected.artifact_id].model_dump(mode="json")
        == expected.model_dump(mode="json")
        for expected in artifacts
    )
