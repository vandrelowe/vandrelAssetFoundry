import hashlib
import json
import struct
from pathlib import Path

import pytest

from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.add_source import (
    _gltf_sidecars,
    add_external_fbx,
    add_external_glb,
)
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.inspect_assets import initialize_workspace
from vandrel_foundry.services.inspect_glb import inspect_glb, inspect_processed_glb
from vandrel_foundry.services.process_blender import process_with_blender
from vandrel_foundry.services.render_preview import render_local_preview
from vandrel_foundry.services.validate_godot import ProcessResult
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
            "nodes": [{}, {}, {}],
            "skins": [{"joints": [0, 1, 2]}],
            "animations": [{}, {}],
        },
    )
    result = inspect_glb(path)
    assert result.triangle_count == 4
    assert result.mesh_count == 1
    assert result.primitive_count == 1
    assert result.material_count == 1
    assert result.texture_count == 2
    assert result.image_count == 1
    assert result.skin_count == 1
    assert result.joint_count == 3
    assert result.animation_count == 2


@pytest.mark.parametrize("joints", [[], [1], [-1], [True]])
def test_inspection_rejects_empty_or_invalid_skin_joints(
    joints: list[object], tmp_path: Path
) -> None:
    path = tmp_path / "invalid-skin.glb"
    _write_glb(
        path,
        {
            "asset": {"version": "2.0"},
            "nodes": [{}],
            "skins": [{"joints": joints}],
        },
    )
    if joints == []:
        assert inspect_glb(path).joint_count == 0
    else:
        with pytest.raises(FoundryError, match="valid node indices"):
            inspect_glb(path)


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
            "materials": [{}],
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
    assert next(check for check in saved.validation.checks if check["name"] == "geometry_present")[
        "passed"
    ]
    assert report["artifact_sha256"] == hashlib.sha256(content).hexdigest()

    saved.workflow.state = WorkflowState.REVIEW
    saved.validation.checks.append({"name": "godot_sandbox_import", "passed": True})
    saved.revision += 1
    repository.save(saved, "test.review", expected_revision=saved.revision - 1)
    inspect_processed_glb(config, lanes, "stone_knife_001")
    reinspected = repository.load("stone_knife_001")
    assert reinspected.workflow.state is WorkflowState.REVIEW
    assert any(
        check["name"] == "godot_sandbox_import" and check["passed"]
        for check in reinspected.validation.checks
    )


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

    executable = tmp_path / "blender.exe"
    executable.write_bytes(b"fixture executable")
    config.tools.blender_executable = executable

    def fake_runner(arguments, cwd, environment, timeout_seconds, maximum_output_bytes):
        input_path, output_path, report_path = map(Path, arguments[-3:])
        output_path.write_bytes(input_path.read_bytes())
        report_path.write_text(
            json.dumps({"blender_version": "fixture", "triangles": 2}),
            encoding="utf-8",
        )
        return ProcessResult(0, "", "", False, False, 0.1)

    processed = process_with_blender(
        config,
        "external_prop_001",
        runner=fake_runner,
    )
    updated = ManifestRepository(config.foundry.workspace_root).load("external_prop_001")
    assert updated.workflow.state is WorkflowState.PROCESSED
    assert processed.derived_from == [artifact.artifact_id]
    assert processed.processor is not None
    assert processed.processor.name == "blender_cleanup"
    assert any(item.role == "blender_processing_report" for item in updated.artifacts)

    def fake_preview_runner(arguments, cwd, environment, timeout_seconds, maximum_output_bytes):
        _, output_path, report_path = map(Path, arguments[-3:])
        output_path.write_bytes(b"\x89PNG\r\n\x1a\npreview")
        report_path.write_text(
            json.dumps({"blender_version": "fixture", "resolution": [512, 512]}),
            encoding="utf-8",
        )
        return ProcessResult(0, "", "", False, False, 0.1)

    preview = render_local_preview(config, "external_prop_001", runner=fake_preview_runner)
    preview_manifest = ManifestRepository(config.foundry.workspace_root).load("external_prop_001")
    assert preview.role == "local_preview"
    assert preview_manifest.workflow.state is WorkflowState.PROCESSED
    assert any(item.role == "local_preview_log" for item in preview_manifest.artifacts)

    def fake_decimate_runner(arguments, cwd, environment, timeout_seconds, maximum_output_bytes):
        input_path, output_path, report_path = map(Path, arguments[-4:-1])
        assert arguments[-1] == "3"
        output_path.write_bytes(input_path.read_bytes())
        report_path.write_text(
            json.dumps(
                {
                    "blender_version": "fixture",
                    "triangles_before": 5,
                    "triangles_after": 3,
                    "target_triangles": 3,
                }
            ),
            encoding="utf-8",
        )
        return ProcessResult(0, "", "", False, False, 0.1)

    decimated = process_with_blender(
        config,
        "external_prop_001",
        target_triangles=3,
        runner=fake_decimate_runner,
    )
    assert decimated.processor is not None
    assert decimated.processor.name == "blender_decimate"

    def fake_over_target_runner(arguments, cwd, environment, timeout_seconds, maximum_output_bytes):
        input_path, output_path, report_path = map(Path, arguments[-4:-1])
        output_path.write_bytes(input_path.read_bytes())
        report_path.write_text(
            json.dumps({"blender_version": "fixture", "target_triangles": 1}),
            encoding="utf-8",
        )
        return ProcessResult(0, "", "", False, False, 0.1)

    with pytest.raises(FoundryError, match="exceeds the requested triangle target"):
        process_with_blender(
            config,
            "external_prop_001",
            target_triangles=1,
            runner=fake_over_target_runner,
        )
    assert not (
        config.foundry.workspace_root
        / "assets/external_prop_001/processed/blender/processed_glb_003.glb"
    ).exists()

    repository = ManifestRepository(config.foundry.workspace_root)
    approved = repository.load("external_prop_001")
    approved.workflow.state = WorkflowState.APPROVED
    approved.approval.approved = True
    approved.approval.approved_artifact_hashes = {"processed_model": decimated.sha256}
    approved.revision += 1
    repository.save(approved, "test.approved", expected_revision=approved.revision - 1)

    render_local_preview(config, "external_prop_001", runner=fake_preview_runner)
    still_approved = repository.load("external_prop_001")
    assert still_approved.workflow.state is WorkflowState.APPROVED
    assert still_approved.approval.approved
    assert still_approved.approval.approved_artifact_hashes == {"processed_model": decimated.sha256}


def test_blender_processing_rejects_nonpositive_triangle_target(config) -> None:
    with pytest.raises(FoundryError, match="positive integer"):
        process_with_blender(config, "missing", target_triangles=0)


def test_external_fbx_package_preserves_source_texture_and_conversion_evidence(
    config, lanes, prompt: Path, tmp_path: Path
) -> None:
    initialize_workspace(config.foundry.workspace_root)
    create_asset(
        config,
        lanes,
        "external_fbx_001",
        "static_prop",
        "External FBX",
        prompt,
    )
    package = tmp_path / "package"
    package.mkdir()
    source = package / "Meshy Export.fbx"
    texture = package / "Meshy Export.png"
    source.write_bytes(b"fixture-fbx")
    texture.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    executable = tmp_path / "blender.exe"
    executable.write_bytes(b"fixture executable")
    config.tools.blender_executable = executable

    def fake_runner(arguments, cwd, environment, timeout_seconds, maximum_output_bytes):
        output_path = Path(arguments[-2])
        report_path = Path(arguments[-1])
        _write_glb(
            output_path,
            {
                "asset": {"version": "2.0"},
                "accessors": [{"count": 6}],
                "meshes": [{"primitives": [{"indices": 0}]}],
                "materials": [{}],
                "textures": [{}],
                "images": [{}],
            },
        )
        report_path.write_text(
            json.dumps({"blender_version": "fixture", "input_format": "fbx"}),
            encoding="utf-8",
        )
        return ProcessResult(0, "WARNING: conversion warning", "", False, False, 0.1)

    converted = add_external_fbx(
        config,
        "external_fbx_001",
        source,
        runner=fake_runner,
    )
    manifest = ManifestRepository(config.foundry.workspace_root).load("external_fbx_001")
    asset_root = config.foundry.workspace_root / "assets" / "external_fbx_001"
    roles = [item.role for item in manifest.artifacts]
    assert manifest.workflow.state is WorkflowState.DOWNLOADED
    assert roles == [
        "external_source_model",
        "source_texture",
        "source_model",
        "blender_conversion_report",
        "blender_conversion_log",
    ]
    assert (asset_root / "source/packages/package_001/Meshy Export.fbx").read_bytes() == (
        source.read_bytes()
    )
    assert (asset_root / "source/packages/package_001/Meshy Export.png").read_bytes() == (
        texture.read_bytes()
    )
    assert set(converted.derived_from) == {
        "external_source_fbx_001",
        "source_texture_001_002",
    }
    assert "WARNING: conversion warning" in (
        asset_root / "source/packages/package_001/blender-conversion.log"
    ).read_text(encoding="utf-8")
    report = json.loads(
        (asset_root / "source/packages/package_001/blender-conversion.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["warnings"] == ["WARNING: conversion warning"]
    assert manifest.quality.observed["source_conversion_warnings"] == [
        "WARNING: conversion warning"
    ]


def test_gltf_sidecars_include_only_declared_safe_dependencies(tmp_path: Path) -> None:
    model = tmp_path / "model.gltf"
    buffer = tmp_path / "model.bin"
    texture = tmp_path / "base color.png"
    unrelated = tmp_path / "unrelated.png"
    buffer.write_bytes(b"buffer")
    texture.write_bytes(b"texture")
    unrelated.write_bytes(b"unrelated")
    model.write_text(
        json.dumps(
            {
                "asset": {"version": "2.0"},
                "buffers": [{"uri": "model.bin", "byteLength": 6}],
                "images": [{"uri": "base%20color.png"}],
            }
        ),
        encoding="utf-8",
    )
    assert _gltf_sidecars(model) == [texture, buffer]

    model.write_text(
        json.dumps(
            {
                "asset": {"version": "2.0"},
                "buffers": [{"uri": "../escape.bin", "byteLength": 6}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(FoundryError, match="missing or unsafe"):
        _gltf_sidecars(model)
