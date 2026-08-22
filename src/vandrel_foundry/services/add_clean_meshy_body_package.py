"""Transactional, exact-inventory intake for clean Meshy body packages."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from pydantic import ValidationError

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.clean_meshy_body import (
    CleanMeshyBodyIntakeRequest,
    canonical_policy_sha256,
)
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.domain.workflow_policy import transition_workflow
from vandrel_foundry.services.windows_acl_policy import apply_candidate_acl
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path

PROCESSOR = Processor(name="local_clean_meshy_body_intake", version="1")
MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_COMPRESSION_RATIO = 250


def add_clean_meshy_body_package(
    config: FoundryConfig, asset_id: str, request_path: Path
) -> list[Artifact]:
    """Add one request-bound provider ZIP without treating extraction as custody."""

    request = _load_request(request_path)
    if request.asset_id != asset_id:
        raise FoundryError("Clean-body request asset id differs from the candidate.")
    if canonical_policy_sha256(request.package_policy) != request.package_policy_sha256:
        raise FoundryError("Clean-body package policy hash does not bind the exact policy.")

    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.asset.lane != "humanoid" or manifest.workflow.state is not WorkflowState.DRAFT:
        raise FoundryError("Clean Meshy body intake requires a draft humanoid candidate.")
    archive_path = _resolve_input(request_path, request.archive.path)
    bone_map_path = _resolve_input(request_path, request.accepted_bone_map.path)
    sidecar_path = _resolve_input(request_path, request.accepted_import_sidecar_policy.path)
    _require_exact_file(archive_path, request.archive.sha256, request.archive.size_bytes, "archive")
    _require_exact_file(
        bone_map_path,
        request.accepted_bone_map.sha256,
        request.accepted_bone_map.size_bytes,
        "BoneMap",
    )
    _require_exact_file(
        sidecar_path,
        request.accepted_import_sidecar_policy.sha256,
        request.accepted_import_sidecar_policy.size_bytes,
        "sidecar policy",
    )
    if archive_path.suffix.casefold() != ".zip" or archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise FoundryError("Clean-body authority must be one bounded ZIP archive.")

    members = request.package_policy.exact_ordered_members
    with zipfile.ZipFile(archive_path) as archive:
        infos = _verify_archive(archive, members)

    asset_root = repository.asset_directory(asset_id)
    source_root = asset_root / "source"
    source_root.mkdir(parents=True, exist_ok=True)
    destination = source_root / "clean_meshy_body_package_001"
    if destination.exists():
        raise FoundryError("Clean-body intake destination already exists.")
    operation = Path(tempfile.mkdtemp(prefix=".clean-body-intake-", dir=source_root))
    try:
        apply_candidate_acl(config, operation)
        copied_archive = operation / "provider.zip"
        _copy_new(archive_path, copied_archive)
        _require_exact_file(
            copied_archive, request.archive.sha256, request.archive.size_bytes, "copied archive"
        )
        by_role = dict(zip((member.role for member in members), infos, strict=True))
        with zipfile.ZipFile(copied_archive) as archive:
            _extract_new(archive, by_role["body"], operation / "body.fbx")
            _extract_new(archive, by_role["albedo"], operation / "albedo.png")
        body = next(member for member in members if member.role == "body")
        albedo = next(member for member in members if member.role == "albedo")
        _require_exact_file(operation / "body.fbx", body.sha256, body.size_bytes, "body")
        _require_exact_file(operation / "albedo.png", albedo.sha256, albedo.size_bytes, "albedo")
        report = {
            "schema_version": "vandrel_foundry_clean_meshy_body_intake_report/1.0",
            "asset_id": asset_id,
            "archive": {"sha256": request.archive.sha256, "size_bytes": request.archive.size_bytes, "custody": "sole_root"},
            "ordered_members": [
                item.model_dump(mode="json")
                | {"output_disposition": "derived" if item.role in {"body", "albedo"} else "forbidden"}
                for item in members
            ],
            "selected_body_sha256": request.selected_body_sha256,
            "selected_albedo_sha256": request.selected_albedo_sha256,
            "accepted_bone_map": {"sha256": request.accepted_bone_map.sha256, "size_bytes": request.accepted_bone_map.size_bytes, "custody": "policy_evidence_only", "copied": False},
            "accepted_import_sidecar_policy": {"sha256": request.accepted_import_sidecar_policy.sha256, "size_bytes": request.accepted_import_sidecar_policy.size_bytes, "custody": "policy_evidence_only", "copied": False},
            "package_policy_sha256": request.package_policy_sha256,
            "forbidden_output_sha256s": request.package_policy.forbidden_output_sha256s,
            "forbidden_route_ids": request.package_policy.forbidden_route_ids,
            "embedded_animations": "forbidden",
        }
        _write_new(operation / "intake-report.json", report)
        os.replace(operation, destination)
    except BaseException:
        if operation.exists():
            shutil.rmtree(operation)
        raise

    archive_artifact = _artifact(
        destination,
        "clean_meshy_body_archive_root_001",
        "clean_meshy_body_archive",
        "zip",
        "provider.zip",
        [],
    )
    body_artifact = _artifact(
        destination,
        "clean_meshy_body_fbx_derived_001",
        "clean_meshy_body_fbx",
        "fbx",
        "body.fbx",
        [archive_artifact.artifact_id],
    )
    albedo_artifact = _artifact(
        destination,
        "clean_meshy_body_albedo_derived_001",
        "clean_meshy_body_albedo",
        "png",
        "albedo.png",
        [archive_artifact.artifact_id],
    )
    report_artifact = _artifact(
        destination,
        "clean_meshy_body_intake_report_001",
        "clean_meshy_body_intake_report",
        "json",
        "intake-report.json",
        [archive_artifact.artifact_id],
    )
    targets = [archive_artifact, body_artifact, albedo_artifact, report_artifact]
    _verify_artifacts(asset_root, targets)
    revision = manifest.revision
    manifest.artifacts.extend(targets)
    manifest.input.kind = "external"
    manifest.vandrel_technical["clean_meshy_body_intake"] = {
        "package_policy_sha256": request.package_policy_sha256,
        "archive_sha256": request.archive.sha256,
        "body_sha256": request.selected_body_sha256,
        "albedo_sha256": request.selected_albedo_sha256,
        "bone_map_sha256": request.accepted_bone_map.sha256,
        "sidecar_policy_sha256": request.accepted_import_sidecar_policy.sha256,
    }
    transition_workflow(manifest, WorkflowState.DOWNLOADED)
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    try:
        repository.save(manifest, "source.clean_meshy_body_package_added", expected_revision=revision)
    except BaseException:
        live = repository.load(asset_id)
        if live.revision == manifest.revision and _references(live.artifacts, targets):
            _verify_artifacts(asset_root, targets)
            return targets
        if live.revision == revision and not _references(live.artifacts, targets):
            shutil.rmtree(destination)
        raise
    _verify_artifacts(asset_root, targets)
    return targets


def _load_request(path: Path) -> CleanMeshyBodyIntakeRequest:
    try:
        return CleanMeshyBodyIntakeRequest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        raise FoundryError(f"Invalid clean-body intake request: {exc}") from exc


def _resolve_input(request_path: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else request_path.parent / path


def _verify_archive(archive: zipfile.ZipFile, expected: list) -> list[zipfile.ZipInfo]:
    infos = [item for item in archive.infolist() if not item.is_dir()]
    if [item.filename.replace("\\", "/") for item in infos] != [
        item.archive_member for item in expected
    ]:
        raise FoundryError("Clean-body ZIP does not have the exact ordered inventory.")
    for info, member in zip(infos, expected, strict=True):
        _validate_member(info)
        if info.file_size != member.size_bytes or _hash_archive_member(archive, info) != member.sha256:
            raise FoundryError(f"Clean-body ZIP member bytes differ: {member.archive_member}")
    return infos


def _validate_member(info: zipfile.ZipInfo) -> None:
    path = PurePosixPath(info.filename.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.name or info.flag_bits & 0x1:
        raise FoundryError("Clean-body ZIP contains an unsafe or encrypted member.")
    mode = info.external_attr >> 16
    if mode and stat.S_ISLNK(mode):
        raise FoundryError("Clean-body ZIP may not contain symbolic links.")
    if info.file_size < 1 or info.file_size > MAX_MEMBER_BYTES:
        raise FoundryError("Clean-body ZIP member exceeds bounded size policy.")
    if info.compress_size == 0 or info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
        raise FoundryError("Clean-body ZIP member exceeds compression-ratio policy.")


def _artifact(
    root: Path,
    artifact_id: str,
    role: str,
    fmt: str,
    filename: str,
    derived_from: list[str],
) -> Artifact:
    digest, size = _hash_file(root / filename)
    return Artifact(
        artifact_id=artifact_id,
        role=role,
        stage="source",
        format=fmt,
        path=RelativeManifestPath(f"source/clean_meshy_body_package_001/{filename}"),
        sha256=digest,
        size_bytes=size,
        derived_from=derived_from,
        processor=PROCESSOR,
    )


def _extract_new(archive: zipfile.ZipFile, info: zipfile.ZipInfo, destination: Path) -> None:
    with archive.open(info) as source, destination.open("xb") as target:
        shutil.copyfileobj(source, target, length=1024 * 1024)
        target.flush()
        os.fsync(target.fileno())
    if destination.stat().st_size != info.file_size:
        raise FoundryError(f"Extracted clean-body member is truncated: {info.filename}")


def _copy_new(source: Path, destination: Path) -> None:
    with source.open("rb") as input_stream, destination.open("xb") as output_stream:
        shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
        output_stream.flush()
        os.fsync(output_stream.fileno())


def _write_new(path: Path, value: object) -> None:
    payload = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _require_exact_file(path: Path, sha256: str, size: int, label: str) -> None:
    if not path.is_file() or _hash_file(path) != (sha256, size):
        raise FoundryError(f"Clean-body {label} does not match exact request bytes.")


def _hash_archive_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    digest = hashlib.sha256()
    with archive.open(info) as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _verify_artifacts(asset_root: Path, artifacts: list[Artifact]) -> None:
    for artifact in artifacts:
        path = contained_path(asset_root, artifact.path)
        if _hash_file(path) != (artifact.sha256, artifact.size_bytes):
            raise FoundryError(f"Clean-body artifact changed: {artifact.artifact_id}")


def _references(live: list[Artifact], targets: list[Artifact]) -> bool:
    expected = {(item.artifact_id, item.sha256, item.size_bytes) for item in targets}
    actual = {(item.artifact_id, item.sha256, item.size_bytes) for item in live}
    return expected.issubset(actual)
