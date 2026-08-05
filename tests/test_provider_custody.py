import hashlib
import json
from pathlib import Path

from vandrel_foundry.domain.custody_assertion import custody_freshness
from vandrel_foundry.domain.manifest import Artifact, ProviderTask
from vandrel_foundry.domain.provider import ProviderTaskStatus
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.provider_custody import bind_provider_custody
from vandrel_foundry.storage.manifests import ManifestRepository


def test_provider_custody_binds_task_sources_and_retained_rights_policy(
    config, lanes, prompt: Path, tmp_path: Path
) -> None:
    create_asset(config, lanes, "provider_rock_001", "static_prop", "Provider Rock", prompt)
    asset_root = config.foundry.workspace_root / "assets" / "provider_rock_001"
    source = b"provider glb"
    (asset_root / "source").mkdir(exist_ok=True)
    (asset_root / "source" / "model.glb").write_bytes(source)
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load("provider_rock_001")
    manifest.generation.tasks.append(
        ProviderTask(
            task_key="meshy_remesh_001",
            provider="meshy",
            operation="remesh",
            provider_task_id="provider-task-1",
            attempt=1,
            status=ProviderTaskStatus.SUCCEEDED,
            progress=100,
            request_fingerprint="a" * 64,
        )
    )
    manifest.generation.selected_task_key = "meshy_remesh_001"
    manifest.artifacts.append(
        Artifact(
            artifact_id="source_glb_001",
            role="source_model",
            stage="source",
            format="glb",
            path="source/model.glb",
            sha256=hashlib.sha256(source).hexdigest(),
            size_bytes=len(source),
            source_task_key="meshy_remesh_001",
        )
    )
    manifest.revision += 1
    repository.save(manifest, expected_revision=manifest.revision - 1)
    policy = tmp_path / "provider-policy.json"
    policy.write_text(
        json.dumps(
            {
                "schema_version": "vandrel_foundry_provider_rights_policy/1.0",
                "providers": {
                    "meshy": {
                        "rights_status": "documented",
                        "evidence_retrieved_at": "2026-08-02T00:00:00Z",
                        "evidence_urls": ["https://example.test/terms"],
                        "basis": "Paid API generation rights evidence.",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    assertion = bind_provider_custody(config, "provider_rock_001", policy)
    saved = repository.load("provider_rock_001")

    assert assertion.schema_version == "vandrel_foundry_candidate_custody/1.2"
    assert assertion.register_schema_version == "vandrel_foundry_provider_provenance/1.0"
    assert assertion.register_root_fingerprints is not None
    assert set(assertion.register_root_fingerprints) == {"foundry_workspace"}
    assert assertion.source_contributions[0].package_root.logical_root == "foundry_workspace"
    assert custody_freshness(saved) == (True, [])
    evidence = next(item for item in saved.artifacts if item.role == "custody_license_evidence")
    assert (asset_root / evidence.path).read_bytes() == policy.read_bytes()


def test_provider_custody_stales_when_selected_task_changes(
    config, lanes, prompt: Path, tmp_path: Path
) -> None:
    test_provider_custody_binds_task_sources_and_retained_rights_policy(
        config, lanes, prompt, tmp_path
    )
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load("provider_rock_001")
    manifest.generation.selected_task_key = None

    fresh, blockers = custody_freshness(manifest)

    assert not fresh
    assert "custody_provider_provenance_stale" in blockers
