import hashlib
import importlib
import json
import re
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from vandrel_foundry.domain.batch import BatchLedger, BatchPlan
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.services.audit_asset import audit_asset
from vandrel_foundry.services.run_static_batch import _execute_stage, run_static_batch
from vandrel_foundry.services.validate_godot import ProcessResult
from vandrel_foundry.storage.manifests import ManifestRepository


def _write_glb(path: Path) -> None:
    document = {
        "asset": {"version": "2.0"},
        "accessors": [{"count": 3}],
        "meshes": [{"primitives": [{"indices": 0}]}],
    }
    payload = json.dumps(document, separators=(",", ":")).encode()
    payload += b" " * (-len(payload) % 4)
    path.write_bytes(
        struct.pack("<4sII", b"glTF", 2, 20 + len(payload))
        + struct.pack("<II", len(payload), 0x4E4F534A)
        + payload
    )


def test_validate_godot_stage_uses_process_result_contract(monkeypatch) -> None:
    candidate = BatchPlan.model_validate(
        {
            "schema_version": 1,
            "candidates": [
                {
                    "asset_id": "batch_validation_contract",
                    "lane": "static_prop",
                    "stages": ["validate-godot"],
                }
            ],
        }
    ).candidates[0]
    monkeypatch.setattr(
        "vandrel_foundry.services.run_static_batch.validate_godot_sandbox",
        lambda *_: ProcessResult(0, "", "", False, False, 0.1),
    )

    assert _execute_stage(None, None, candidate, "validate-godot") == []


def test_tracked_torch_resume_ledger_is_redacted_and_schema_valid() -> None:
    ledger_path = (
        Path(__file__).parents[1]
        / "docs"
        / "reports"
        / "evidence"
        / "torch-metal"
        / "native-resume-ledger.json"
    )
    content = ledger_path.read_bytes()
    ledger = BatchLedger.model_validate_json(content)

    assert hashlib.sha256(content).hexdigest() == (
        "f40b5fa40611a4049f7e2f924c944a09ef569805945d221d33b7faa6bb7ac3bc"
    )
    assert ledger.completed_candidates == 1
    assert ledger.failed_candidates == 0
    assert len(ledger.records) == 9
    assert sum(record.result == "skipped" for record in ledger.records) == 8
    strings: list[str] = []

    def collect(value):
        if isinstance(value, str):
            strings.append(value)
        elif isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, dict):
            for item in value.values():
                collect(item)

    collect(json.loads(content))
    for value in strings:
        lowered = value.lower()
        assert not re.search(r"[a-z]:[\\/]", value, re.IGNORECASE)
        assert not value.startswith(("/", "\\\\", "//"))
        assert "c:\\dev" not in lowered
        assert "c:/dev" not in lowered
        assert "vandrelfoundryworkspace" not in lowered
        assert "outsideassets" not in lowered
        assert "http://" not in lowered and "https://" not in lowered
        assert "provider_task" not in lowered and "meshy" not in lowered
        assert not re.search(r"\b[^@\s]+@[^@\s]+\.[^@\s]+\b", value)


def test_batch_continues_after_unsafe_candidate_with_accurate_deltas(
    tmp_path: Path, config, lanes
) -> None:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("credit-free static test", encoding="utf-8")
    good_one = tmp_path / "good-one.glb"
    good_two = tmp_path / "good-two.glb"
    _write_glb(good_one)
    _write_glb(good_two)
    unsafe = tmp_path / "unsafe.glb"
    unsafe.write_bytes(b"not a GLB")
    stages = ["create", "add-source", "process", "inspect", "audit"]
    plan = BatchPlan.model_validate(
        {
            "schema_version": 1,
            "failure_policy": "continue",
            "rerun_policy": "resume",
            "candidates": [
                {
                    "asset_id": "batch_good_one",
                    "lane": "static_prop",
                    "display_name": "Good One",
                    "prompt_file": prompt,
                    "source": good_one,
                    "stages": stages,
                },
                {
                    "asset_id": "batch_unsafe",
                    "lane": "static_prop",
                    "display_name": "Unsafe",
                    "prompt_file": prompt,
                    "source": unsafe,
                    "stages": stages,
                },
                {
                    "asset_id": "batch_good_two",
                    "lane": "static_prop",
                    "display_name": "Good Two",
                    "prompt_file": prompt,
                    "source": good_two,
                    "stages": stages,
                },
            ],
        }
    )
    ledger_path = tmp_path / "ledger.json"

    ledger = run_static_batch(config, lanes, plan, ledger_path)

    assert ledger.completed_candidates == 2
    assert ledger.failed_candidates == 1
    assert ledger_path.is_file()
    records = {(item.candidate, item.stage): item for item in ledger.records}
    assert records[("batch_unsafe", "add-source")].result == "failed"
    assert records[("batch_unsafe", "add-source")].artifact_count_delta == 0
    assert records[("batch_unsafe", "add-source")].manifest_revision_after == 1
    for asset_id in ("batch_good_one", "batch_good_two"):
        assert records[(asset_id, "add-source")].artifact_count_delta == 1
        assert records[(asset_id, "add-source")].artifact_bytes_delta == good_one.stat().st_size
        assert records[(asset_id, "process")].artifact_count_delta == 1
        assert records[(asset_id, "inspect")].artifact_count_delta == 0
        assert records[(asset_id, "audit")].result == "completed"
        assert ManifestRepository(config.foundry.workspace_root).load(asset_id).revision == 4
    assert not config.foundry.asset_library_root.exists()
    assert not config.vandrel.reference_repo_root.exists()


def test_unwritable_ledger_fails_before_candidate_mutation(
    tmp_path: Path, config, lanes, monkeypatch
) -> None:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("ledger preflight", encoding="utf-8")
    ledger_path = tmp_path / "denied" / "ledger.json"
    plan = BatchPlan.model_validate(
        {
            "schema_version": 1,
            "candidates": [
                {
                    "asset_id": "batch_ledger_denied",
                    "lane": "static_prop",
                    "display_name": "Ledger Denied",
                    "prompt_file": prompt,
                    "stages": ["create"],
                }
            ],
        }
    )
    original_open = Path.open

    def deny_ledger_open(path: Path, *args, **kwargs):
        if path == ledger_path:
            raise PermissionError("ledger destination denied")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny_ledger_open)

    with pytest.raises(FoundryError, match="Could not reserve batch ledger"):
        run_static_batch(config, lanes, plan, ledger_path)

    assert not (config.foundry.workspace_root / "assets" / "batch_ledger_denied").exists()


def test_existing_ledger_is_preserved_before_candidate_mutation(
    tmp_path: Path, config, lanes
) -> None:
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text("user evidence", encoding="utf-8")
    plan = BatchPlan.model_validate(
        {
            "schema_version": 1,
            "candidates": [
                {
                    "asset_id": "batch_existing_ledger",
                    "lane": "static_prop",
                    "display_name": "Existing Ledger",
                    "prompt_file": tmp_path / "prompt.txt",
                    "stages": ["create"],
                }
            ],
        }
    )

    with pytest.raises(FoundryError, match="Could not reserve batch ledger"):
        run_static_batch(config, lanes, plan, ledger_path)

    assert ledger_path.read_text(encoding="utf-8") == "user evidence"
    assert not (config.foundry.workspace_root / "assets" / "batch_existing_ledger").exists()


@pytest.mark.parametrize("failure_point", ["late_write", "fsync"])
def test_late_ledger_failure_removes_reservation_and_preserves_honest_candidate(
    failure_point: str, tmp_path: Path, config, lanes, monkeypatch
) -> None:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("late ledger failure", encoding="utf-8")
    ledger_path = tmp_path / f"{failure_point}.json"
    plan = BatchPlan.model_validate(
        {
            "schema_version": 1,
            "candidates": [
                {
                    "asset_id": f"batch_{failure_point}_failure",
                    "lane": "static_prop",
                    "display_name": "Late Ledger Failure",
                    "prompt_file": prompt,
                    "stages": ["create"],
                }
            ],
        }
    )
    original_open = Path.open

    class FailingLedgerStream:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def write(self, value):
            result = self.wrapped.write(value)
            if failure_point == "late_write" and value == "\n":
                raise OSError("injected late ledger write failure")
            return result

        def flush(self):
            return self.wrapped.flush()

        def fileno(self):
            return self.wrapped.fileno()

        def close(self):
            return self.wrapped.close()

    def wrap_ledger_open(path: Path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        return FailingLedgerStream(stream) if path == ledger_path else stream

    monkeypatch.setattr(Path, "open", wrap_ledger_open)
    if failure_point == "fsync":
        batch_module = importlib.import_module("vandrel_foundry.services.run_static_batch")
        monkeypatch.setattr(
            batch_module,
            "os",
            SimpleNamespace(
                fsync=lambda _descriptor: (_ for _ in ()).throw(OSError("injected fsync failure"))
            ),
        )

    with pytest.raises(FoundryError, match="Could not write batch ledger"):
        run_static_batch(config, lanes, plan, ledger_path)

    asset_id = f"batch_{failure_point}_failure"
    manifest = ManifestRepository(config.foundry.workspace_root).load(asset_id)
    assert not ledger_path.exists()
    assert manifest.revision == 1
    assert manifest.workflow.state.value == "draft"
    assert not manifest.approval.approved
    assert manifest.release.release_revision is None
    assert audit_asset(config, asset_id).passed


@pytest.mark.parametrize("forbidden_stage", ["bind-custody", "approve", "release"])
def test_static_batch_rejects_governance_and_publication_stages(
    forbidden_stage: str,
) -> None:
    with pytest.raises(ValueError, match="Input should be"):
        BatchPlan.model_validate(
            {
                "schema_version": 1,
                "candidates": [
                    {
                        "asset_id": "batch_boundary_guard",
                        "lane": "static_prop",
                        "stages": [forbidden_stage],
                    }
                ],
            }
        )


def test_resume_skips_completed_immutable_stages(tmp_path: Path, config, lanes) -> None:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("rerun", encoding="utf-8")
    source = tmp_path / "source.glb"
    _write_glb(source)
    candidate = {
        "asset_id": "batch_resume_one",
        "lane": "static_prop",
        "display_name": "Resume One",
        "prompt_file": prompt,
        "source": source,
        "stages": ["create", "add-source", "process", "inspect"],
    }
    plan = BatchPlan.model_validate(
        {
            "schema_version": 1,
            "failure_policy": "continue",
            "rerun_policy": "resume",
            "candidates": [candidate],
        }
    )
    run_static_batch(config, lanes, plan, tmp_path / "first.json")

    rerun = run_static_batch(config, lanes, plan, tmp_path / "second.json")

    assert all(record.result == "skipped" for record in rerun.records)
    assert all(record.artifact_count_delta == 0 for record in rerun.records)
    assert ManifestRepository(config.foundry.workspace_root).load("batch_resume_one").revision == 4


def test_resume_does_not_treat_a_different_plan_source_as_complete(
    tmp_path: Path, config, lanes
) -> None:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("source binding", encoding="utf-8")
    original = tmp_path / "original.glb"
    changed = tmp_path / "changed.glb"
    _write_glb(original)
    _write_glb(changed)
    changed.write_bytes(changed.read_bytes() + b"changed")
    base = {
        "asset_id": "batch_source_binding",
        "lane": "static_prop",
        "display_name": "Source Binding",
        "prompt_file": prompt,
        "source": original,
        "stages": ["create", "add-source"],
    }
    run_static_batch(
        config,
        lanes,
        BatchPlan.model_validate({"schema_version": 1, "candidates": [base]}),
        tmp_path / "first.json",
    )
    base["source"] = changed

    ledger = run_static_batch(
        config,
        lanes,
        BatchPlan.model_validate({"schema_version": 1, "candidates": [base]}),
        tmp_path / "changed.json",
    )

    assert ledger.records[0].result == "skipped"
    assert ledger.records[1].result == "failed"
    assert "draft state" in str(ledger.records[1].detail)


def test_fail_rerun_policy_reports_completed_stage(tmp_path: Path, config, lanes) -> None:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("rerun fail", encoding="utf-8")
    candidate = {
        "asset_id": "batch_fail_rerun",
        "lane": "static_prop",
        "display_name": "Fail Rerun",
        "prompt_file": prompt,
        "stages": ["create"],
    }
    resume = BatchPlan.model_validate(
        {
            "schema_version": 1,
            "rerun_policy": "resume",
            "candidates": [candidate],
        }
    )
    run_static_batch(config, lanes, resume, tmp_path / "first.json")
    fail = BatchPlan.model_validate(
        {
            "schema_version": 1,
            "rerun_policy": "fail",
            "candidates": [candidate],
        }
    )

    ledger = run_static_batch(config, lanes, fail, tmp_path / "failed.json")

    assert ledger.failed_candidates == 1
    assert ledger.records[0].result == "failed"
    assert ledger.records[0].error_category == "FoundryError"


def test_stop_policy_lists_candidates_that_were_not_run(tmp_path: Path, config, lanes) -> None:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("stop policy", encoding="utf-8")
    unsafe = tmp_path / "unsafe.glb"
    unsafe.write_bytes(b"invalid")
    plan = BatchPlan.model_validate(
        {
            "schema_version": 1,
            "failure_policy": "stop",
            "candidates": [
                {
                    "asset_id": "batch_stop_bad",
                    "lane": "static_prop",
                    "display_name": "Stop Bad",
                    "prompt_file": prompt,
                    "source": unsafe,
                    "stages": ["create", "add-source"],
                },
                {
                    "asset_id": "batch_not_run",
                    "lane": "static_prop",
                    "display_name": "Not Run",
                    "prompt_file": prompt,
                    "stages": ["create"],
                },
            ],
        }
    )

    ledger = run_static_batch(config, lanes, plan, tmp_path / "stop.json")

    assert ledger.planned_candidates == 2
    assert ledger.not_run_candidates == ["batch_not_run"]
    assert not (config.foundry.workspace_root / "assets" / "batch_not_run").exists()


def test_foreground_coverage_is_recorded_and_flags_empty_canvas(
    tmp_path: Path, config, lanes, monkeypatch
) -> None:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("coverage", encoding="utf-8")
    source = tmp_path / "source.glb"
    _write_glb(source)
    base_plan = BatchPlan.model_validate(
        {
            "schema_version": 1,
            "candidates": [
                {
                    "asset_id": "batch_coverage_one",
                    "lane": "static_prop",
                    "display_name": "Coverage One",
                    "prompt_file": prompt,
                    "source": source,
                    "stages": ["create", "add-source", "process"],
                }
            ],
        }
    )
    run_static_batch(config, lanes, base_plan, tmp_path / "base.json")

    def fake_render(settings, asset_id):
        repository = ManifestRepository(settings.foundry.workspace_root)
        manifest = repository.load(asset_id)
        asset_root = settings.foundry.workspace_root / "assets" / asset_id
        artifacts = []
        from vandrel_foundry.domain.manifest import Artifact, Processor
        from vandrel_foundry.storage.paths import RelativeManifestPath

        for name in ("front", "right", "back", "left"):
            relative = RelativeManifestPath(f"preview/fake-{name}.png")
            path = asset_root / str(relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            image = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
            for x in range(45, 55):
                for y in range(45, 55):
                    image.putpixel((x, y), (255, 0, 0, 255))
            image.save(path)
            import hashlib

            content = path.read_bytes()
            artifacts.append(
                Artifact(
                    artifact_id=f"multi_angle_preview_001_{name}",
                    role="multi_angle_preview",
                    stage="review",
                    format="png",
                    path=relative,
                    sha256=hashlib.sha256(content).hexdigest(),
                    size_bytes=len(content),
                    derived_from=["processed_glb_001"],
                    processor=Processor(name="test", version="1"),
                )
            )
        manifest.artifacts.extend(artifacts)
        manifest.revision += 1
        repository.save(manifest, "test.multi_angle", expected_revision=manifest.revision - 1)
        return artifacts

    monkeypatch.setattr(
        "vandrel_foundry.services.run_static_batch.render_multi_angle_preview", fake_render
    )
    render_plan = BatchPlan.model_validate(
        {
            "schema_version": 1,
            "candidates": [
                {
                    "asset_id": "batch_coverage_one",
                    "lane": "static_prop",
                    "display_name": "Coverage One",
                    "prompt_file": prompt,
                    "stages": ["render-multi-angle-preview"],
                }
            ],
        }
    )

    ledger = run_static_batch(config, lanes, render_plan, tmp_path / "coverage.json")

    coverage = ledger.records[0].foreground_coverage
    assert len(coverage) == 4
    assert all(item.bounding_box_fraction == 0.01 for item in coverage)
    assert all(item.nonzero_alpha_pixel_fraction == 0.01 for item in coverage)
    assert all(item.excessive_empty_canvas for item in coverage)
