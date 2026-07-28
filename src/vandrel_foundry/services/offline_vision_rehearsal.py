from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from vandrel_foundry.domain.errors import FoundryError

SCHEMA_VERSION = "vandrel_foundry_offline_vision_rehearsal/1.0"
REQUIRED_BLOCKERS = {
    "sealed_hash_locked_wheelhouse_missing",
    "accepted_dino_canonical_golden_missing",
    "accepted_sam_raw_mask_goldens_missing",
    "accepted_end_to_end_goldens_missing",
    "execution_not_implemented_or_authorized",
}


@dataclass(frozen=True)
class RehearsalReadiness:
    schema_version: str
    ready: bool
    blockers: tuple[str, ...]


def assess_offline_vision_rehearsal(
    manifest_path: Path,
    schema_path: Path,
    *,
    allow_network: bool = False,
    allow_writes: bool = False,
    execute: bool = False,
) -> RehearsalReadiness:
    """Validate an inert rehearsal manifest without performing rehearsal work."""
    if allow_network:
        raise FoundryError("Offline vision rehearsal forbids network access.")
    if allow_writes:
        raise FoundryError("Offline vision rehearsal validator forbids writes.")
    if execute:
        raise FoundryError("Offline vision rehearsal execution is not implemented or authorized.")

    manifest = _read_json(manifest_path, "rehearsal manifest")
    schema = _read_json(schema_path, "rehearsal schema")
    errors = sorted(
        Draft202012Validator(schema).iter_errors(manifest),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    if errors:
        detail = "; ".join(
            f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
            for error in errors
        )
        raise FoundryError(f"Offline vision rehearsal manifest is invalid: {detail}")

    blockers = _derived_blockers(manifest)
    declared = set(manifest["blockers"])
    if manifest["readiness"] == "ready" and (blockers or declared):
        raise FoundryError(
            "Offline vision rehearsal declares ready while fail-closed blockers remain."
        )
    if manifest["readiness"] == "blocked" and not declared:
        raise FoundryError("Blocked offline vision rehearsal must declare at least one blocker.")
    missing_declarations = blockers - declared
    if missing_declarations:
        raise FoundryError(
            "Offline vision rehearsal omits derived blockers: "
            + ", ".join(sorted(missing_declarations))
        )
    return RehearsalReadiness(
        schema_version=str(manifest["schema_version"]),
        ready=False,
        blockers=tuple(sorted(declared | blockers)),
    )


def _derived_blockers(manifest: dict[str, Any]) -> set[str]:
    blockers: set[str] = {"execution_not_implemented_or_authorized"}
    wheelhouse = manifest["wheelhouse"]
    if wheelhouse["status"] != "complete" or not wheelhouse["wheels"]:
        blockers.add("sealed_hash_locked_wheelhouse_missing")
    goldens = manifest["goldens"]
    if goldens["status"] != "accepted" or not goldens["dino_canonical_sha256"]:
        blockers.add("accepted_dino_canonical_golden_missing")
    if goldens["status"] != "accepted" or len(goldens["sam_raw_mask_sha256"]) != 4:
        blockers.add("accepted_sam_raw_mask_goldens_missing")
    if (
        goldens["status"] != "accepted"
        or not goldens["end_to_end_diagnostic_sha256"]
        or not goldens["end_to_end_mask_sha256"]
    ):
        blockers.add("accepted_end_to_end_goldens_missing")
    return blockers


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FoundryError(f"Unable to read {label}: {path}") from exc
    if not isinstance(value, dict):
        raise FoundryError(f"{label.capitalize()} must be a JSON object: {path}")
    return value
