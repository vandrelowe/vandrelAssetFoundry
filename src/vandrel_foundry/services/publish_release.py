import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.lanes import LaneConfiguration
from vandrel_foundry.domain.manifest import AssetManifest, utc_now
from vandrel_foundry.domain.release_descriptor import format_release_revision
from vandrel_foundry.services.plan_release import ReleasePlan, plan_release
from vandrel_foundry.services.windows_acl_policy import apply_release_acl
from vandrel_foundry.storage.atomic import write_json_temp
from vandrel_foundry.storage.git_worktree import (
    GitRunner,
    changed_paths,
    run_git,
    verify_git_worktree,
    verify_lfs_path,
)
from vandrel_foundry.storage.locks import AssetLock
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import contained_path

CATALOG_PATH = "catalog.json"
STAGING_ROOT = ".foundry-staging"


@dataclass(frozen=True)
class PublicationResult:
    destination: Path
    release_revision: int
    recovered: bool


def publish_release(
    config: FoundryConfig,
    lanes: LaneConfiguration,
    asset_id: str,
    git_runner: GitRunner = run_git,
) -> PublicationResult:
    root = config.foundry.asset_library_root
    verify_git_worktree(root, git_runner)
    lock = root / ".git" / "foundry-publication.lock"
    with AssetLock(lock):
        repository = ManifestRepository(config.foundry.workspace_root)
        manifest = repository.load(asset_id)
        plan = plan_release(config, lanes, asset_id)
        recovery = _matching_uncataloged_release(root, plan)
        effective = recovery or plan
        allowed = _allowed_transaction_paths(effective)
        unrelated = changed_paths(root, git_runner) - allowed
        if unrelated:
            sample = ", ".join(sorted(unrelated)[:3])
            raise FoundryError(f"Asset-library worktree has unrelated changes: {sample}")
        for item in effective.descriptor["files"]:
            if Path(item["path"]).suffix.lower() in {".glb", ".gltf", ".fbx"}:
                relative = _release_relative_path(effective, item["path"])
                verify_lfs_path(root, relative, git_runner)
        recovered = recovery is not None
        if not recovered:
            _stage_and_promote(config, asset_id, effective)
        apply_release_acl(config, effective.destination)
        descriptor_hash = _sha256_file(effective.destination / "asset-release.json")
        _update_catalog(root, effective, descriptor_hash)
        _record_manifest_release(repository, manifest, effective.release_revision)
        return PublicationResult(
            destination=effective.destination,
            release_revision=effective.release_revision,
            recovered=recovered,
        )


def _stage_and_promote(config: FoundryConfig, asset_id: str, plan: ReleasePlan) -> None:
    staging_parent = config.foundry.asset_library_root / STAGING_ROOT
    staging_parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f"{asset_id}-r{plan.release_revision:03d}-",
            dir=staging_parent,
        )
    )
    source_root = config.foundry.workspace_root / "assets" / asset_id
    try:
        for item in plan.descriptor["files"]:
            source_artifact = next(
                artifact
                for artifact in ManifestRepository(config.foundry.workspace_root)
                .load(asset_id)
                .artifacts
                if artifact.artifact_id == item["source_artifact_id"]
            )
            source = contained_path(source_root, source_artifact.path)
            destination = contained_path(staging, item["path"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            _copy_new(source, destination)
            if _sha256_file(destination) != item["sha256"]:
                raise FoundryError(f"Staged release artifact changed: {item['path']}")
        descriptor_temp = write_json_temp(staging, plan.descriptor)
        os.replace(descriptor_temp, staging / "asset-release.json")
        plan.destination.parent.mkdir(parents=True, exist_ok=True)
        if plan.destination.exists():
            raise FoundryError(f"Release destination already exists: {plan.destination}")
        os.replace(staging, plan.destination)
    except BaseException:
        if staging.exists():
            # Retain non-empty staging as interruption evidence.
            pass
        raise


def _copy_new(source: Path, destination: Path) -> None:
    try:
        with source.open("rb") as input_stream, destination.open("xb") as output_stream:
            shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
            output_stream.flush()
            os.fsync(output_stream.fileno())
    except OSError as exc:
        raise FoundryError(f"Could not stage release artifact {destination.name}: {exc}") from exc


def _matching_uncataloged_release(root: Path, plan: ReleasePlan) -> ReleasePlan | None:
    asset_root = root / "assets" / plan.descriptor["asset_id"]
    if not asset_root.is_dir():
        return None
    expected = _descriptor_identity(plan.descriptor)
    matches: list[ReleasePlan] = []
    for path in asset_root.glob("r[0-9][0-9][0-9]"):
        descriptor_path = path / "asset-release.json"
        try:
            descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if _descriptor_identity(descriptor) == expected:
            matches.append(
                ReleasePlan(
                    release_revision=int(descriptor["release_revision"]),
                    destination=path,
                    descriptor=descriptor,
                )
            )
    if len(matches) > 1:
        raise FoundryError("Multiple matching recoverable releases require manual reconciliation.")
    return matches[0] if matches else None


def _descriptor_identity(descriptor: dict[str, Any]) -> tuple[Any, ...]:
    return (
        descriptor.get("schema_version"),
        descriptor.get("asset_id"),
        tuple(
            (item.get("role"), item.get("path"), item.get("sha256"), item.get("size_bytes"))
            for item in descriptor.get("files", [])
        ),
        descriptor.get("provenance", {}).get("approved_at"),
        descriptor.get("custody", {}).get("semantic_assertion_sha256"),
    )


def _update_catalog(root: Path, plan: ReleasePlan, descriptor_hash: str) -> None:
    path = root / CATALOG_PATH
    catalog = _load_catalog(path)
    assets = catalog.setdefault("assets", {})
    asset = assets.setdefault(plan.descriptor["asset_id"], {"releases": []})
    releases = asset["releases"]
    entry = {
        "revision": plan.release_revision,
        "path": _release_relative_path(plan, "asset-release.json"),
        "descriptor_sha256": descriptor_hash,
    }
    existing = [item for item in releases if item.get("revision") == plan.release_revision]
    if existing and existing != [entry]:
        raise FoundryError("Catalog release entry conflicts with immutable release.")
    if not existing:
        releases.append(entry)
        releases.sort(key=lambda item: item["revision"])
    asset["latest_revision"] = max(item["revision"] for item in releases)
    temporary = write_json_temp(root, catalog)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_catalog(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "assets": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FoundryError(f"Could not read asset-library catalog: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise FoundryError("Asset-library catalog has an unsupported schema.")
    if not isinstance(value.get("assets"), dict):
        raise FoundryError("Asset-library catalog assets must be an object.")
    return value


def _record_manifest_release(
    repository: ManifestRepository,
    manifest: AssetManifest,
    revision: int,
) -> None:
    manifest.release.released = True
    manifest.release.release_revision = revision
    manifest.release.released_at = utc_now()
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    try:
        repository.save(
            manifest,
            "asset.released",
            expected_revision=manifest.revision - 1,
        )
    except ValidationError as exc:
        raise FoundryError(f"Could not record release in Foundry manifest: {exc}") from exc


def _release_relative_path(plan: ReleasePlan, child: str) -> str:
    revision = format_release_revision(plan.release_revision)
    return f"assets/{plan.descriptor['asset_id']}/{revision}/{child}"


def _allowed_transaction_paths(plan: ReleasePlan) -> set[str]:
    revision = format_release_revision(plan.release_revision)
    prefix = f"assets/{plan.descriptor['asset_id']}/{revision}/"
    return {
        CATALOG_PATH,
        *(prefix + item["path"] for item in plan.descriptor["files"]),
        prefix + "asset-release.json",
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise FoundryError(f"Could not hash release file {path}: {exc}") from exc
    return digest.hexdigest()
