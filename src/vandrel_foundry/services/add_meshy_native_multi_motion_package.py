import hashlib
import os
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, utc_now
from vandrel_foundry.domain.meshy_native_multi_motion import (
    MeshyNativeMultiMotionEntry,
    MeshyNativeMultiMotionIntakeReport,
)
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.domain.workflow_policy import invalidate_approval
from vandrel_foundry.services.windows_acl_policy import apply_candidate_acl
from vandrel_foundry.storage.atomic import json_bytes
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path

PROCESSOR = Processor(name="local_meshy_native_multi_motion_intake", version="1")
ARCHIVE_ID = "meshy_native_multi_motion_archive_root_001"
TEXTURE_ID = "meshy_native_multi_motion_texture_root_001"
REPORT_ID = "meshy_native_multi_motion_intake_report_001"
FBX_IDS = tuple(
    f"meshy_native_multi_motion_fbx_root_{index:03d}" for index in range(1, 21)
)
ROOT_IDS = frozenset((ARCHIVE_ID, TEXTURE_ID, *FBX_IDS))
ACCEPTED_PREEXISTING_ROOT_IDS = frozenset(
    {
        "meshy_native_character_archive_root_001",
        "meshy_native_character_fbx_root_001",
        "meshy_native_walking_fbx_root_001",
        "meshy_native_character_texture_root_001",
        "meshy_native_motion_model_root_001",
        "meshy_native_motion_report_root_001",
    }
)
LEGACY_UUID = "019fee70-fd9d-7b6e-914a-d6dad2a49eeb"
MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_RATIO = 250


def add_meshy_native_multi_motion_package(
    config: FoundryConfig,
    asset_id: str,
    archive_path: Path,
    expected_archive_sha256: str,
) -> list[Artifact]:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    committed = _committed_artifacts(manifest)
    if committed:
        _verify_retry(
            repository.asset_directory(asset_id),
            committed,
            archive_path,
            expected_archive_sha256,
        )
        return committed
    if manifest.asset.lane != "humanoid" or manifest.workflow.state is not WorkflowState.PROCESSED:
        raise FoundryError("Meshy multi-motion intake requires a processed humanoid candidate.")
    current_root_ids = {
        artifact.artifact_id
        for artifact in manifest.artifacts
        if artifact.stage == "source" and not artifact.derived_from
    }
    if current_root_ids != ACCEPTED_PREEXISTING_ROOT_IDS:
        raise FoundryError(
            "Meshy multi-motion intake requires the exact six accepted character and "
            "canary source roots before extension."
        )
    if not archive_path.is_file() or archive_path.suffix.lower() != ".zip":
        raise FoundryError("Meshy multi-motion intake requires one ZIP archive.")
    _require_sha256(expected_archive_sha256)
    source_hash = _hash_file(archive_path)
    if source_hash[0] != expected_archive_sha256:
        raise FoundryError("Meshy multi-motion archive hash does not match the authorized source.")
    asset_root = repository.asset_directory(asset_id)
    destination = asset_root / "source" / "meshy_native_multi_motion_package_001"
    if destination.exists():
        raise FoundryError("Meshy multi-motion source destination already exists.")
    temporary = Path(
        tempfile.mkdtemp(prefix=".meshy-native-multi-motion-", dir=asset_root / "source")
    )
    promoted = False
    try:
        apply_candidate_acl(config, temporary)
        archive_copy = temporary / "source.zip"
        _copy_new(archive_path, archive_copy)
        if _hash_file(archive_copy) != source_hash or _hash_file(archive_path) != source_hash:
            raise FoundryError("Meshy multi-motion archive changed while copied.")
        members = _inspect_archive(archive_copy)
        fbx_members = [item for item in members if item.filename.lower().endswith(".fbx")]
        texture_member = next(
            item for item in members if item.filename.lower().endswith(".png")
        )
        fbx_directory = temporary / "fbx"
        texture_directory = temporary / "texture"
        fbx_directory.mkdir()
        texture_directory.mkdir()
        entry_models: list[MeshyNativeMultiMotionEntry] = []
        extracted_paths: dict[str, Path] = {}
        with zipfile.ZipFile(archive_copy) as archive:
            for index, info in enumerate(fbx_members, start=1):
                exact_name = _exact_export_name(info.filename)
                relative = RelativeManifestPath(f"fbx/{index:02d}-{_slug(exact_name)}.fbx")
                output = contained_path(temporary, relative)
                _extract_new(archive, info, output)
                digest, size = _hash_file(output)
                artifact_id = FBX_IDS[index - 1]
                extracted_paths[artifact_id] = output
                entry_models.append(
                    MeshyNativeMultiMotionEntry(
                        artifact_id=artifact_id,
                        role="meshy_native_multi_animation_fbx",
                        archive_member=info.filename,
                        archive_member_crc32=f"{info.CRC:08x}",
                        exact_export_name=exact_name,
                        sha256=digest,
                        size_bytes=size,
                        runtime_eligibility=(
                            "provenance_only_legacy_outlier"
                            if exact_name == LEGACY_UUID
                            else "identity_normalized"
                        ),
                    )
                )
            texture_output = texture_directory / "texture.png"
            _extract_new(archive, texture_member, texture_output)
        texture_hash, texture_size = _hash_file(texture_output)
        extracted_paths[TEXTURE_ID] = texture_output
        entry_models.append(
            MeshyNativeMultiMotionEntry(
                artifact_id=TEXTURE_ID,
                role="meshy_native_multi_texture",
                archive_member=texture_member.filename,
                archive_member_crc32=f"{texture_member.CRC:08x}",
                exact_export_name=Path(texture_member.filename).name,
                sha256=texture_hash,
                size_bytes=texture_size,
                runtime_eligibility="identity_normalized",
            )
        )
        intake = MeshyNativeMultiMotionIntakeReport(
            schema="vandrel_foundry_meshy_native_multi_motion_intake/1.0",
            authority_basis="user_selected_local_source",
            archive_original_name=archive_path.name,
            archive_artifact_id=ARCHIVE_ID,
            archive_sha256=source_hash[0],
            archive_size_bytes=source_hash[1],
            source_entry_count=21,
            animation_entry_count=20,
            texture_entry_count=1,
            entries=entry_models,
            provider_task_metadata="not_inspected",
            license_metadata="not_inspected",
            external_provider_lookup="not_performed_by_intake_service",
            provider_download="not_performed_by_intake_service",
            semantic_policy="archive_names_are_provider_semantics_except_unresolved_uuids",
            gender_policy=(
                "female_prefix_is_provenance_only_and_does_not_restrict_humanoid_use"
            ),
            permission_scope="local_unreleased_candidate_processing_only",
        )
        report_copy = temporary / "intake-report.json"
        _write_new(report_copy, json_bytes(intake.model_dump(mode="json", by_alias=True)))
        if _hash_file(archive_path) != source_hash:
            raise FoundryError("Meshy multi-motion archive changed before promotion.")
        os.rename(temporary, destination)
        promoted = True
    except BaseException:
        if not promoted:
            shutil.rmtree(temporary, ignore_errors=True)
        raise

    try:
        artifacts = _artifacts(destination, source_hash, entry_models)
        _verify_target_bytes(asset_root, artifacts)
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    source_revision = manifest.revision
    manifest.artifacts.extend(artifacts)
    manifest.validation.result = "not_run"
    manifest.validation.checks = []
    manifest.quality.observed = {}
    invalidate_approval(manifest)
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    try:
        repository.save(
            manifest,
            "source.meshy_native_multi_motion_package_added",
            expected_revision=source_revision,
        )
    except BaseException:
        live = repository.load(asset_id)
        if _is_exact_target(live, manifest.revision, artifacts):
            diagnosis = repository.diagnose_pending_save(asset_id)
            if diagnosis.status in {"event_missing", "event_partial", "event_complete"}:
                repository.reconcile_pending_save(asset_id)
            _verify_target_bytes(asset_root, artifacts)
            return artifacts
        if live.revision == source_revision and not _references(live, artifacts):
            shutil.rmtree(destination, ignore_errors=True)
        raise
    _verify_target_bytes(asset_root, artifacts)
    return artifacts


def _artifacts(
    destination: Path,
    source_hash: tuple[str, int],
    entries: list[MeshyNativeMultiMotionEntry],
) -> list[Artifact]:
    values = [
        Artifact(
            artifact_id=ARCHIVE_ID,
            role="meshy_native_multi_motion_archive",
            stage="source",
            format="zip",
            path=RelativeManifestPath(
                "source/meshy_native_multi_motion_package_001/source.zip"
            ),
            sha256=source_hash[0],
            size_bytes=source_hash[1],
            derived_from=[],
            processor=PROCESSOR,
        )
    ]
    for entry in entries:
        if entry.role == "meshy_native_multi_texture":
            relative = RelativeManifestPath(
                "source/meshy_native_multi_motion_package_001/texture/texture.png"
            )
            role = "meshy_native_multi_motion_texture"
            format_name = "png"
        else:
            index = FBX_IDS.index(entry.artifact_id) + 1
            relative = RelativeManifestPath(
                "source/meshy_native_multi_motion_package_001/"
                f"fbx/{index:02d}-{_slug(entry.exact_export_name)}.fbx"
            )
            role = "meshy_native_multi_motion_fbx"
            format_name = "fbx"
        values.append(
            Artifact(
                artifact_id=entry.artifact_id,
                role=role,
                stage="source",
                format=format_name,
                path=relative,
                sha256=entry.sha256,
                size_bytes=entry.size_bytes,
                derived_from=[],
                processor=PROCESSOR,
            )
        )
    report_path = destination / "intake-report.json"
    report_hash = _hash_file(report_path)
    values.append(
        Artifact(
            artifact_id=REPORT_ID,
            role="meshy_native_multi_motion_intake_report",
            stage="source",
            format="json",
            path=RelativeManifestPath(
                "source/meshy_native_multi_motion_package_001/intake-report.json"
            ),
            sha256=report_hash[0],
            size_bytes=report_hash[1],
            derived_from=sorted(ROOT_IDS),
            processor=PROCESSOR,
        )
    )
    return values


def _inspect_archive(path: Path) -> list[zipfile.ZipInfo]:
    try:
        with zipfile.ZipFile(path) as archive:
            members = [item for item in archive.infolist() if not item.is_dir()]
    except (OSError, zipfile.BadZipFile) as exc:
        raise FoundryError(f"Meshy multi-motion archive is invalid: {exc}") from exc
    if len(members) != 21:
        raise FoundryError("Meshy multi-motion archive must contain exactly 21 files.")
    normalized_names: set[str] = set()
    for info in members:
        name = PurePosixPath(info.filename.replace("\\", "/"))
        mode = info.external_attr >> 16
        key = info.filename.replace("\\", "/").casefold()
        if (
            name.is_absolute()
            or ".." in name.parts
            or not name.name
            or key in normalized_names
            or (mode and stat.S_ISLNK(mode))
            or info.flag_bits & 0x1
            or info.file_size <= 0
            or info.file_size > MAX_MEMBER_BYTES
            or info.compress_size <= 0
            or info.file_size / info.compress_size > MAX_RATIO
            or info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
        ):
            raise FoundryError("Meshy multi-motion archive contains an unsafe entry.")
        normalized_names.add(key)
    fbx = sorted(
        (item for item in members if item.filename.lower().endswith("_withskin.fbx")),
        key=lambda item: item.filename.casefold(),
    )
    textures = [item for item in members if item.filename.lower().endswith(".png")]
    if len(fbx) != 20 or len(textures) != 1 or len(fbx) + len(textures) != 21:
        raise FoundryError("Meshy multi-motion archive requires 20 withSkin FBXs and one PNG.")
    exact_names = [_exact_export_name(item.filename) for item in fbx]
    if len(set(exact_names)) != 20 or exact_names.count(LEGACY_UUID) != 1:
        raise FoundryError("Meshy multi-motion exact action names are invalid.")
    return [*fbx, textures[0]]


def _exact_export_name(member: str) -> str:
    filename = PurePosixPath(member.replace("\\", "/")).name
    match = re.fullmatch(
        r"Meshy_AI_Primal_Female_Caveman_biped_Animation_(.+)_withSkin\.fbx",
        filename,
        flags=re.IGNORECASE,
    )
    if match is None or not match.group(1):
        raise FoundryError("Meshy multi-motion FBX name does not match the exact export shape.")
    return match.group(1)


def _verify_retry(
    asset_root: Path,
    artifacts: list[Artifact],
    archive_path: Path,
    expected_archive_sha256: str,
) -> None:
    by_id = {item.artifact_id: item for item in artifacts}
    if set(by_id) != {REPORT_ID, *ROOT_IDS}:
        raise FoundryError("Existing Meshy multi-motion intake is incomplete.")
    if _hash_file(archive_path)[0] != expected_archive_sha256:
        raise FoundryError("Retry archive does not match the committed multi-motion root.")
    archive = by_id[ARCHIVE_ID]
    if archive.sha256 != expected_archive_sha256:
        raise FoundryError("Committed Meshy multi-motion archive hash is different.")
    _verify_target_bytes(asset_root, artifacts)


def _committed_artifacts(manifest) -> list[Artifact]:
    ids = {REPORT_ID, *ROOT_IDS}
    return [item for item in manifest.artifacts if item.artifact_id in ids]


def _verify_target_bytes(asset_root: Path, artifacts: list[Artifact]) -> None:
    for artifact in artifacts:
        path = contained_path(asset_root, artifact.path)
        if not path.is_file() or _hash_file(path) != (artifact.sha256, artifact.size_bytes):
            raise FoundryError(
                f"Manifest-owned Meshy multi-motion byte changed: {artifact.artifact_id}."
            )


def _extract_new(archive: zipfile.ZipFile, info: zipfile.ZipInfo, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(info, "r") as source, destination.open("xb") as output:
        shutil.copyfileobj(source, output, length=1024 * 1024)
        output.flush()
        os.fsync(output.fileno())
    if destination.stat().st_size != info.file_size:
        raise FoundryError("Extracted Meshy multi-motion member size changed.")


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


def _require_sha256(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise FoundryError("Expected source hash must be lowercase SHA-256.")


def _slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    if not result:
        raise FoundryError("Meshy multi-motion entry has no portable slug.")
    return result


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
