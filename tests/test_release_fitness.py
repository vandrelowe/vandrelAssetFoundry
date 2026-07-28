import hashlib
import json
from pathlib import Path

from typer.testing import CliRunner

from tests.conftest import write_config
from vandrel_foundry.cli import app
from vandrel_foundry.domain.manifest import Artifact, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.release_fitness import inspect_release_fitness
from vandrel_foundry.storage.manifests import ManifestRepository


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _candidate(config, lanes, prompt: Path, asset_id: str = "fitness_asset_001"):
    create_asset(config, lanes, asset_id, "static_prop", "Fitness Asset", prompt)
    root = config.foundry.workspace_root / "assets" / asset_id
    model = b"model"
    wrapper = b"wrapper"
    (root / "processed").mkdir(exist_ok=True)
    (root / "processed" / "model.glb").write_bytes(model)
    (root / "godot_staging").mkdir(exist_ok=True)
    (root / "godot_staging" / "wrapper.tscn").write_bytes(wrapper)
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    manifest.artifacts.extend(
        [
            Artifact(
                artifact_id="processed_model_001",
                role="processed_model",
                stage="processed",
                format="glb",
                path="processed/model.glb",
                sha256=_sha(model),
                size_bytes=len(model),
            ),
            Artifact(
                artifact_id="godot_wrapper_scene_001",
                role="godot_wrapper_scene",
                stage="validation",
                format="tscn",
                path="godot_staging/wrapper.tscn",
                sha256=_sha(wrapper),
                size_bytes=len(wrapper),
            ),
        ]
    )
    manifest.validation.result = "passed"
    manifest.validation.checks = [
        {
            "name": name,
            "passed": True,
            "processed_model_sha256": _sha(model),
        }
        for name in (
            "glb_structure",
            "geometry_present",
            "triangle_budget",
            "materials_required",
            "skeleton_required",
            "godot_sandbox_import",
        )
    ]
    manifest.workflow.state = WorkflowState.REVIEW
    manifest.revision += 1
    repository.save(manifest, "test.review", expected_revision=manifest.revision - 1)
    return repository, model, wrapper


def _approve(repository, asset_id: str, model: bytes, wrapper: bytes) -> None:
    manifest = repository.load(asset_id)
    manifest.workflow.state = WorkflowState.APPROVED
    manifest.approval.approved = True
    manifest.approval.approved_at = utc_now()
    manifest.approval.reviewer = "Reviewer"
    manifest.approval.approved_artifact_hashes = {
        "processed_model": _sha(model),
        "godot_wrapper_scene": _sha(wrapper),
    }
    manifest.revision += 1
    repository.save(manifest, "test.approved", expected_revision=manifest.revision - 1)


def _library(config, asset_id: str, model: bytes, wrapper: bytes, *, revision: int = 1):
    root = config.foundry.asset_library_root
    release = root / "assets" / asset_id / f"r{revision:03d}"
    release.mkdir(parents=True)
    (release / "model.glb").write_bytes(model)
    (release / "wrapper.tscn").write_bytes(wrapper)
    descriptor = {
        "schema_version": 1,
        "asset_id": asset_id,
        "release_revision": revision,
        "files": [
            {
                "role": "model",
                "path": "model.glb",
                "sha256": _sha(model),
                "size_bytes": len(model),
                "source_artifact_id": "processed_model_001",
            },
            {
                "role": "godot_wrapper_scene",
                "path": "wrapper.tscn",
                "sha256": _sha(wrapper),
                "size_bytes": len(wrapper),
                "source_artifact_id": "godot_wrapper_scene_001",
            },
        ],
    }
    descriptor_bytes = (json.dumps(descriptor, indent=2) + "\n").encode()
    (release / "asset-release.json").write_bytes(descriptor_bytes)
    catalog = {
        "schema_version": 1,
        "assets": {
            asset_id: {
                "latest_revision": revision,
                "releases": [
                    {
                        "revision": revision,
                        "path": (f"assets/{asset_id}/r{revision:03d}/asset-release.json"),
                        "descriptor_sha256": _sha(descriptor_bytes),
                    }
                ],
            }
        },
    }
    (root / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")


def _consumer(
    config,
    repository,
    asset_id: str,
    model_hash: str | None,
    status: str,
    gate: bool | None,
    *,
    hash_bound: bool = True,
) -> None:
    manifest = repository.load(asset_id)
    root = config.foundry.workspace_root / "assets" / asset_id
    number = (
        sum(item.role == "vandrel_consumer_validation_report" for item in manifest.artifacts) + 1
    )
    report = {
        "schema_version": 1,
        "asset_id": asset_id,
        "processed_model": (
            {"artifact_id": "processed_model_001", "sha256": model_hash}
            if model_hash is not None
            else {}
        ),
        "consumer_status": status,
        "hash_bound": hash_bound,
        "generic_gate_passed": gate,
    }
    content = (json.dumps(report) + "\n").encode()
    path = root / "reports" / f"consumer-{number:03d}.json"
    path.write_bytes(content)
    manifest.artifacts.append(
        Artifact(
            artifact_id=f"vandrel_consumer_validation_report_{number:03d}",
            role="vandrel_consumer_validation_report",
            stage="validation",
            format="json",
            path=f"reports/consumer-{number:03d}.json",
            sha256=_sha(content),
            size_bytes=len(content),
            derived_from=["processed_model_001"],
        )
    )
    manifest.revision += 1
    repository.save(manifest, "test.consumer", expected_revision=manifest.revision - 1)


def test_valid_review_candidate_is_unapproved_and_ineligible(config, lanes, prompt):
    _candidate(config, lanes, prompt)

    view = inspect_release_fitness(config, lanes, "fitness_asset_001")

    assert view.integrity.status == "passing"
    assert view.technical_validation_result == "passed"
    assert all(check.binding_status == "exact" for check in view.technical_checks)
    assert view.approval.status == "unapproved"
    assert not view.release_eligibility.eligible
    assert view.library.status == "absent"


def test_approved_unpublished_static_candidate_is_release_eligible(config, lanes, prompt):
    repository, model, wrapper = _candidate(config, lanes, prompt)
    _approve(repository, "fitness_asset_001", model, wrapper)

    view = inspect_release_fitness(config, lanes, "fitness_asset_001")

    assert view.approval.status == "approved"
    assert view.approval.binding_status == "exact"
    assert view.library.status == "absent"
    assert view.release_eligibility.eligible
    assert view.release_eligibility.proposed_revision == 1


def test_historical_release_does_not_match_current_approved_set(config, lanes, prompt):
    repository, model, wrapper = _candidate(config, lanes, prompt)
    _approve(repository, "fitness_asset_001", model, wrapper)
    _library(config, "fitness_asset_001", b"historical", wrapper)

    view = inspect_release_fitness(config, lanes, "fitness_asset_001")

    assert view.library.status == "mismatched"
    assert view.library.matches_current_approved_set is False
    assert view.library.historical_releases[0].revision == 1


def test_published_current_set_remains_separate_from_absent_consumer(config, lanes, prompt):
    repository, model, wrapper = _candidate(config, lanes, prompt)
    _approve(repository, "fitness_asset_001", model, wrapper)
    _library(config, "fitness_asset_001", model, wrapper)

    view = inspect_release_fitness(config, lanes, "fitness_asset_001")

    assert view.library.status == "current_set"
    assert view.vandrel_consumer.evidence_status == "absent"
    assert view.vandrel_consumer.acceptance_status == "unknown"


def test_exact_bound_consumer_rejection_is_not_inferred_as_release_state(config, lanes, prompt):
    repository, model, wrapper = _candidate(config, lanes, prompt)
    _approve(repository, "fitness_asset_001", model, wrapper)
    _consumer(
        config,
        repository,
        "fitness_asset_001",
        _sha(model),
        "fail",
        False,
    )

    view = inspect_release_fitness(config, lanes, "fitness_asset_001")

    assert view.vandrel_consumer.evidence_status == "exact"
    assert view.vandrel_consumer.acceptance_status == "rejected"
    assert view.vandrel_consumer.latest_exact_current_result is not None
    assert view.approval.status == "approved"


def test_stale_and_unbound_consumer_evidence_are_distinct(config, lanes, prompt):
    repository, _, _ = _candidate(config, lanes, prompt)
    _consumer(config, repository, "fitness_asset_001", "f" * 64, "pass", True)

    stale = inspect_release_fitness(config, lanes, "fitness_asset_001")

    assert stale.vandrel_consumer.evidence_status == "stale"
    assert stale.vandrel_consumer.acceptance_status == "unknown"
    other_id = "fitness_unbound_001"
    other_repository, _, _ = _candidate(config, lanes, prompt, other_id)
    _consumer(
        config,
        other_repository,
        other_id,
        None,
        "pass",
        None,
        hash_bound=False,
    )

    unbound = inspect_release_fitness(config, lanes, other_id)

    assert unbound.vandrel_consumer.evidence_status == "unbound"
    assert unbound.vandrel_consumer.acceptance_status == "unknown"


def test_newer_stale_consumer_report_does_not_hide_latest_exact_current_result(
    config, lanes, prompt
):
    repository, model, _ = _candidate(config, lanes, prompt)
    _consumer(config, repository, "fitness_asset_001", _sha(model), "pass", True)
    _consumer(config, repository, "fitness_asset_001", "f" * 64, "fail", False)

    view = inspect_release_fitness(config, lanes, "fitness_asset_001")

    assert view.vandrel_consumer.evidence_status == "stale"
    assert view.vandrel_consumer.acceptance_status == "unknown"
    exact = view.vandrel_consumer.latest_exact_current_result
    assert exact is not None
    assert exact.consumer_status == "pass"
    assert exact.report_artifact_id == "vandrel_consumer_validation_report_001"


def test_selected_source_without_derived_output_has_no_current_processed(config, lanes, prompt):
    repository, _, _ = _candidate(config, lanes, prompt)
    manifest = repository.load("fitness_asset_001")
    root = config.foundry.workspace_root / "assets" / "fitness_asset_001"
    source = b"new source"
    (root / "source" / "new.glb").write_bytes(source)
    manifest.artifacts.append(
        Artifact(
            artifact_id="source_glb_002",
            role="source_model",
            stage="source",
            format="glb",
            path="source/new.glb",
            sha256=_sha(source),
            size_bytes=len(source),
            source_task_key="new_source_task",
        )
    )
    manifest.generation.selected_task_key = "new_source_task"
    manifest.revision += 1
    repository.save(manifest, "test.new_source", expected_revision=manifest.revision - 1)

    view = inspect_release_fitness(config, lanes, "fitness_asset_001")

    assert view.selected_source is not None
    assert view.selected_source.artifact_id == "source_glb_002"
    assert view.current_processed is None
    assert all(check.binding_status == "stale" for check in view.technical_checks)


def test_exact_consumer_pass_and_current_release_are_visibly_separate(config, lanes, prompt):
    repository, model, wrapper = _candidate(config, lanes, prompt)
    _approve(repository, "fitness_asset_001", model, wrapper)
    _library(config, "fitness_asset_001", model, wrapper)
    _consumer(config, repository, "fitness_asset_001", _sha(model), "pass", True)

    view = inspect_release_fitness(config, lanes, "fitness_asset_001")

    assert view.release_eligibility.eligible
    assert view.library.status == "current_set"
    assert view.vandrel_consumer.acceptance_status == "passing"


def test_rejected_candidate_keeps_historical_release_separate(config, lanes, prompt):
    repository, model, wrapper = _candidate(config, lanes, prompt)
    _library(config, "fitness_asset_001", model, wrapper)
    manifest = repository.load("fitness_asset_001")
    manifest.workflow.state = WorkflowState.REJECTED
    manifest.approval.notes = "abandoned"
    manifest.revision += 1
    repository.save(manifest, "test.rejected", expected_revision=manifest.revision - 1)

    view = inspect_release_fitness(config, lanes, "fitness_asset_001")

    assert view.workflow_state == "rejected"
    assert view.approval.status == "rejected"
    assert view.library.status == "historical_only"
    assert not view.release_eligibility.eligible


def test_human_and_json_cli_views_agree(tmp_path, config_data, config, lanes, prompt):
    _candidate(config, lanes, prompt)
    config_path = tmp_path / "foundry.toml"
    write_config(config_path, config_data)
    runner = CliRunner()

    machine = runner.invoke(
        app,
        [
            "release-fitness",
            "fitness_asset_001",
            "--json",
            "--config",
            str(config_path),
        ],
    )
    human = runner.invoke(
        app,
        ["release-fitness", "fitness_asset_001", "--config", str(config_path)],
    )

    assert machine.exit_code == 0, machine.output
    assert human.exit_code == 0, human.output
    data = json.loads(machine.output)
    assert data["workflow_state"] == "review"
    assert data["approval"]["status"] == "unapproved"
    assert "Current workflow" in human.output and "review" in human.output
    assert "Human approval: unapproved" in human.output
