import hashlib
from pathlib import Path

import pytest

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.custody_assertion import semantic_assertion_sha256
from vandrel_foundry.domain.lanes import LaneConfiguration
from vandrel_foundry.domain.manifest import (
    Artifact,
    CustodyAssertion,
    CustodyLicenseEvidence,
    CustodySourceContribution,
    CustodySourceInput,
)


@pytest.fixture
def config_data(tmp_path: Path) -> dict:
    return {
        "schema_version": 1,
        "foundry": {
            "workspace_root": str(tmp_path / "workspace"),
            "asset_library_root": str(tmp_path / "library"),
            "default_provider": "meshy",
        },
        "vandrel": {
            "reference_repo_root": str(tmp_path / "vandrel"),
            "required_marker": "project.godot",
            "write_enabled": False,
        },
        "providers": {
            "meshy": {
                "api_base": "https://api.meshy.ai",
                "api_key_environment_variable": "MESHY_API_KEY",
            }
        },
        "release": {"default_dry_run": True, "allow_overwrite": False},
    }


@pytest.fixture
def config(config_data: dict) -> FoundryConfig:
    return FoundryConfig.model_validate(config_data)


@pytest.fixture
def lanes() -> LaneConfiguration:
    return LaneConfiguration.model_validate(
        {
            "lanes": {
                "static_prop": {
                    "wrapper_template": "static_prop",
                    "target_triangles": 2500,
                    "maximum_triangles": 5000,
                    "collision_policy": "manual",
                }
            }
        }
    )


@pytest.fixture
def humanoid_lanes() -> LaneConfiguration:
    return LaneConfiguration.model_validate(
        {
            "lanes": {
                "humanoid": {
                    "wrapper_template": "humanoid_candidate",
                    "collision_policy": "manual_review",
                    "requires_materials": True,
                    "requires_skeleton": True,
                    "release_enabled": True,
                }
            }
        }
    )


@pytest.fixture
def prompt(tmp_path: Path) -> Path:
    path = tmp_path / "prompt.txt"
    path.write_text("a rough stone knife", encoding="utf-8")
    return path


def write_config(path: Path, data: dict) -> None:
    foundry = data["foundry"]
    vandrel = data["vandrel"]
    meshy = data["providers"]["meshy"]
    release = data["release"]
    path.write_text(
        "\n".join(
            [
                "schema_version = 1",
                "[foundry]",
                f'workspace_root = "{Path(foundry["workspace_root"]).as_posix()}"',
                f'asset_library_root = "{Path(foundry["asset_library_root"]).as_posix()}"',
                f'default_provider = "{foundry["default_provider"]}"',
                "[vandrel]",
                f'reference_repo_root = "{Path(vandrel["reference_repo_root"]).as_posix()}"',
                f'required_marker = "{vandrel["required_marker"]}"',
                f"write_enabled = {str(vandrel['write_enabled']).lower()}",
                "[providers.meshy]",
                f'api_base = "{meshy["api_base"]}"',
                f'api_key_environment_variable = "{meshy["api_key_environment_variable"]}"',
                "[release]",
                f"default_dry_run = {str(release['default_dry_run']).lower()}",
                f"allow_overwrite = {str(release['allow_overwrite']).lower()}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def bind_documented_test_custody(manifest, asset_root: Path) -> None:
    """Attach a minimal, internally consistent custody assertion to a test candidate."""
    evidence = b"license fixture"
    (asset_root / "custody" / "evidence").mkdir(parents=True, exist_ok=True)
    (asset_root / "custody" / "evidence" / "license.txt").write_bytes(evidence)
    evidence_sha = hashlib.sha256(evidence).hexdigest()
    root_sources = [
        item
        for item in manifest.artifacts
        if item.stage == "source" and not item.derived_from
    ]
    if not root_sources:
        source = b"source fixture"
        (asset_root / "source").mkdir(exist_ok=True)
        (asset_root / "source" / "source.glb").write_bytes(source)
        source_artifact = Artifact(
            artifact_id="source-fixture-001",
            role="provider_source_model",
            stage="source",
            format="glb",
            path="source/source.glb",
            sha256=hashlib.sha256(source).hexdigest(),
            size_bytes=len(source),
        )
        manifest.artifacts.append(source_artifact)
        root_sources = [source_artifact]
    manifest.artifacts.append(
        Artifact(
            artifact_id="custody-evidence-001",
            role="custody_license_evidence",
            stage="custody",
            format="txt",
            path="custody/evidence/license.txt",
            sha256=evidence_sha,
            size_bytes=len(evidence),
        )
    )
    source_inputs = [
        CustodySourceInput(
            artifact_id=item.artifact_id,
            role=item.role,
            sha256=item.sha256,
            size_bytes=item.size_bytes,
        )
        for item in sorted(root_sources, key=lambda item: item.artifact_id)
    ]
    contribution = CustodySourceContribution(
        contribution_id="fixture-contribution",
        source_id="fixture-provider",
        package_id="fixture-package",
        package_root="fixture-package",
        source_inputs=source_inputs,
        rights_status="documented",
        license_evidence=[
            CustodyLicenseEvidence(
                binding_id="fixture-license",
                original_evidence_path="licenses/fixture.txt",
                evidence_sha256=evidence_sha,
                size_bytes=len(evidence),
                scope_root="fixture-package",
                rights_semantics="documented",
                candidate_evidence_artifact_id="custody-evidence-001",
            )
        ],
    )
    semantic_sha = semantic_assertion_sha256([contribution])
    manifest.custody = CustodyAssertion(
        schema_version="vandrel_foundry_candidate_custody/1.0",
        assessment_status="evaluated",
        source_contributions=[contribution],
        policy_schema_version="test-policy/1",
        policy_sha256="1" * 64,
        register_schema_version="test-register/1",
        register_sha256="2" * 64,
        evaluated_manifest_revision=manifest.revision,
        effective_rights_status="documented",
        semantic_assertion_sha256=semantic_sha,
    )
    manifest.approval.custody_assertion_sha256 = semantic_sha
    manifest.approval.custody_source_inputs = source_inputs
