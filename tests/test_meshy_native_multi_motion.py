import hashlib
import json
import zipfile
from pathlib import Path

import pytest

import vandrel_foundry.services.add_meshy_native_multi_motion_package as service
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.lanes import LaneConfiguration
from vandrel_foundry.domain.manifest import Artifact, Processor
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.storage.manifests import ManifestRepository

ACTION_NAMES = [
    service.LEGACY_UUID,
    "Angry",
    "Carry",
    "Collect",
    "Dead",
    "Female_Crouch_Pick_Fruit_Basket_Stand",
    "Female_Stand_Pick_Fruit_Basket",
    "Hit",
    "Idle_6",
    "Running",
    "Stand_To_Side_Lying",
    "Walking",
    *[f"Work_{index:02d}" for index in range(1, 9)],
]


def _lanes() -> LaneConfiguration:
    return LaneConfiguration.model_validate(
        {
            "lanes": {
                "humanoid": {
                    "wrapper_template": "humanoid_candidate",
                    "collision_policy": "manual_review",
                    "requires_materials": True,
                    "requires_skeleton": True,
                    "release_enabled": False,
                }
            }
        }
    )


def _archive(path: Path, names: list[str] | None = None) -> str:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, name in enumerate(names or ACTION_NAMES):
            archive.writestr(
                f"Meshy_AI_Primal_Female_Caveman_biped_Animation_{name}_withSkin.fbx",
                f"fbx-{index}-{name}".encode(),
            )
        archive.writestr("Meshy_AI_Primal_Female_Caveman_biped_texture.png", b"png")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _candidate(config, prompt: Path, tmp_path: Path):
    create_asset(config, _lanes(), "multi_motion_test_001", "humanoid", "Multi", prompt)
    repository = ManifestRepository(config.foundry.workspace_root)
    root = repository.asset_directory("multi_motion_test_001")
    source = root / "source" / "accepted"
    source.mkdir(parents=True)
    manifest = repository.load("multi_motion_test_001")
    processor = Processor(name="test_accepted_intake", version="1")
    roles = {
        "meshy_native_character_archive_root_001": ("meshy_native_character_archive", "zip"),
        "meshy_native_character_fbx_root_001": ("meshy_native_character_fbx", "fbx"),
        "meshy_native_walking_fbx_root_001": ("meshy_native_walking_fbx", "fbx"),
        "meshy_native_character_texture_root_001": ("meshy_native_character_texture", "png"),
        "meshy_native_motion_model_root_001": ("meshy_native_motion_model", "glb"),
        "meshy_native_motion_report_root_001": ("meshy_native_motion_report", "json"),
    }
    for index, (artifact_id, (role, format_name)) in enumerate(roles.items()):
        path = source / f"{index}.{format_name}"
        value = f"root-{artifact_id}".encode()
        path.write_bytes(value)
        manifest.artifacts.append(
            Artifact(
                artifact_id=artifact_id,
                role=role,
                stage="source",
                format=format_name,
                path=path.relative_to(root).as_posix(),
                sha256=hashlib.sha256(value).hexdigest(),
                size_bytes=len(value),
                processor=processor,
            )
        )
    manifest.workflow.state = WorkflowState.PROCESSED
    revision = manifest.revision
    manifest.revision += 1
    repository.save(manifest, expected_revision=revision)
    archive = tmp_path / "multi.zip"
    digest = _archive(archive)
    return repository, root, archive, digest


def test_intake_retains_exact_twenty_two_root_union_and_report(
    config, prompt, tmp_path
):
    repository, root, archive, digest = _candidate(config, prompt, tmp_path)
    artifacts = service.add_meshy_native_multi_motion_package(
        config, "multi_motion_test_001", archive, digest
    )
    assert {item.artifact_id for item in artifacts} == {
        service.REPORT_ID,
        *service.ROOT_IDS,
    }
    manifest = repository.load("multi_motion_test_001")
    new_roots = [
        item for item in manifest.artifacts if item.artifact_id in service.ROOT_IDS
    ]
    assert len(new_roots) == 22
    report = next(
        item for item in manifest.artifacts if item.artifact_id == service.REPORT_ID
    )
    assert set(report.derived_from) == set(service.ROOT_IDS)
    payload = json.loads((root / report.path).read_text(encoding="utf-8"))
    assert payload["animation_entry_count"] == 20
    assert payload["license_metadata"] == "not_inspected"
    assert sum(
        item["runtime_eligibility"] == "provenance_only_legacy_outlier"
        for item in payload["entries"]
    ) == 1
    assert manifest.approval.approved is False


def test_intake_appends_numbered_variable_package_and_retries_exactly(
    config, prompt, tmp_path
):
    repository, root, archive, digest = _candidate(config, prompt, tmp_path)
    first = service.add_meshy_native_multi_motion_package(
        config, "multi_motion_test_001", archive, digest
    )
    released = repository.load("multi_motion_test_001")
    released.workflow.state = WorkflowState.APPROVED
    released.approval.approved = True
    released.release.released = True
    released.release.release_revision = 1
    released_revision = released.revision
    released.revision += 1
    repository.save(released, expected_revision=released_revision)
    second_archive = tmp_path / "dark-sorceress.zip"
    second_digest = _archive(
        second_archive,
        ["Attack", "Sleep_Normally", "Walking"],
    )

    second = service.add_meshy_native_multi_motion_package(
        config,
        "multi_motion_test_001",
        second_archive,
        second_digest,
    )
    revision = repository.load("multi_motion_test_001").revision
    retry = service.add_meshy_native_multi_motion_package(
        config,
        "multi_motion_test_001",
        second_archive,
        second_digest,
    )

    identity = service.package_identity(2, 3)
    assert {item.artifact_id for item in second} == {
        identity.report_id,
        *identity.root_ids,
    }
    assert {
        item.artifact_id: item.model_dump() for item in retry
    } == {
        item.artifact_id: item.model_dump() for item in second
    }
    assert repository.load("multi_motion_test_001").revision == revision
    assert all((root / item.path).is_file() for item in [*first, *second])
    report = next(item for item in second if item.artifact_id == identity.report_id)
    payload = json.loads((root / report.path).read_text(encoding="utf-8"))
    assert payload["schema"] == "vandrel_foundry_meshy_native_multi_motion_intake/1.1"
    assert payload["package_number"] == 2
    assert payload["source_qualifier"] == second_digest[:8]
    assert payload["animation_entry_count"] == 3
    assert payload["license_metadata"] == "not_inspected"
    assert {item["exact_export_name"] for item in payload["entries"][:-1]} == {
        "Attack",
        "Sleep_Normally",
        "Walking",
    }
    assert repository.load("multi_motion_test_001").workflow.state is WorkflowState.PROCESSED
    assert repository.load("multi_motion_test_001").approval.approved is False


def test_intake_rejects_wrong_preexisting_root_union_before_copy(
    config, prompt, tmp_path
):
    repository, root, archive, digest = _candidate(config, prompt, tmp_path)
    manifest = repository.load("multi_motion_test_001")
    manifest.artifacts = [
        item
        for item in manifest.artifacts
        if item.artifact_id != "meshy_native_motion_report_root_001"
    ]
    revision = manifest.revision
    manifest.revision += 1
    repository.save(manifest, expected_revision=revision)
    with pytest.raises(FoundryError, match="exact accepted character roots"):
        service.add_meshy_native_multi_motion_package(
            config, "multi_motion_test_001", archive, digest
        )
    assert not (root / "source/meshy_native_multi_motion_package_001").exists()


def test_intake_rejects_archive_mutation_after_verified_copy(
    config, prompt, tmp_path, monkeypatch
):
    repository, root, archive, digest = _candidate(config, prompt, tmp_path)
    before = repository.load("multi_motion_test_001")
    original = service._inspect_archive

    def mutate(path):
        result = original(path)
        archive.write_bytes(archive.read_bytes() + b"changed")
        return result

    monkeypatch.setattr(service, "_inspect_archive", mutate)
    with pytest.raises(FoundryError, match="changed before promotion"):
        service.add_meshy_native_multi_motion_package(
            config, "multi_motion_test_001", archive, digest
        )
    assert repository.load("multi_motion_test_001").model_dump(mode="json") == (
        before.model_dump(mode="json")
    )
    assert not (root / "source/meshy_native_multi_motion_package_001").exists()


def test_intake_precommit_failure_rolls_back_promoted_package(
    config, prompt, tmp_path, monkeypatch
):
    repository, root, archive, digest = _candidate(config, prompt, tmp_path)
    before = repository.load("multi_motion_test_001")
    original = ManifestRepository.save

    def fail(self, manifest, event_type="manifest.updated", expected_revision=None):
        if event_type == "source.meshy_native_multi_motion_package_added":
            raise OSError("precommit")
        return original(self, manifest, event_type, expected_revision)

    monkeypatch.setattr(ManifestRepository, "save", fail)
    with pytest.raises(OSError, match="precommit"):
        service.add_meshy_native_multi_motion_package(
            config, "multi_motion_test_001", archive, digest
        )
    assert repository.load("multi_motion_test_001").model_dump(mode="json") == (
        before.model_dump(mode="json")
    )
    assert not (root / "source/meshy_native_multi_motion_package_001").exists()


def test_intake_post_promotion_verification_failure_rolls_back_package(
    config, prompt, tmp_path, monkeypatch
):
    repository, root, archive, digest = _candidate(config, prompt, tmp_path)
    before = repository.load("multi_motion_test_001")

    def fail(*_args):
        raise FoundryError("verification failure")

    monkeypatch.setattr(service, "_artifacts", fail)
    with pytest.raises(FoundryError, match="verification failure"):
        service.add_meshy_native_multi_motion_package(
            config, "multi_motion_test_001", archive, digest
        )
    assert repository.load("multi_motion_test_001").model_dump(mode="json") == (
        before.model_dump(mode="json")
    )
    assert not (root / "source/meshy_native_multi_motion_package_001").exists()


def test_intake_save_then_failure_preserves_exact_committed_package(
    config, prompt, tmp_path, monkeypatch
):
    repository, root, archive, digest = _candidate(config, prompt, tmp_path)
    original = ManifestRepository.save

    def save_then_fail(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise OSError("post replace")

    monkeypatch.setattr(ManifestRepository, "save", save_then_fail)
    artifacts = service.add_meshy_native_multi_motion_package(
        config, "multi_motion_test_001", archive, digest
    )
    live = repository.load("multi_motion_test_001")
    assert all(any(item.artifact_id == value.artifact_id for item in live.artifacts) for value in artifacts)
    assert all((root / value.path).is_file() for value in artifacts)


def test_intake_retry_rehashes_every_manifest_owned_byte(
    config, prompt, tmp_path
):
    _repository, root, archive, digest = _candidate(config, prompt, tmp_path)
    artifacts = service.add_meshy_native_multi_motion_package(
        config, "multi_motion_test_001", archive, digest
    )
    victim = next(item for item in artifacts if item.artifact_id == service.FBX_IDS[7])
    (root / victim.path).write_bytes(b"corrupt")
    with pytest.raises(FoundryError, match="byte changed"):
        service.add_meshy_native_multi_motion_package(
            config, "multi_motion_test_001", archive, digest
        )


@pytest.mark.parametrize(
    "names",
    [
        ACTION_NAMES[:-1],
        [*ACTION_NAMES[:-1], ACTION_NAMES[0]],
        [name for name in ACTION_NAMES if name != service.LEGACY_UUID] + ["Other"],
    ],
)
def test_intake_rejects_missing_duplicate_or_wrong_legacy_entries(
    config, prompt, tmp_path, names
):
    _repository, root, archive, _digest = _candidate(config, prompt, tmp_path)
    digest = _archive(archive, names)
    with pytest.raises(
        FoundryError, match="exact action names|exactly 21|unsafe entry"
    ):
        service.add_meshy_native_multi_motion_package(
            config, "multi_motion_test_001", archive, digest
        )
    assert not (root / "source/meshy_native_multi_motion_package_001").exists()
