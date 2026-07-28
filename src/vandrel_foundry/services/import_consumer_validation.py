import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.consumer_validation import (
    CharacterGroundAudit,
    ConsumerAssetEvidence,
    VandrelCharacterAcceptanceLedger,
)
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path

MAX_LEDGER_BYTES = 4 * 1024 * 1024
PROCESSOR_NAME = "vandrel_consumer_validation_import"
PROCESSOR_VERSION = "1"
CONSUMER_CONTRACT = "vandrel_character_asset_acceptance/1.0"
CONSUMER_CONTRACT_REVISION = "vandrel@16cbf78d"
ALLOWED_STATES = {
    WorkflowState.PROCESSED,
    WorkflowState.REVIEW,
    WorkflowState.APPROVED,
    WorkflowState.BLOCKED,
    WorkflowState.REJECTED,
}


@dataclass(frozen=True)
class ConsumerValidationImport:
    report: Artifact
    hash_bound: bool
    generic_gate_passed: bool | None
    consumer_status: str


def import_vandrel_character_validation(
    config: FoundryConfig,
    asset_id: str,
    ledger_path: Path,
    consumer_asset_key: str,
    *,
    allow_unbound_diagnostic: bool = False,
    ground_audit_path: Path | None = None,
) -> ConsumerValidationImport:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.workflow.state not in ALLOWED_STATES:
        raise FoundryError("Consumer validation import requires a processed or reviewed candidate.")
    models = [item for item in manifest.artifacts if item.role == "processed_model"]
    if not models:
        raise FoundryError("Consumer validation import requires a processed model.")
    model = models[-1]
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    _verify_artifact(asset_root, model)

    ledger_bytes = _read_bounded(ledger_path)
    try:
        raw_ledger = json.loads(ledger_bytes)
        ledger = VandrelCharacterAcceptanceLedger.model_validate(raw_ledger)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise FoundryError(f"Vandrel consumer validation ledger is invalid: {exc}") from exc
    evidence = ledger.assets.get(consumer_asset_key)
    if evidence is None:
        raise FoundryError(
            f"Vandrel consumer validation asset key is unavailable: {consumer_asset_key}"
        )

    hash_bound = _binding_matches(evidence, asset_id, model.sha256)
    if not hash_bound and not allow_unbound_diagnostic:
        raise FoundryError(
            "Consumer validation is not bound to this Foundry asset and processed-model hash."
        )
    blocking_findings = [
        finding
        for finding in evidence.generic_asset_defects
        if finding.owner == "asset_foundry" and finding.severity in {"error", "blocker"}
    ]
    generic_gate_passed = not blocking_findings if hash_bound else None
    ground_audit_records: list[dict[str, object]] = []
    ground_audit_sha256: str | None = None
    if ground_audit_path is not None:
        audit_bytes = _read_bounded(ground_audit_path)
        try:
            audit = CharacterGroundAudit.model_validate_json(audit_bytes)
        except ValidationError as exc:
            raise FoundryError(f"Vandrel character grounding audit is invalid: {exc}") from exc
        character_ids = {evidence.character_id, *evidence.affected_character_ids}
        matching = [item for item in audit.characters if item.character_id in character_ids]
        if not matching:
            raise FoundryError(
                "Vandrel character grounding audit has no record for the selected asset."
            )
        ground_audit_records = [item.model_dump(mode="json") for item in matching]
        ground_audit_sha256 = hashlib.sha256(audit_bytes).hexdigest()

    number = (
        sum(item.role == "vandrel_consumer_validation_report" for item in manifest.artifacts) + 1
    )
    relative = RelativeManifestPath(f"reports/vandrel-consumer-validation-{number:03d}.json")
    path = contained_path(asset_root, relative)
    report = {
        "schema_version": 1,
        "asset_id": asset_id,
        "processed_model": {
            "artifact_id": model.artifact_id,
            "sha256": model.sha256,
        },
        "consumer_contract": CONSUMER_CONTRACT,
        "consumer_contract_revision": CONSUMER_CONTRACT_REVISION,
        "consumer_asset_key": consumer_asset_key,
        "consumer_status": evidence.status,
        "hash_bound": hash_bound,
        "generic_gate_passed": generic_gate_passed,
        "source_ledger_sha256": hashlib.sha256(ledger_bytes).hexdigest(),
        "source_ground_audit_sha256": ground_audit_sha256,
        "grounding_audit_records": ground_audit_records,
        "source_generated_utc": (
            ledger.generated_utc.isoformat() if ledger.generated_utc else None
        ),
        "imported_at": utc_now().isoformat(),
        "asset_evidence": evidence.model_dump(mode="json"),
        "authority": {
            "generic_asset_defects": "Foundry-owned only when exact-hash bound",
            "vandrel_runtime_corrections": "diagnostic consumer-owned evidence",
            "unbound_evidence": "diagnostic only",
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_new_json(path, report)
    digest, size = _hash_file(path)
    artifact = Artifact(
        artifact_id=f"vandrel_consumer_validation_report_{number:03d}",
        role="vandrel_consumer_validation_report",
        stage="validation",
        format="json",
        path=relative,
        sha256=digest,
        size_bytes=size,
        derived_from=[model.artifact_id],
        processor=Processor(name=PROCESSOR_NAME, version=PROCESSOR_VERSION),
    )
    manifest.artifacts.append(artifact)
    check_name = (
        "vandrel_consumer_generic_asset_gate"
        if hash_bound
        else "vandrel_consumer_unbound_diagnostic"
    )
    check = {
        "name": check_name,
        "passed": generic_gate_passed if hash_bound else True,
        "report": str(relative),
        "processed_model_sha256": model.sha256,
        "consumer_status": evidence.status,
        "hash_bound": hash_bound,
        "promotion_affecting": hash_bound,
    }
    manifest.validation.checks = [
        item for item in manifest.validation.checks if item.get("name") != check_name
    ]
    manifest.validation.checks.append(check)
    if hash_bound and not generic_gate_passed:
        manifest.validation.result = "failed"
        manifest.workflow.state = WorkflowState.BLOCKED
        manifest.workflow.blocked_reason = (
            "Vandrel consumer evidence reported exact-hash generic asset defects."
        )
        manifest.approval.approved = False
        manifest.approval.approved_at = None
        manifest.approval.approved_artifact_hashes = {}
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    repository.save(
        manifest,
        "asset.vandrel_consumer_validation_imported",
        expected_revision=manifest.revision - 1,
    )
    return ConsumerValidationImport(
        report=artifact,
        hash_bound=hash_bound,
        generic_gate_passed=generic_gate_passed,
        consumer_status=evidence.status,
    )


def _binding_matches(
    evidence: ConsumerAssetEvidence,
    asset_id: str,
    model_sha256: str,
) -> bool:
    binding = evidence.foundry_binding
    return bool(
        binding is not None
        and binding.asset_id == asset_id
        and binding.model_sha256.lower() == model_sha256
    )


def _read_bounded(path: Path) -> bytes:
    try:
        size = path.stat().st_size
        if size <= 0 or size > MAX_LEDGER_BYTES:
            raise FoundryError("Vandrel consumer validation ledger has an invalid size.")
        return path.read_bytes()
    except OSError as exc:
        raise FoundryError(f"Could not read Vandrel consumer validation ledger: {exc}") from exc


def _verify_artifact(asset_root: Path, artifact: Artifact) -> None:
    digest, size = _hash_file(contained_path(asset_root, artifact.path))
    if digest != artifact.sha256 or size != artifact.size_bytes:
        raise FoundryError(f"Processed model changed: {artifact.artifact_id}")


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _write_new_json(path: Path, value: dict[str, object]) -> None:
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise FoundryError(f"Could not write consumer validation evidence: {exc}") from exc
