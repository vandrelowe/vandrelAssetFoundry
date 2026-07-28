import hashlib
import json
from typing import Any

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.lanes import LaneConfiguration
from vandrel_foundry.domain.manifest import Artifact, AssetManifest
from vandrel_foundry.domain.release_fitness import (
    ApprovalView,
    ArtifactIdentity,
    ConsumerResultView,
    ConsumerView,
    EligibilityView,
    IntegrityView,
    LibraryRevisionView,
    LibraryView,
    ReleaseFitnessView,
    TechnicalCheckView,
)
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.audit_asset import audit_asset
from vandrel_foundry.services.audit_library import audit_library_asset
from vandrel_foundry.services.plan_release import plan_release
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import contained_path

CONSUMER_ROLE = "vandrel_consumer_validation_report"
RELEASE_ROLE_TO_APPROVAL = {
    "model": "processed_model",
    "godot_wrapper_scene": "godot_wrapper_scene",
    "animation_walk": "processed_animation_walk",
    "animation_run": "processed_animation_run",
    "godot_animation_loader_script": "godot_animation_loader_script",
}


def inspect_release_fitness(
    config: FoundryConfig, lanes: LaneConfiguration, asset_id: str
) -> ReleaseFitnessView:
    manifest = ManifestRepository(config.foundry.workspace_root).load(asset_id)
    source = _selected_source(manifest)
    processed = _current_processed(manifest, source)
    audit = audit_asset(config, asset_id)
    failed_audit = [item.artifact_id for item in audit.artifact_checks if not item.passed] + [
        str(item["name"]) for item in audit.manifest_checks if not bool(item.get("passed"))
    ]
    integrity = IntegrityView(
        status="passing" if audit.passed else "failed",
        artifact_checks=len(audit.artifact_checks),
        failed_checks=failed_audit,
    )
    technical = [
        _technical_check(check, processed)
        for check in manifest.validation.checks
        if not str(check.get("name", "")).startswith("vandrel_consumer_")
    ]
    approval = _approval_view(manifest)
    library = _library_view(config, manifest)
    consumer = _consumer_view(config, manifest, processed)
    blockers: list[str] = []
    proposed_revision = None
    try:
        plan = plan_release(config, lanes, asset_id)
        proposed_revision = plan.release_revision
    except FoundryError as exc:
        blockers.append(str(exc))
    if not audit.passed:
        blockers.append("Candidate integrity audit failed.")
    return ReleaseFitnessView(
        asset_id=asset_id,
        display_name=manifest.asset.display_name,
        lane=manifest.asset.lane,
        manifest_revision=manifest.revision,
        workflow_state=manifest.workflow.state.value,
        selected_source=_identity(source),
        current_processed=_identity(processed),
        integrity=integrity,
        technical_validation_result=manifest.validation.result,
        technical_checks=technical,
        approval=approval,
        library=library,
        vandrel_consumer=consumer,
        release_eligibility=EligibilityView(
            eligible=not blockers,
            blockers=blockers,
            proposed_revision=proposed_revision,
        ),
    )


def _selected_source(manifest: AssetManifest) -> Artifact | None:
    selected = manifest.generation.selected_task_key
    values = [
        item
        for item in manifest.artifacts
        if item.role == "source_model" and (selected is None or item.source_task_key == selected)
    ]
    return values[-1] if values else None


def _current_processed(manifest: AssetManifest, source: Artifact | None) -> Artifact | None:
    values = [item for item in manifest.artifacts if item.role == "processed_model"]
    if source is not None:
        derived = [item for item in values if source.artifact_id in item.derived_from]
        return derived[-1] if derived else None
    return values[-1] if values else None


def _identity(artifact: Artifact | None) -> ArtifactIdentity | None:
    return (
        ArtifactIdentity(artifact_id=artifact.artifact_id, sha256=artifact.sha256)
        if artifact
        else None
    )


def _technical_check(check: dict[str, Any], processed: Artifact | None) -> TechnicalCheckView:
    passed = check.get("passed")
    status = "passing" if passed is True else "failed" if passed is False else "unknown"
    hashes = {
        key: value
        for key, value in check.items()
        if key.endswith("sha256") and isinstance(value, str)
    }
    model_hash = hashes.get("processed_model_sha256") or hashes.get("artifact_sha256")
    if model_hash is None:
        binding = "unbound"
    elif processed is None:
        binding = "stale"
    elif model_hash.lower() == processed.sha256:
        binding = "exact"
    else:
        binding = "stale"
    return TechnicalCheckView(
        name=str(check.get("name", "unknown")),
        status=status,
        binding_status=binding,
        bound_hashes=hashes,
        detail={
            key: value
            for key, value in check.items()
            if key not in {"name", "passed"} and not key.endswith("sha256")
        },
    )


def _approval_view(manifest: AssetManifest) -> ApprovalView:
    status = (
        "rejected"
        if manifest.workflow.state is WorkflowState.REJECTED
        else "approved"
        if manifest.approval.approved
        else "unapproved"
    )
    bindings = manifest.approval.approved_artifact_hashes
    if not bindings:
        matches = None
        binding_status = "unbound"
    else:
        current = {
            role: values[-1].sha256
            for role in bindings
            if (values := [item for item in manifest.artifacts if item.role == role])
        }
        matches = current == bindings
        binding_status = "exact" if matches else "stale"
    return ApprovalView(
        status=status,
        binding_status=binding_status,
        matches_current_artifact_set=matches,
        reviewer=manifest.approval.reviewer,
        approved_at=(
            manifest.approval.approved_at.isoformat() if manifest.approval.approved_at else None
        ),
        bound_hashes=bindings,
    )


def _library_view(config: FoundryConfig, manifest: AssetManifest) -> LibraryView:
    catalog_path = config.foundry.asset_library_root / "catalog.json"
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return LibraryView(
            status="absent",
            latest_revision=None,
            matches_current_approved_set=None,
            historical_releases=[],
        )
    except (OSError, json.JSONDecodeError):
        return LibraryView(
            status="unknown",
            latest_revision=None,
            matches_current_approved_set=None,
            historical_releases=[],
        )
    asset_entry = catalog.get("assets", {}).get(manifest.asset.asset_id)
    if not isinstance(asset_entry, dict) or not isinstance(asset_entry.get("releases"), list):
        return LibraryView(
            status="absent",
            latest_revision=None,
            matches_current_approved_set=None,
            historical_releases=[],
        )
    audit = audit_library_asset(config, manifest.asset.asset_id)
    checks = audit.checks if audit else ()
    releases = []
    for entry in asset_entry["releases"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("revision"), int):
            continue
        revision = entry["revision"]
        prefix = f"{manifest.asset.asset_id}:r{revision:03d}"
        relevant = [check for check in checks if check.subject.startswith(prefix)]
        integrity = (
            "unknown"
            if not relevant
            else "passing"
            if all(check.passed for check in relevant)
            else "failed"
        )
        releases.append(
            LibraryRevisionView(
                revision=revision,
                descriptor_sha256=str(entry.get("descriptor_sha256", "")),
                integrity_status=integrity,
            )
        )
    latest_number = asset_entry.get("latest_revision")
    latest = next(
        (item for item in releases if item.revision == latest_number),
        None,
    )
    matches = _latest_matches_approval(config, manifest, asset_entry, latest_number)
    status = (
        "historical_only"
        if not manifest.approval.approved
        else "current_set"
        if matches is True
        else "mismatched"
        if matches is False
        else "unknown"
    )
    return LibraryView(
        status=status,
        latest_revision=latest,
        matches_current_approved_set=matches,
        historical_releases=releases,
    )


def _latest_matches_approval(
    config: FoundryConfig,
    manifest: AssetManifest,
    asset_entry: dict[str, Any],
    latest_number: Any,
) -> bool | None:
    if not manifest.approval.approved:
        return None
    entry = next(
        (
            item
            for item in asset_entry.get("releases", [])
            if isinstance(item, dict) and item.get("revision") == latest_number
        ),
        None,
    )
    if entry is None or not isinstance(entry.get("path"), str):
        return None
    try:
        path = contained_path(config.foundry.asset_library_root, entry["path"])
        descriptor = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    files = descriptor.get("files") if isinstance(descriptor, dict) else None
    if not isinstance(files, list):
        return None
    released = {
        RELEASE_ROLE_TO_APPROVAL.get(str(item.get("role"))): item.get("sha256")
        for item in files
        if isinstance(item, dict)
        and RELEASE_ROLE_TO_APPROVAL.get(str(item.get("role"))) is not None
    }
    return released == manifest.approval.approved_artifact_hashes


def _consumer_view(
    config: FoundryConfig,
    manifest: AssetManifest,
    processed: Artifact | None,
) -> ConsumerView:
    asset_root = config.foundry.workspace_root / "assets" / manifest.asset.asset_id
    reports = [item for item in manifest.artifacts if item.role == CONSUMER_ROLE]
    valid: list[tuple[Artifact, dict[str, Any], str]] = []
    for artifact in reversed(reports):
        try:
            path = contained_path(asset_root, artifact.path)
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != artifact.sha256:
                continue
            data = json.loads(content)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        model = data.get("processed_model", {})
        bound_hash = model.get("sha256") if isinstance(model, dict) else None
        exact = _consumer_report_is_exact(manifest, processed, data)
        classification = "exact" if exact else "stale" if isinstance(bound_hash, str) else "unbound"
        valid.append((artifact, data, classification))
    if not valid:
        return ConsumerView(
            evidence_status="absent",
            consumer_status=None,
            acceptance_status="unknown",
            report_artifact_id=None,
            report_sha256=None,
            bound_model_sha256=None,
            latest_exact_current_result=None,
        )
    latest_artifact, latest_data, latest_classification = valid[0]
    exact_entry = next((entry for entry in valid if entry[2] == "exact"), None)
    consumer_status = latest_data.get("consumer_status")
    gate = latest_data.get("generic_gate_passed")
    acceptance = (
        "passing"
        if latest_classification == "exact" and consumer_status == "pass" and gate is True
        else "rejected"
        if latest_classification == "exact" and (consumer_status == "fail" or gate is False)
        else "blocked"
        if latest_classification == "exact" and consumer_status == "blocked"
        else "not_tested"
        if latest_classification == "exact" and consumer_status in {"not_tested", "in_progress"}
        else "unknown"
    )
    model = latest_data.get("processed_model", {})
    return ConsumerView(
        evidence_status=latest_classification,
        consumer_status=consumer_status if isinstance(consumer_status, str) else None,
        acceptance_status=acceptance,
        report_artifact_id=latest_artifact.artifact_id,
        report_sha256=latest_artifact.sha256,
        bound_model_sha256=(
            model.get("sha256")
            if isinstance(model, dict) and isinstance(model.get("sha256"), str)
            else None
        ),
        latest_exact_current_result=(
            _consumer_result(exact_entry[0], exact_entry[1]) if exact_entry is not None else None
        ),
    )


def _consumer_report_is_exact(
    manifest: AssetManifest,
    processed: Artifact | None,
    data: dict[str, Any],
) -> bool:
    if (
        processed is None
        or data.get("hash_bound") is not True
        or data.get("asset_id") != manifest.asset.asset_id
    ):
        return False
    model = data.get("processed_model")
    if not isinstance(model, dict) or (
        model.get("artifact_id") != processed.artifact_id
        or str(model.get("sha256", "")).lower() != processed.sha256
    ):
        return False
    evidence = data.get("asset_evidence")
    binding = evidence.get("foundry_binding") if isinstance(evidence, dict) else None
    if isinstance(binding, dict):
        if (
            binding.get("asset_id") != manifest.asset.asset_id
            or str(binding.get("model_sha256", "")).lower() != processed.sha256
        ):
            return False
        declared_model_id = binding.get("model_artifact_id")
        if declared_model_id is not None and declared_model_id != processed.artifact_id:
            return False
        for prefix, role in (
            ("walk", "processed_animation_walk"),
            ("run", "processed_animation_run"),
        ):
            declared_hash = binding.get(f"{prefix}_sha256")
            declared_id = binding.get(f"{prefix}_artifact_id")
            if declared_hash is None and declared_id is None:
                continue
            candidates = [item for item in manifest.artifacts if item.role == role]
            if not candidates:
                return False
            current = candidates[-1]
            if declared_id is not None and declared_id != current.artifact_id:
                return False
            if declared_hash is not None and str(declared_hash).lower() != current.sha256:
                return False
    return True


def _consumer_result(artifact: Artifact, data: dict[str, Any]) -> ConsumerResultView:
    status = str(data.get("consumer_status", "not_tested"))
    gate = data.get("generic_gate_passed")
    acceptance = (
        "passing"
        if status == "pass" and gate is True
        else "rejected"
        if status == "fail" or gate is False
        else "blocked"
        if status == "blocked"
        else "not_tested"
    )
    model = data["processed_model"]
    return ConsumerResultView(
        consumer_status=status,
        acceptance_status=acceptance,
        report_artifact_id=artifact.artifact_id,
        report_sha256=artifact.sha256,
        bound_model_sha256=str(model["sha256"]),
    )
