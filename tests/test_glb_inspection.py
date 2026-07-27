import hashlib
import json
import struct
from pathlib import Path

import pytest

from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.add_source import add_external_glb
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.inspect_assets import initialize_workspace
from vandrel_foundry.services.inspect_glb import inspect_glb, inspect_processed_glb
from vandrel_foundry.storage.manifests import ManifestRepository


def _write_glb(path: Path, document: dict) -> None:
    payload = json.dumps(document, separators=(",", ":")).encode("utf-8")
    payload += b" " * (-len(payload) % 4)
    length = 12 + 8 + len(payload)
    path.write_bytes(
        struct.pack("<4sII", b"glTF", 2, length)
        + struct.pack("<II", len(payload), 0x4E4F534A)
        + payload
    )


def test_inspection_counts_indexed_triangles_and_materials(tmp_path: Path) -> None:
    path = tmp_path / "model.glb"
    _write_glb(
        path,
        {
            "asset": {"version": "2.0"},
            "accessors": [{"count": 12}],
            "meshes": [{"primitives": [{"indices": 0, "material": 0}]}],
            "materials": [{}],
            "textures": [{}, {}],
            "images": [{}],
        },
    )
    result = inspect_glb(path)
    assert result.triangle_count == 4
    assert result.mesh_count == 1
    assert result.primitive_count == 1
    assert result.material_count == 1
    assert result.texture_count == 2
    assert result.image_count == 1


@pytest.mark.parametrize(
    "content",
    [
        b"",
        struct.pack("<4sII", b"NOPE", 2, 12),
        struct.pack("<4sII", b"glTF", 1, 12),
        struct.pack("<4sII", b"glTF", 2, 999),
    ],
)
def test_inspection_rejects_invalid_glb(content: bytes, tmp_path: Path) -> None:
    path = tmp_path / "invalid.glb"
    path.write_bytes(content)
    with pytest.raises(FoundryError):
        inspect_glb(path)


def test_asset_inspection_persists_hash_bound_report(config, lanes, prompt: Path) -> None:
    initialize_workspace(config.foundry.workspace_root)
    manifest = create_asset(
        config,
        lanes,
        "stone_knife_001",
        "static_prop",
        "Stone Knife",
        prompt,
    )
    asset_root = config.foundry.workspace_root / "assets" / "stone_knife_001"
    relative = "processed/passthrough/processed_glb_001.glb"
    path = asset_root / relative
    path.parent.mkdir(parents=True)
    _write_glb(
        path,
        {
            "asset": {"version": "2.0"},
            "accessors": [{"count": 15}],
            "meshes": [{"primitives": [{"indices": 0}]}],
        },
    )
    content = path.read_bytes()
    manifest.artifacts.append(
        Artifact(
            artifact_id="processed_glb_001",
            role="processed_model",
            stage="processed",
            format="glb",
            path=relative,
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
        )
    )
    manifest.workflow.state = WorkflowState.PROCESSED
    manifest.revision += 1
    repository = ManifestRepository(config.foundry.workspace_root)
    repository.save(manifest, expected_revision=1)

    result = inspect_processed_glb(config, lanes, "stone_knife_001")
    saved = repository.load("stone_knife_001")
    report = json.loads(
        (asset_root / "reports" / "technical-inspection-001.json").read_text(encoding="utf-8")
    )
    assert result.triangle_count == 5
    assert saved.validation.result == "passed"
    assert saved.quality.observed["triangle_count"] == 5
    assert report["artifact_sha256"] == hashlib.sha256(content).hexdigest()


def test_external_glb_enters_downloaded_workflow_without_provider(
    config, lanes, prompt: Path, tmp_path: Path
) -> None:
    initialize_workspace(config.foundry.workspace_root)
    create_asset(
        config,
        lanes,
        "external_prop_001",
        "static_prop",
        "External Prop",
        prompt,
    )
    source = tmp_path / "external.glb"
    _write_glb(
        source,
        {
            "asset": {"version": "2.0"},
            "accessors": [{"count": 6}],
            "meshes": [{"primitives": [{"indices": 0}]}],
        },
    )
    artifact = add_external_glb(config, "external_prop_001", source)
    manifest = ManifestRepository(config.foundry.workspace_root).load("external_prop_001")
    copied = config.foundry.workspace_root / "assets" / "external_prop_001" / str(artifact.path)
    assert manifest.input.kind == "external"
    assert manifest.workflow.state is WorkflowState.DOWNLOADED
    assert manifest.generation.tasks == []
    assert artifact.processor is not None
    assert artifact.processor.name == "external_glb_import"
    assert copied.read_bytes() == source.read_bytes()
    assert copied.stat().st_ino != source.stat().st_ino
