import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vandrel_foundry.cli import app
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.services.offline_vision_rehearsal import (
    REQUIRED_BLOCKERS,
    assess_offline_vision_rehearsal,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "offline-vision-rehearsal.v1.json"
SCHEMA = ROOT / "schemas" / "offline-vision-rehearsal-v1.schema.json"
RUNNER = CliRunner()


def test_blocked_manifest_is_valid_and_fail_closed() -> None:
    result = assess_offline_vision_rehearsal(MANIFEST, SCHEMA)

    assert result.ready is False
    assert set(result.blockers) == REQUIRED_BLOCKERS


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"allow_network": True}, "forbids network"),
        ({"allow_writes": True}, "forbids writes"),
        ({"execute": True}, "not implemented or authorized"),
    ],
)
def test_unsafe_arguments_fail_before_manifest_read(
    tmp_path: Path, kwargs: dict[str, bool], message: str
) -> None:
    missing = tmp_path / "missing.json"

    with pytest.raises(FoundryError, match=message):
        assess_offline_vision_rehearsal(missing, missing, **kwargs)


def test_ready_claim_with_missing_inputs_fails_closed(tmp_path: Path) -> None:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    data["readiness"] = "ready"
    path = tmp_path / "premature-ready.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(FoundryError, match="declares ready"):
        assess_offline_vision_rehearsal(path, SCHEMA)


def test_missing_derived_blocker_fails_closed(tmp_path: Path) -> None:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    data["blockers"].remove("sealed_hash_locked_wheelhouse_missing")
    path = tmp_path / "omitted-blocker.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(FoundryError, match="omits derived blockers"):
        assess_offline_vision_rehearsal(path, SCHEMA)


def test_schema_rejects_nonportable_fixture_path(tmp_path: Path) -> None:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    data["fixtures"][0]["path"] = "../escape.png"
    path = tmp_path / "traversal.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(FoundryError, match="manifest is invalid"):
        assess_offline_vision_rehearsal(path, SCHEMA)


def test_cli_reports_blocked_and_exits_nonzero() -> None:
    result = RUNNER.invoke(
        app,
        [
            "offline-vision-rehearsal",
            "--manifest",
            str(MANIFEST),
            "--schema",
            str(SCHEMA),
        ],
    )

    assert result.exit_code == 1
    assert "Offline vision rehearsal: blocked" in result.output
    assert "sealed_hash_locked_wheelhouse_missing" in result.output


def test_cli_network_guard_precedes_missing_manifest(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    result = RUNNER.invoke(
        app,
        [
            "offline-vision-rehearsal",
            "--manifest",
            str(missing),
            "--schema",
            str(missing),
            "--allow-network",
        ],
    )

    assert result.exit_code == 1
    assert "forbids network access" in result.output
