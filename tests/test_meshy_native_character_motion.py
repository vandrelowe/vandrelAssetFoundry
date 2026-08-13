import hashlib
import json
import struct
import zipfile
from pathlib import Path

import pytest
from PIL import Image

import vandrel_foundry.services.assemble_meshy_native_character_motion as service
import vandrel_foundry.services.validate_meshy_native_character_release as release_service
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.lanes import LaneConfiguration
from vandrel_foundry.domain.manifest import Artifact, Processor, ScaleCalibration, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.domain.workflow_policy import transition_workflow
from vandrel_foundry.services.add_meshy_native_character_package import (
    add_meshy_native_character_package,
)
from vandrel_foundry.services.add_meshy_native_multi_motion_package import (
    LEGACY_UUID,
    add_meshy_native_multi_motion_package,
)
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.inspect_glb_skin import (
    inspect_top8_repaired_glb_skin,
    require_matching_top8_repaired_skin,
)
from vandrel_foundry.services.validate_godot import ProcessResult
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.save_journal import SaveDiagnosis

ACTIONS = sorted(
    [
        "target_character|019fe8c8-1952-7ce9-a611-33851c9cf0b2",
        "target_character|019fe8ca-a6c4-7968-822f-92efebbab5a4",
        "target_character|019fe8d4-0feb-798a-bcbb-81126f26e17f",
        "target_character|019fe8d7-ed16-7b82-a594-728d821ee711",
        "target_character|Female_Crouch_Pick_Fruit_Basket_Stand",
        "target_character|Female_Stand_Pick_Fruit_Basket",
        "target_character|Female_Walk_Pick_Put_In_Pocket",
        "target_character|Red_Carpet_Walk",
        "target_character|Running",
        "target_character|Walking",
    ],
    key=str.casefold,
)

MULTI_ACTIONS = [
    LEGACY_UUID,
    "Angry_Ground_Stomp",
    "Carry_Heavy_Object_Walk",
    "Collect_Object",
    "Crouch_and_Step_Back",
    "Dead",
    "dying_backwards",
    "Fall_Dead_from_Abdominal_Injury",
    "falling_down",
    "Female_Crouch_Pick_Fruit_Basket_Stand",
    "Female_Stand_Pick_Fruit_Basket",
    "Hit_Reaction_1",
    "Idle_02",
    "Idle_6",
    "Idle_7",
    "Idle_9",
    "Running",
    "Skill_01",
    "Stand_To_Side_Lying",
    "Walking",
]
COLLISION_NAMES = {
    "Walking",
    "Running",
    "Female_Crouch_Pick_Fruit_Basket_Stand",
    "Female_Stand_Pick_Fruit_Basket",
}
RELEASE_REVIEW_ACTIONS = [
    "target_character|019fe8ca-a6c4-7968-822f-92efebbab5a4",
    "target_character|019fe8d7-ed16-7b82-a594-728d821ee711",
    "target_character|Idle_6",
    "target_character|Dead",
    "target_character|Stand_To_Side_Lying",
    "target_character|Walking",
    "target_character|Running",
    "target_character|Angry_Ground_Stomp",
    "target_character|Hit_Reaction_1",
    "target_character|Carry_Heavy_Object_Walk",
    "target_character|Collect_Object",
    "target_character|Female_Crouch_Pick_Fruit_Basket_Stand",
    "target_character|Female_Stand_Pick_Fruit_Basket",
]
REPRESENTATIVE_ACTIONS = [
    "target_character|Idle_6",
    "target_character|Walking",
    "target_character|Pull_Radish",
]


def _lanes():
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


def _write_glb(
    path: Path,
    names: list[str],
    *,
    image: bool = True,
    corrupt_skin: bool = False,
    top8: bool = False,
    bad_material: bool = False,
):
    binary = bytearray()
    views = []
    accessors = []

    def add_view(value: bytes) -> int:
        while len(binary) % 4:
            binary.append(0)
        offset = len(binary)
        binary.extend(value)
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(value)})
        return len(views) - 1

    def add_accessor(value: bytes, component: int, shape: str, count: int) -> int:
        view = add_view(value)
        accessors.append(
            {
                "bufferView": view,
                "componentType": component,
                "count": count,
                "type": shape,
            }
        )
        return len(accessors) - 1

    positions = add_accessor(
        struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0), 5126, "VEC3", 3
    )
    normals = add_accessor(
        struct.pack("<9f", 0, 0, 1, 0, 0, 1, 0, 0, 1), 5126, "VEC3", 3
    )
    joints = add_accessor(bytes([0, 1, 2, 3] * 3), 5121, "VEC4", 3)
    weights_value = ([0.4, 0.25, 0.15, 0.1] if top8 else [0.4, 0.3, 0.2, 0.1]) * 3
    if corrupt_skin:
        weights_value[-1] = 0.0
    weights = add_accessor(struct.pack("<12f", *weights_value), 5126, "VEC4", 3)
    joints_1 = (
        add_accessor(bytes([4, 5, 6, 7] * 3), 5121, "VEC4", 3) if top8 else None
    )
    weights_1 = (
        add_accessor(
            struct.pack("<12f", *([0.04, 0.03, 0.02, 0.01] * 3)),
            5126,
            "VEC4",
            3,
        )
        if top8
        else None
    )
    matrices = []
    for index in range(24):
        matrix = [1.0 if row % 5 == 0 else 0.0 for row in range(16)]
        if corrupt_skin and index == 0:
            matrix[0] = 2.0
        matrices.extend(matrix)
    inverse = add_accessor(struct.pack("<384f", *matrices), 5126, "MAT4", 24)
    image_view = add_view(b"texture") if image else None
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": views,
        "accessors": accessors,
        "meshes": [
            {
                "primitives": [
                    {
                        "attributes": {
                            "POSITION": positions,
                            "NORMAL": normals,
                            "JOINTS_0": joints,
                            "WEIGHTS_0": weights,
                            **(
                                {"JOINTS_1": joints_1, "WEIGHTS_1": weights_1}
                                if top8
                                else {}
                            ),
                        },
                        "material": 0,
                    }
                ]
            }
        ],
        "materials": [
            {
                **(
                    {
                        "alphaMode": "BLEND",
                        "emissiveFactor": [1.0, 1.0, 1.0],
                        "emissiveTexture": {"index": 0},
                        "extensions": {
                            "KHR_materials_specular": {
                                "specularColorFactor": [2.0, 2.0, 2.0]
                            }
                        },
                    }
                    if bad_material
                    else {}
                ),
                "pbrMetallicRoughness": {
                    "baseColorTexture": {"index": 0},
                    **(
                        {"metallicFactor": 0.0, "roughnessFactor": 0.8}
                        if top8
                        else {}
                    ),
                }
            }
        ],
        "textures": [{"source": 0}] if image else [],
        "images": (
            [{"bufferView": image_view, "mimeType": "image/png"}] if image else []
        ),
        "nodes": [
            *[
                {"name": "Hips" if index == 0 else f"joint_{index}"}
                for index in range(24)
            ],
            {"name": "Character", "mesh": 0, "skin": 0},
        ],
        "skins": [
            {
                "name": "Armature",
                "joints": list(range(24)),
                "inverseBindMatrices": inverse,
            }
        ],
        "animations": [{"name": name} for name in names],
    }
    payload = json.dumps(document, separators=(",", ":")).encode()
    payload += b" " * (-len(payload) % 4)
    binary += b"\x00" * (-len(binary) % 4)
    path.write_bytes(
        struct.pack("<4sII", b"glTF", 2, 28 + len(payload) + len(binary))
        + struct.pack("<II", len(payload), 0x4E4F534A)
        + payload
        + struct.pack("<II", len(binary), 0x004E4942)
        + binary
    )


def test_top8_repaired_glb_proves_skin_geometry_texture_and_material(tmp_path):
    reference = tmp_path / "reference.glb"
    output = tmp_path / "output.glb"
    _write_glb(reference, [], top8=True)
    _write_glb(output, ["Idle"], top8=True)

    reference_proof = inspect_top8_repaired_glb_skin(reference)
    output_proof = inspect_top8_repaired_glb_skin(output)
    require_matching_top8_repaired_skin(
        reference_proof,
        output_proof,
        hashlib.sha256(b"texture").hexdigest(),
    )

    assert output_proof.joint_weight_sets == (
        "JOINTS_0",
        "JOINTS_1",
        "WEIGHTS_0",
        "WEIGHTS_1",
    )
    assert output_proof.maximum_influences == 8
    assert output_proof.unweighted_vertex_count == 0
    assert output_proof.normal_attribute_present is True
    assert output_proof.alpha_modes == ("OPAQUE",)
    assert output_proof.metallic_factors == (0.0,)
    assert output_proof.roughness_factors == (0.8,)
    assert output_proof.emissive_texture_count == 0


def test_top8_repaired_glb_rejects_legacy_emissive_blend_material(tmp_path):
    output = tmp_path / "bad-material.glb"
    _write_glb(output, [], top8=True, bad_material=True)

    with pytest.raises(FoundryError, match="opaque, nonmetallic"):
        inspect_top8_repaired_glb_skin(output)


def test_top8_repaired_glb_rejects_missing_second_influence_set(tmp_path):
    output = tmp_path / "top4.glb"
    _write_glb(output, [], top8=False)

    with pytest.raises(FoundryError, match="JOINTS_1"):
        inspect_top8_repaired_glb_skin(output)


def _candidate(config, prompt: Path, tmp_path: Path):
    config.tools.blender_executable = prompt
    create_asset(config, _lanes(), "native_motion_test_001", "humanoid", "Native", prompt)
    archive = tmp_path / "character.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as value:
        value.writestr("package/Character_output.fbx", b"character")
        value.writestr("package/Animation_Walking_withSkin.fbx", b"walking")
        value.writestr("package/texture_0.png", b"texture")
    add_meshy_native_character_package(
        config,
        "native_motion_test_001",
        archive,
        hashlib.sha256(archive.read_bytes()).hexdigest(),
        {
            "source_task_id": "source",
            "source_display_name": "Source",
            "remesh_task_id": "remesh",
            "remesh_face_count": "1",
            "rig_task_id": "rig",
            "excluded_duplicate_rig_task_id": "",
        },
    )
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load("native_motion_test_001")
    revision = manifest.revision
    transition_workflow(manifest, WorkflowState.PROCESSED)
    manifest.revision += 1
    repository.save(manifest, expected_revision=revision)

    create_asset(
        config,
        _lanes(),
        "meshy_native_brukk_canary_001",
        "humanoid",
        "Canary",
        prompt,
    )
    canary_root = repository.asset_directory("meshy_native_brukk_canary_001")
    (canary_root / "processed").mkdir(exist_ok=True)
    (canary_root / "reports").mkdir(exist_ok=True)
    model_path = canary_root / "processed/canary.glb"
    _write_glb(model_path, ACTIONS)
    durations = {name: 1.0 + index / 30 for index, name in enumerate(ACTIONS)}
    report_path = canary_root / "reports/canary.json"
    report_path.write_text(
        json.dumps(
            {
                "clips": [
                    {"exact_name": name, "duration_seconds": duration}
                    for name, duration in durations.items()
                ]
            }
        ),
        encoding="utf-8",
    )
    canary = repository.load("meshy_native_brukk_canary_001")
    processor = Processor(name="blender_meshy_native_normalization", version="1")
    model_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
    report_hash = hashlib.sha256(report_path.read_bytes()).hexdigest()
    canary.artifacts.extend(
        [
            Artifact(
                artifact_id="meshy_native_canary_model_005",
                role="processed_model",
                stage="processed",
                format="glb",
                path="processed/canary.glb",
                sha256=model_hash,
                size_bytes=model_path.stat().st_size,
                processor=processor,
            ),
            Artifact(
                artifact_id="meshy_native_canary_report_005",
                role="meshy_native_canary_report",
                stage="processing",
                format="json",
                path="reports/canary.json",
                sha256=report_hash,
                size_bytes=report_path.stat().st_size,
                derived_from=["meshy_native_canary_model_005"],
                processor=processor,
            ),
        ]
    )
    revision = canary.revision
    canary.revision += 1
    repository.save(canary, expected_revision=revision)
    return repository, repository.asset_directory("native_motion_test_001"), durations


def _extend_candidate(config, repository, tmp_path: Path, durations):
    service.assemble_meshy_native_character_motion(
        config, "native_motion_test_001", _runner(durations)
    )
    archive = tmp_path / "multi-motion.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as value:
        for index, name in enumerate(MULTI_ACTIONS):
            value.writestr(
                f"Meshy_AI_Primal_Female_Caveman_biped_Animation_{name}_withSkin.fbx",
                f"entry-{index}-{name}".encode(),
            )
        value.writestr("Meshy_AI_Primal_Female_Caveman_biped_texture_0.png", b"texture")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    add_meshy_native_multi_motion_package(
        config, "native_motion_test_001", archive, digest
    )
    return repository.load("native_motion_test_001")


def _add_motion_archive(config, tmp_path: Path, number: int, names: list[str]):
    archive = tmp_path / f"multi-motion-{number}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as value:
        for index, name in enumerate(names):
            value.writestr(
                f"Meshy_AI_Carrier_Animation_{name}_withSkin.fbx",
                f"entry-{number}-{index}-{name}".encode(),
            )
        value.writestr(f"Meshy_AI_Carrier_texture_{number}.png", b"texture")
    add_meshy_native_multi_motion_package(
        config,
        "native_motion_test_001",
        archive,
        hashlib.sha256(archive.read_bytes()).hexdigest(),
    )


def _runner(
    durations,
    *,
    bind_ok=True,
    duration_ok=True,
    image=True,
    partial=False,
    corrupt_output=False,
    transfer_policy="native_joint_identity_global_pose_reconstruction",
    direct_basis=False,
    old_postfactor=False,
    orientation_delta=0.0,
    extension_mode=None,
    bad_container=False,
    source_maximum_influences=8,
    source_vertices_over_eight=0,
    dropped_influence_count=0,
    dropped_weight_above_eight=0.0,
):
    calls = 0

    def run(arguments, *_unused):
        nonlocal calls
        calls += 1
        separator = arguments.index("--")
        if calls == 1:
            top8 = arguments[-1] == "profile=provider_top8_pbr_v1"
            reference = Path(arguments[separator + 4])
            output = Path(arguments[separator + 5])
            report = Path(arguments[separator + 6])
            _write_glb(reference, [], image=image, top8=top8)
            output_names = list(ACTIONS)
            collisions = []
            extension_entries = []
            extension_durations = {}
            if extension_mode is not None:
                rest_signature = "e" * 64
                source_entries = (
                    json.loads(Path(arguments[separator + 7]).read_text())["entries"]
                    if extension_mode == "full61"
                    else [
                        {
                            "exact_export_name": name,
                            "runtime_eligibility": (
                                "provenance_only_legacy_outlier"
                                if name == LEGACY_UUID
                                else "identity_normalized"
                            ),
                            "source_package_number": 1,
                            "source_qualifier": "fc7f5947",
                        }
                        for name in MULTI_ACTIONS
                    ]
                )
                seen_runtime_names = set(output_names)
                for index, source_entry in enumerate(source_entries):
                    name = source_entry["exact_export_name"]
                    excluded = name == LEGACY_UUID
                    runtime_name = None
                    base = f"target_character|{name}"
                    if not excluded and base not in seen_runtime_names:
                        runtime_name = base
                        seen_runtime_names.add(runtime_name)
                        output_names.append(runtime_name)
                        extension_durations[runtime_name] = 2.0 + index / 300
                    elif not excluded:
                        collisions.append(
                            {
                                "exact_export_name": name,
                                "existing_runtime_action_name": base,
                                "selected_runtime_action_name": base,
                                "retained_alternative_action_name": None,
                                "source_package_number": source_entry.get(
                                    "source_package_number", 1
                                ),
                                "source_qualifier": source_entry.get(
                                    "source_qualifier", "fc7f5947"
                                ),
                                "resolution": "deduplicated_identical_curve",
                            }
                        )
                    extension_entries.append(
                        {
                            "exact_export_name": name,
                            "runtime_eligibility": (
                                "provenance_only_legacy_outlier"
                                if excluded
                                else "identity_normalized"
                            ),
                            "rest_signature": (
                                "f" * 64 if excluded else rest_signature
                            ),
                            "container_rotation_degrees": (
                                90.0 if excluded else (1.0 if bad_container else 0.0)
                            ),
                            "runtime_action_name": runtime_name,
                            "source_package_number": source_entry.get(
                                "source_package_number", 1
                            ),
                        }
                    )
                if extension_mode != "full61":
                    collisions = []
                    for name in sorted(COLLISION_NAMES):
                        base = f"target_character|{name}"
                        different = extension_mode == "different"
                        alternative = (
                            f"target_character|multi_fc7f5947|{name}" if different else None
                        )
                        if alternative is not None:
                            output_names.append(alternative)
                            extension_durations[alternative] = 3.0
                        collisions.append(
                            {
                                "exact_export_name": name,
                                "existing_runtime_action_name": base,
                                "selected_runtime_action_name": base,
                                "retained_alternative_action_name": alternative,
                                "resolution": (
                                    "source_qualified_alternative"
                                    if different
                                    else "deduplicated_identical"
                                ),
                            }
                        )
            _write_glb(
                output,
                output_names,
                image=image,
                corrupt_skin=corrupt_output,
                top8=top8,
            )
            if partial:
                report.write_text("{}", encoding="utf-8")
                return ProcessResult(0, "partial", "", False, False, 0.1)
            output_durations = {**durations, **extension_durations}
            clips = [
                {
                    "exact_name": name,
                    "frame_range": [1, 31],
                    "duration_seconds": duration if duration_ok else duration + 1,
                    "root_xy_baseline": [0, 0],
                    "ground_before_correction_z": 0,
                    "ground_after_range_z": [0, 0],
                    "maximum_sampled_vertex_displacement": 1,
                }
                for name, duration in output_durations.items()
            ]
            signature = "a" * 64
            report.write_text(
                json.dumps(
                    {
                        "schema": (
                            "vandrel_foundry_meshy_native_character_assembly_adapter/6.0"
                            if top8
                            else (
                                "vandrel_foundry_meshy_native_character_assembly_adapter/5.0"
                                if extension_mode == "full61"
                                else "vandrel_foundry_meshy_native_character_assembly_adapter/4.0"
                                if extension_mode is not None
                                else "vandrel_foundry_meshy_native_character_assembly_adapter/3.0"
                            )
                        ),
                        "blender_version": "Blender-test",
                        "transformation_facts": {
                            "target_joint_count": 24,
                            "source_joint_count": 24,
                            "exact_native_joint_hierarchy_match": True,
                            "semantic_transfer_policy": transfer_policy,
                            "index_or_mixamo_graft": False,
                            "rest_rotation_max_delta_radians": 0,
                            "armature_space_correction_quaternion_wxyz": [1, 0, 0, 0],
                            "armature_space_correction_angle_degrees": 0,
                            "target_rest_translation_policy": (
                                "preserve_target_rest_translations_and_bone_lengths"
                            ),
                            "target_pose_scale_policy": (
                                "identity_preserves_target_bone_lengths"
                            ),
                            "old_target_global_rest_postfactor_applied": old_postfactor,
                            "direct_matrix_basis_copy_applied": direct_basis,
                            "maximum_sampled_global_orientation_delta_degrees": (
                                orientation_delta
                            ),
                            "maximum_sampled_parent_local_orientation_delta_degrees": (
                                orientation_delta
                            ),
                            "translation_scale_ratio": 1,
                            "target_bind_matrix_signature_before": signature,
                            "target_bind_matrix_signature_after": (
                                signature if bind_ok else "b" * 64
                            ),
                            "bind_matrices_preserved": True,
                            "source_native_skin_weight_signature": "c" * 64,
                            "target_processed_skin_weight_signature": "d" * 64,
                            "target_top4_skin_weight_signature": "d" * 64,
                            "target_top8_skin_weight_signature": "d" * 64 if top8 else None,
                            "skin_weight_policy": (
                                "deterministic_top8_normalized"
                                if top8
                                else "deterministic_top4_normalized"
                            ),
                            "skin_weights_exactly_preserved": False,
                            "source_vertex_count": 3,
                            "source_maximum_influences": (
                                source_maximum_influences if top8 else 6
                            ),
                            "source_vertices_over_four_influences": 1,
                            "dropped_source_weight_total": 0.05,
                            "top4_maximum_influences": 4,
                            "top4_normalized": True,
                            **(
                                {
                                    "source_vertices_over_8_influences": (
                                        source_vertices_over_eight
                                    ),
                                    "dropped_source_weight_above_8_total": (
                                        dropped_weight_above_eight
                                    ),
                                    "positive_source_influence_identities_preserved": (
                                        source_maximum_influences <= 8
                                    ),
                                    "positive_source_influence_count_dropped": (
                                        dropped_influence_count
                                    ),
                                    "retained_weight_normalization_adjustment_total": 0.01,
                                    "top8_maximum_influences": 8,
                                    "top8_normalized": True,
                                }
                                if top8
                                else {}
                            ),
                            "provider_material_signature_before_normalization": "f" * 64,
                            "target_material_signature_before": signature,
                            "target_material_signature_after": signature,
                            "material_texture_preserved": True,
                            **(
                                {
                                    "material_policy": (
                                        "opaque_basecolor_only_nonmetal_roughness_0_8"
                                    ),
                                    "base_color_texture_only": True,
                                    "authored_distinct_emissive_mask_present": False,
                                    "emissive_factor_zero": True,
                                    "opaque_body_material": True,
                                    "metallic_factor": 0.0,
                                    "roughness_factor": 0.8,
                                    "normal_and_tangent_geometry_preservation_required": True,
                                }
                                if top8
                                else {}
                            ),
                            "preexport_unweighted_vertex_count": 0,
                            "output_action_count": len(output_names),
                            "root_motion_policy": "test",
                            **(
                                {
                                    "base_action_count": 10,
                                    "extension_source_entry_count": len(source_entries),
                                    "extension_compatible_entry_count": sum(
                                        item["runtime_eligibility"]
                                        == "identity_normalized"
                                        for item in source_entries
                                    ),
                                    "extension_provenance_only_entry_count": 1,
                                    "runtime_collision_count": len(collisions),
                                    "runtime_deduplicated_collision_count": (
                                        len(collisions)
                                        if extension_mode in {"identical", "full61"}
                                        else 0
                                    ),
                                    "runtime_source_qualified_collision_count": (
                                        4 if extension_mode == "different" else 0
                                    ),
                                }
                                if extension_mode is not None
                                else {}
                            ),
                        },
                        "clips": clips,
                        "extension_entries": extension_entries,
                        "collisions": collisions,
                    }
                ),
                encoding="utf-8",
            )
        else:
            frames = Path(arguments[separator + 2])
            report = Path(arguments[separator + 3])
            playback_durations = json.loads(
                Path(arguments[separator + 4]).read_text(encoding="utf-8")
            )
            frames.mkdir()
            clips = []
            for index, (name, duration) in enumerate(playback_durations.items()):
                directory = frames / f"clip-{index}"
                directory.mkdir()
                Image.new("RGB", (4, 4), "white").save(directory / "000.png")
                Image.new("RGB", (4, 4), "gray").save(directory / "001.png")
                clips.append(
                    {
                        "exact_name": name,
                        "frame_files": [f"clip-{index}/000.png", f"clip-{index}/001.png"],
                        "duration_delta_seconds": 0,
                        "sampled_ground_minimum_range": [0, 0],
                    }
                )
            report.write_text(
                json.dumps(
                    {
                        "schema": "vandrel_foundry_meshy_native_playback/1.0",
                        "clips": clips,
                    }
                ),
                encoding="utf-8",
            )
        return ProcessResult(0, "ok", "", False, False, 0.1)

    return run


def test_release_review_selector_is_exactly_the_established_thirteen_clips():
    additional = [f"target_character|Package_Action_{index:02d}" for index in range(48)]
    names = [*RELEASE_REVIEW_ACTIONS, *additional]
    entries = [
        {
            "source_package_number": 2,
            "runtime_action_name": name,
            "collision_resolution": "source_qualified_unique",
        }
        for name in additional
    ]

    selected = service._playback_names(
        names,
        True,
        entries,
        profile="release_review",
    )

    assert len(names) == 61
    assert selected == RELEASE_REVIEW_ACTIONS
    assert len(selected) == 13


def _release_validation_candidate(
    config,
    prompt: Path,
    tmp_path: Path,
    *,
    schema: str,
    clip_names: list[str],
    playback_names: list[str],
):
    asset_id = "native_release_validation_test_001"
    config.tools.godot_executable = prompt
    create_asset(config, _lanes(), asset_id, "humanoid", "Native release", prompt)
    repository = ManifestRepository(config.foundry.workspace_root)
    root = repository.asset_directory(asset_id)
    manifest = repository.load(asset_id)

    def artifact_for(
        artifact_id: str,
        role: str,
        stage: str,
        format_name: str,
        relative: str,
        *,
        derived_from: list[str] | None = None,
        processor: Processor | None = None,
    ) -> Artifact:
        path = root / relative
        payload = path.read_bytes()
        return Artifact(
            artifact_id=artifact_id,
            role=role,
            stage=stage,
            format=format_name,
            path=relative,
            sha256=hashlib.sha256(payload).hexdigest(),
            size_bytes=len(payload),
            derived_from=derived_from or [],
            processor=processor,
        )

    source_ids = [f"source_root_{index:03d}" for index in range(28)]
    source_artifacts = []
    for index, artifact_id in enumerate(source_ids):
        relative = f"source/release-validation/root-{index:03d}.fbx"
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"root-{index}".encode())
        source_artifacts.append(
            artifact_for(artifact_id, "source_contribution", "source", "fbx", relative)
        )

    model_path = root / "processed/release-validation/model.glb"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    _write_glb(model_path, clip_names)
    processor = Processor(
        name="blender_meshy_native_character_motion_assembly",
        version="test",
    )
    model_artifact = artifact_for(
        "processed_model_release_validation",
        "processed_model",
        "processed",
        "glb",
        "processed/release-validation/model.glb",
        derived_from=source_ids,
        processor=processor,
    )
    skin = release_service.inspect_top4_glb_skin(model_path)
    skin_facts = {
        "policy": skin.policy,
        "skin_payload_sha256": skin.skin_payload_sha256,
        "inverse_bind_matrices_sha256": skin.inverse_bind_matrices_sha256,
        "material_binding_sha256": skin.material_binding_sha256,
        "embedded_image_sha256s": list(skin.embedded_image_sha256s),
        "unweighted_vertex_count": skin.unweighted_vertex_count,
        "maximum_influences": skin.maximum_influences,
    }

    playback_artifacts = []
    playback = []
    for index, name in enumerate(playback_names):
        artifact_id = f"release_review_playback_{index:03d}"
        relative = f"preview/release-validation/{index:02d}.webp"
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"playback-{index}".encode())
        playback_artifacts.append(
            artifact_for(
                artifact_id,
                "meshy_native_character_motion_playback",
                "review",
                "webp",
                relative,
                derived_from=[model_artifact.artifact_id],
                processor=processor,
            )
        )
        playback.append(
            {
                "artifact_id": artifact_id,
                "exact_name": name,
                "duration_seconds": 1.0,
            }
        )

    report_value = {
        "schema": schema,
        "asset_id": asset_id,
        "processor": {"name": processor.name, "version": processor.version},
        "source_union": source_ids,
        "source_bindings": [],
        "semantic_evidence": {},
        "transformation_facts": {
            "semantic_transfer_policy": "native_joint_identity_global_pose_reconstruction",
            "bind_matrices_preserved": True,
            "material_texture_preserved": True,
            "independent_top4_reference_match": True,
            "independent_final_top4_skin": skin_facts,
            "maximum_sampled_global_orientation_delta_degrees": 0.0,
            "maximum_sampled_parent_local_orientation_delta_degrees": 0.0,
            "playback_evidence_profile": (
                "representative_batch" if schema.endswith("/1.4") else "release_review"
            ),
        },
        "clips": [
            {"exact_name": name, "duration_seconds": 1.0} for name in clip_names
        ],
        "playback": playback,
        "comparison": {},
        "runtime_readiness": {"vandrel_ready": False},
        "output": {
            "sha256": model_artifact.sha256,
            "size_bytes": model_artifact.size_bytes,
        },
        "process_logs": [],
    }
    report_path = root / "reports/release-validation/assembly.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report_value), encoding="utf-8")
    report_artifact = artifact_for(
        "motion_report_release_validation",
        "meshy_native_character_motion_report",
        "processing",
        "json",
        "reports/release-validation/assembly.json",
        derived_from=[model_artifact.artifact_id, *source_ids],
        processor=processor,
    )

    manifest.artifacts.extend(
        [*source_artifacts, model_artifact, report_artifact, *playback_artifacts]
    )
    transition_workflow(manifest, WorkflowState.DOWNLOADED)
    transition_workflow(manifest, WorkflowState.PROCESSED)
    transition_workflow(manifest, WorkflowState.REVIEW)
    manifest.validation.result = "passed"
    manifest.validation.checks = [{"name": "godot_sandbox_import", "passed": True}]
    source_revision = manifest.revision
    manifest.revision += 1
    repository.save(manifest, expected_revision=source_revision)

    calls = {"count": 0}

    def runner(_arguments, operation_root, *_unused):
        calls["count"] += 1
        if calls["count"] == 2:
            (Path(operation_root) / "result.json").write_text(
                json.dumps(
                    {
                        "schema": "vandrel_foundry_godot_meshy_native_release/1.0",
                        "passed": True,
                        "animation_count": len(clip_names),
                        "bone_count": 24,
                        "visible_skinned_mesh_count": 1,
                        "textured_material_count": 1,
                        "finite_sampled_bone_transforms": True,
                        "maximum_duration_delta_seconds": 0.0,
                        "duration_tolerance_policy": (
                            "godot_import_may_quantize_by_at_most_one_30fps_frame"
                        ),
                        "dead_final_hold_root_delta": 0.0,
                    }
                ),
                encoding="utf-8",
            )
        return ProcessResult(0, "ok", "", False, False, 0.1)

    return asset_id, root, runner, calls


def test_schema_1_3_release_validation_accepts_exact_thirteen_clip_review(
    config, prompt, tmp_path
):
    clip_names = [
        *RELEASE_REVIEW_ACTIONS,
        *(f"target_character|Package_Action_{index:02d}" for index in range(48)),
    ]
    asset_id, root, runner, calls = _release_validation_candidate(
        config,
        prompt,
        tmp_path,
        schema="vandrel_foundry_meshy_native_character_motion/1.3",
        clip_names=clip_names,
        playback_names=RELEASE_REVIEW_ACTIONS,
    )

    result = release_service.validate_meshy_native_character_release(
        config,
        asset_id,
        runner=runner,
        environment={},
    )

    validated = json.loads((root / result.report.path).read_text(encoding="utf-8"))
    assert calls["count"] == 2
    assert validated["schema"] == "vandrel_foundry_meshy_native_character_release/1.1"
    assert validated["selected_review_clips"] == RELEASE_REVIEW_ACTIONS
    assert len(validated["playback_evidence"]) == 13


@pytest.mark.parametrize(
    "work_action",
    ["target_character|Pull_Radish", "target_character|Collect_Object"],
)
def test_schema_1_4_release_validation_accepts_exact_representative_batch(
    config, prompt, tmp_path, work_action
):
    additional = (
        ["target_character|Pull_Radish"]
        if work_action.endswith("Pull_Radish")
        else []
    )
    package_count = 61 - len(RELEASE_REVIEW_ACTIONS) - len(additional)
    clip_names = [
        *RELEASE_REVIEW_ACTIONS,
        *additional,
        *(f"target_character|Package_Action_{index:02d}" for index in range(package_count)),
    ]
    representative_actions = [*REPRESENTATIVE_ACTIONS[:2], work_action]
    asset_id, root, runner, calls = _release_validation_candidate(
        config,
        prompt,
        tmp_path,
        schema="vandrel_foundry_meshy_native_character_motion/1.4",
        clip_names=clip_names,
        playback_names=representative_actions,
    )

    result = release_service.validate_meshy_native_character_release(
        config,
        asset_id,
        runner=runner,
        environment={},
    )

    validated = json.loads((root / result.report.path).read_text(encoding="utf-8"))
    live = ManifestRepository(config.foundry.workspace_root).load(asset_id)
    check = next(
        item
        for item in live.validation.checks
        if item.get("name") == "meshy_native_character_release_playback"
    )
    assert calls["count"] == 2
    assert validated["schema"] == "vandrel_foundry_meshy_native_character_release/1.2"
    assert validated["selected_review_clips"] == representative_actions
    assert len(validated["clip_inventory"]) == 61
    assert len(validated["playback_evidence"]) == 3
    assert check["playback_clip_names"] == representative_actions
    assert check["assembly_evidence_schema"].endswith("/1.4")
    assert check["playback_evidence_profile"] == "representative_batch"


@pytest.mark.parametrize(
    ("case", "clip_count", "playback_names"),
    [
        (
            "missing",
            61,
            [
                "target_character|Idle_6",
                "target_character|Walking",
                "target_character|Package_Action_00",
            ],
        ),
        (
            "wrong",
            61,
            [
                "target_character|Walking",
                "target_character|Idle_6",
                "target_character|Pull_Radish",
            ],
        ),
        (
            "duplicate",
            61,
            [
                "target_character|Idle_6",
                "target_character|Walking",
                "target_character|Walking",
            ],
        ),
        (
            "additional",
            61,
            [
                *REPRESENTATIVE_ACTIONS,
                "target_character|Package_Action_00",
            ],
        ),
        ("incomplete_inventory", 60, REPRESENTATIVE_ACTIONS),
    ],
)
def test_schema_1_4_release_validation_rejects_invalid_representative_evidence(
    config, prompt, tmp_path, case, clip_count, playback_names
):
    core = [*RELEASE_REVIEW_ACTIONS, "target_character|Pull_Radish"]
    clip_names = [
        *core,
        *(
            f"target_character|Package_Action_{index:02d}"
            for index in range(clip_count - len(core))
        ),
    ]
    if case == "missing":
        clip_names[RELEASE_REVIEW_ACTIONS.index("target_character|Collect_Object")] = (
            "target_character|Package_Action_Missing_Fallback"
        )
        clip_names[13] = "target_character|Package_Action_Missing_Work"
    asset_id, _root, runner, calls = _release_validation_candidate(
        config,
        prompt,
        tmp_path,
        schema="vandrel_foundry_meshy_native_character_motion/1.4",
        clip_names=clip_names,
        playback_names=playback_names,
    )

    with pytest.raises(FoundryError, match="representative|61-action"):
        release_service.validate_meshy_native_character_release(
            config,
            asset_id,
            runner=runner,
            environment={},
        )
    assert calls["count"] == 0


def test_assembly_registers_six_root_lineage_without_generic_semantics(config, prompt, tmp_path):
    repository, root, durations = _candidate(config, prompt, tmp_path)
    result = service.assemble_meshy_native_character_motion(
        config, "native_motion_test_001", _runner(durations)
    )
    manifest = repository.load("native_motion_test_001")
    roots = [
        item for item in manifest.artifacts if item.stage == "source" and not item.derived_from
    ]
    assert len(roots) == 6
    assert len(result.playback) == 10
    assert result.model.derived_from == sorted(item.artifact_id for item in roots)
    portable_manifest = json.dumps(manifest.model_dump(mode="json"))
    assert "squat_butcher" not in portable_manifest
    assert "squat_eat" not in portable_manifest
    report = json.loads((root / result.report.path).read_text())
    assert report["runtime_readiness"]["vandrel_ready"] is False
    assert report["comparison"]["clean_motion_claimed"] is False
    facts = report["transformation_facts"]
    assert facts["skin_weight_policy"] == "deterministic_top4_normalized"
    assert facts["skin_weights_exactly_preserved"] is False
    assert facts["independent_top4_reference_match"] is True
    assert facts["independent_final_top4_skin"]["joint_weight_sets"] == [
        "JOINTS_0",
        "WEIGHTS_0",
    ]
    assert facts["independent_final_top4_skin"]["maximum_influences"] == 4
    assert facts["independent_final_top4_skin"]["unweighted_vertex_count"] == 0
    assert facts["semantic_transfer_policy"] == (
        "native_joint_identity_global_pose_reconstruction"
    )
    assert facts["old_target_global_rest_postfactor_applied"] is False
    assert facts["direct_matrix_basis_copy_applied"] is False
    assert facts["maximum_sampled_global_orientation_delta_degrees"] == 0
    assert facts["maximum_sampled_parent_local_orientation_delta_degrees"] == 0


def test_repair_profile_preserves_r001_and_registers_top8_material_comparison(
    config, prompt, tmp_path
):
    repository, root, durations = _candidate(config, prompt, tmp_path)
    _extend_candidate(config, repository, tmp_path, durations)
    second_names = [
        "Heavy_Hammer_Swing",
        "Pull_Radish",
        "Walk_Forward_with_Bow_Aimed",
        *[f"Second_Action_{index:02d}" for index in range(15)],
        "Walking",
    ]
    third_names = [
        *[f"Third_Action_{index:02d}" for index in range(18)],
        "Running",
    ]
    _add_motion_archive(config, tmp_path, 2, second_names)
    _add_motion_archive(config, tmp_path, 3, third_names)
    baseline = service.assemble_meshy_native_character_motion(
        config,
        "native_motion_test_001",
        _runner(durations, extension_mode="full61"),
        playback_profile="representative_batch",
    )
    baseline_bytes = (root / baseline.model.path).read_bytes()
    manifest = repository.load("native_motion_test_001")
    transition_workflow(manifest, WorkflowState.REVIEW)
    transition_workflow(manifest, WorkflowState.APPROVED)
    manifest.approval.approved = True
    manifest.approval.approved_at = utc_now()
    manifest.approval.approved_artifact_hashes = {
        "processed_model": baseline.model.sha256
    }
    manifest.release.released = True
    manifest.release.release_revision = 1
    manifest.release.released_at = utc_now()
    revision = manifest.revision
    manifest.revision += 1
    repository.save(manifest, expected_revision=revision)

    result = service.assemble_meshy_native_character_motion(
        config,
        "native_motion_test_001",
        _runner(durations, extension_mode="full61"),
        playback_profile="repair_canary",
        processing_profile="provider_top8_pbr_v1",
    )

    live = repository.load("native_motion_test_001")
    report = json.loads((root / result.report.path).read_text(encoding="utf-8"))
    facts = report["transformation_facts"]
    assert live.workflow.state is WorkflowState.PROCESSED
    assert live.approval.approved is False
    assert live.release.released is True
    assert (root / baseline.model.path).read_bytes() == baseline_bytes
    assert report["schema"] == "vandrel_foundry_meshy_native_character_motion/1.5"
    assert len(report["clips"]) == 61
    assert len(report["playback"]) == 6
    assert len(result.playback) == 6
    assert len(report["process_logs"]) == 4
    assert facts["skin_weight_policy"] == "deterministic_top8_normalized"
    assert facts["material_policy"] == (
        "opaque_basecolor_only_nonmetal_roughness_0_8"
    )
    assert report["runtime_readiness"]["vandrel_ready"] is False
    assert report["runtime_readiness"]["top8_source_influence_gate_passes"] is True
    assert report["runtime_readiness"]["consumer_blocking_reasons"] == [
        "pending_vandrel_lightweight_f12_validation"
    ]
    assert facts["independent_final_skin"]["joint_weight_sets"] == [
        "JOINTS_0",
        "JOINTS_1",
        "WEIGHTS_0",
        "WEIGHTS_1",
    ]
    assert all(len(item["comparison_stages"]) == 3 for item in report["playback"])
    assert all((root / item.path).is_file() for item in result.playback)


def test_repair_profile_records_and_blocks_source_influences_above_eight(
    config, prompt, tmp_path
):
    repository, root, durations = _candidate(config, prompt, tmp_path)
    _extend_candidate(config, repository, tmp_path, durations)
    _add_motion_archive(
        config,
        tmp_path,
        2,
        [
            "Heavy_Hammer_Swing",
            "Pull_Radish",
            "Walk_Forward_with_Bow_Aimed",
            *[f"Second_Action_{index:02d}" for index in range(15)],
            "Walking",
        ],
    )
    _add_motion_archive(
        config,
        tmp_path,
        3,
        [*[f"Third_Action_{index:02d}" for index in range(18)], "Running"],
    )
    baseline = service.assemble_meshy_native_character_motion(
        config,
        "native_motion_test_001",
        _runner(durations, extension_mode="full61"),
        playback_profile="representative_batch",
    )
    manifest = repository.load("native_motion_test_001")
    transition_workflow(manifest, WorkflowState.REVIEW)
    transition_workflow(manifest, WorkflowState.APPROVED)
    manifest.approval.approved = True
    manifest.approval.approved_at = utc_now()
    manifest.approval.approved_artifact_hashes = {
        "processed_model": baseline.model.sha256
    }
    manifest.release.released = True
    manifest.release.release_revision = 1
    manifest.release.released_at = utc_now()
    revision = manifest.revision
    manifest.revision += 1
    repository.save(manifest, expected_revision=revision)

    result = service.assemble_meshy_native_character_motion(
        config,
        "native_motion_test_001",
        _runner(
            durations,
            extension_mode="full61",
            source_maximum_influences=10,
            source_vertices_over_eight=15,
            dropped_influence_count=18,
            dropped_weight_above_eight=0.0370816984504927,
        ),
        playback_profile="repair_canary",
        processing_profile="provider_top8_pbr_v1",
    )

    report = json.loads((root / result.report.path).read_text(encoding="utf-8"))
    facts = report["transformation_facts"]
    assert facts["source_maximum_influences"] == 10
    assert facts["source_vertices_over_8_influences"] == 15
    assert facts["positive_source_influence_count_dropped"] == 18
    assert facts["dropped_source_weight_above_8_total"] == pytest.approx(
        0.0370816984504927
    )
    assert facts["positive_source_influence_identities_preserved"] is False
    assert facts["skin_weights_exactly_preserved"] is False
    assert report["runtime_readiness"]["vandrel_ready"] is False
    assert report["runtime_readiness"]["top8_source_influence_gate_passes"] is False
    assert report["runtime_readiness"]["consumer_blocking_reasons"] == [
        "greater_than_eight_source_influences",
        "pending_vandrel_lightweight_f12_validation",
    ]


def test_repair_profile_retries_review_as_fresh_processed_attempt(
    config, prompt, tmp_path
):
    repository, root, durations = _candidate(config, prompt, tmp_path)
    _extend_candidate(config, repository, tmp_path, durations)
    _add_motion_archive(
        config,
        tmp_path,
        2,
        [
            "Heavy_Hammer_Swing",
            "Pull_Radish",
            "Walk_Forward_with_Bow_Aimed",
            *[f"Second_Action_{index:02d}" for index in range(15)],
            "Walking",
        ],
    )
    _add_motion_archive(
        config,
        tmp_path,
        3,
        [*[f"Third_Action_{index:02d}" for index in range(18)], "Running"],
    )
    first = service.assemble_meshy_native_character_motion(
        config,
        "native_motion_test_001",
        _runner(durations, extension_mode="full61"),
        playback_profile="representative_batch",
    )
    old_report_bytes = (root / first.report.path).read_bytes()
    manifest = repository.load("native_motion_test_001")
    transition_workflow(manifest, WorkflowState.REVIEW)
    manifest.validation.result = "passed"
    manifest.validation.checks = [
        {
            "name": "godot_sandbox_import",
            "passed": True,
            "processed_model_sha256": first.model.sha256,
        }
    ]
    manifest.scale_calibration = ScaleCalibration(
        status="approved",
        processed_model_sha256=first.model.sha256,
        preview_report_sha256="a" * 64,
        source_bounds_min=[0.0, 0.0, 0.0],
        source_bounds_max=[1.0, 1.0, 1.0],
        source_dimensions=[1.0, 1.0, 1.0],
        target_height_meters=1.8,
        baseline_uniform_scale=1.8,
        variation_min_multiplier=0.9,
        variation_max_multiplier=1.1,
        reference_standard="meter_grid_and_human_1_8m",
        reviewer="test-reviewer",
        approved_at=utc_now(),
        notes="stale model-bound test calibration",
    )
    manifest.approval.approved = True
    manifest.approval.approved_at = utc_now()
    manifest.approval.approved_artifact_hashes = {
        "processed_model": first.model.sha256
    }
    revision = manifest.revision
    manifest.revision += 1
    repository.save(manifest, expected_revision=revision)

    retry = service.assemble_meshy_native_character_motion(
        config,
        "native_motion_test_001",
        _runner(durations, extension_mode="full61"),
        playback_profile="repair_canary",
        processing_profile="provider_top8_pbr_v1",
    )

    live = repository.load("native_motion_test_001")
    assert live.workflow.state is WorkflowState.PROCESSED
    assert int(retry.model.artifact_id.rsplit("_", 1)[-1]) == (
        int(first.model.artifact_id.rsplit("_", 1)[-1]) + 1
    )
    assert int(retry.report.artifact_id.rsplit("_", 1)[-1]) == (
        int(first.report.artifact_id.rsplit("_", 1)[-1]) + 1
    )
    assert retry.report.artifact_id != first.report.artifact_id
    assert any(
        artifact.artifact_id == first.report.artifact_id
        for artifact in live.artifacts
    )
    assert (root / first.report.path).read_bytes() == old_report_bytes
    assert live.validation.result == "not_run"
    assert live.validation.checks == []
    assert live.scale_calibration.status == "not_calibrated"
    assert live.scale_calibration.processed_model_sha256 is None
    assert live.approval.approved is False
    assert live.approval.approved_artifact_hashes == {}


@pytest.mark.parametrize(
    "options",
    [
        {"transfer_policy": "native_joint_identity_rest_space_delta"},
        {"direct_basis": True},
        {"old_postfactor": True},
    ],
)
def test_assembly_rejects_direct_copy_and_old_rest_postfactor(
    config, prompt, tmp_path, options
):
    repository, root, durations = _candidate(config, prompt, tmp_path)
    before = repository.load("native_motion_test_001")
    with pytest.raises(FoundryError, match="violate the contract"):
        service.assemble_meshy_native_character_motion(
            config, "native_motion_test_001", _runner(durations, **options)
        )
    assert repository.load("native_motion_test_001").model_dump(mode="json") == before.model_dump(
        mode="json"
    )
    assert not (root / "processed/meshy-native-character-motion").exists()


def test_assembly_rejects_nonzero_h4_orientation_delta(config, prompt, tmp_path):
    repository, root, durations = _candidate(config, prompt, tmp_path)
    before = repository.load("native_motion_test_001")
    with pytest.raises(FoundryError, match="orientation reconstruction did not close"):
        service.assemble_meshy_native_character_motion(
            config,
            "native_motion_test_001",
            _runner(durations, orientation_delta=0.01),
        )
    assert repository.load("native_motion_test_001").model_dump(mode="json") == before.model_dump(
        mode="json"
    )
    assert not (root / "processed/meshy-native-character-motion").exists()


def test_assembly_creates_fresh_numbered_attempt_without_rewriting_first(
    config, prompt, tmp_path
):
    repository, root, durations = _candidate(config, prompt, tmp_path)
    first = service.assemble_meshy_native_character_motion(
        config, "native_motion_test_001", _runner(durations)
    )
    first_hash = hashlib.sha256((root / first.model.path).read_bytes()).hexdigest()
    second = service.assemble_meshy_native_character_motion(
        config, "native_motion_test_001", _runner(durations)
    )
    manifest = repository.load("native_motion_test_001")
    assert first.model.artifact_id.endswith("_001")
    assert second.model.artifact_id.endswith("_002")
    assert str(second.model.path).endswith("model-002.glb")
    assert hashlib.sha256((root / first.model.path).read_bytes()).hexdigest() == first_hash
    roots = [item for item in manifest.artifacts if item.stage == "source" and not item.derived_from]
    assert {item.artifact_id for item in roots} == service.CHARACTER_ROOTS | service.MOTION_ROOTS


def test_assembly_rejects_wrong_root_union_before_runner(config, prompt, tmp_path):
    repository, _root, durations = _candidate(config, prompt, tmp_path)
    manifest = repository.load("native_motion_test_001")
    manifest.artifacts = [
        item
        for item in manifest.artifacts
        if item.artifact_id != "meshy_native_character_texture_root_001"
    ]
    revision = manifest.revision
    manifest.revision += 1
    repository.save(manifest, expected_revision=revision)
    with pytest.raises(FoundryError, match="exact four character roots"):
        service.assemble_meshy_native_character_motion(
            config, "native_motion_test_001", _runner(durations)
        )


def test_assembly_detects_late_source_mutation_and_rolls_back(
    config, prompt, tmp_path, monkeypatch
):
    repository, root, durations = _candidate(config, prompt, tmp_path)
    before = repository.load("native_motion_test_001")
    texture = root / "source/meshy_native_character_package_001/texture.png"
    original_comparison = service._comparison

    def mutate():
        texture.write_bytes(b"late mutation")
        return original_comparison()

    monkeypatch.setattr(service, "_comparison", mutate)
    with pytest.raises(FoundryError, match="input/output changed"):
        service.assemble_meshy_native_character_motion(
            config, "native_motion_test_001", _runner(durations)
        )
    assert repository.load("native_motion_test_001").model_dump(mode="json") == before.model_dump(
        mode="json"
    )
    assert not (root / "processed/meshy-native-character-motion/model-001.glb").exists()
    assert not (root / "reports/meshy-native-character-motion-001.json").exists()


def test_assembly_rehashes_six_roots_immediately_before_save(
    config, prompt, tmp_path, monkeypatch
):
    repository, root, durations = _candidate(config, prompt, tmp_path)
    before = repository.load("native_motion_test_001")
    texture = root / "source/meshy_native_character_package_001/texture.png"
    original_process_artifact = service._process_artifact
    mutated = False

    def mutate_after_promotion(*args, **kwargs):
        nonlocal mutated
        if not mutated:
            mutated = True
            texture.write_bytes(b"mutation after pre-promotion check")
        return original_process_artifact(*args, **kwargs)

    monkeypatch.setattr(service, "_process_artifact", mutate_after_promotion)
    with pytest.raises(FoundryError, match="input/output changed"):
        service.assemble_meshy_native_character_motion(
            config, "native_motion_test_001", _runner(durations)
        )
    live = repository.load("native_motion_test_001")
    assert live.model_dump(mode="json") == before.model_dump(mode="json")
    assert all((root / item.path).exists() for item in before.artifacts)
    assert not (root / "processed/meshy-native-character-motion/model-001.glb").exists()
    assert not (root / "reports/meshy-native-character-motion-001.json").exists()


def test_first_extended_assembly_binds_canary_and_multi_roots_in_one_transaction(
    config, prompt, tmp_path
):
    repository, root, durations = _candidate(config, prompt, tmp_path)
    archive = tmp_path / "multi-motion-first.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as value:
        for index, name in enumerate(MULTI_ACTIONS):
            value.writestr(
                f"Meshy_AI_Primal_Female_Caveman_biped_Animation_{name}_withSkin.fbx",
                f"entry-{index}-{name}".encode(),
            )
        value.writestr(
            "Meshy_AI_Primal_Female_Caveman_biped_texture_0.png", b"texture"
        )
    add_meshy_native_multi_motion_package(
        config,
        "native_motion_test_001",
        archive,
        hashlib.sha256(archive.read_bytes()).hexdigest(),
    )
    before = repository.load("native_motion_test_001")
    assert not service.MOTION_ROOTS <= {
        item.artifact_id for item in before.artifacts if not item.derived_from
    }
    result = service.assemble_meshy_native_character_motion(
        config,
        "native_motion_test_001",
        _runner(durations, extension_mode="identical"),
        playback_profile="representative_batch",
    )
    live = repository.load("native_motion_test_001")
    root_ids = {
        item.artifact_id
        for item in live.artifacts
        if item.stage == "source" and not item.derived_from
    }
    assert service.BASE_ROOTS | service.MULTI_ROOT_IDS == root_ids
    report = json.loads((root / result.report.path).read_text(encoding="utf-8"))
    assert report["schema"] == "vandrel_foundry_meshy_native_character_motion/1.4"
    assert [item["exact_name"] for item in report["playback"]] == [
        "target_character|Idle_6",
        "target_character|Walking",
        "target_character|Collect_Object",
    ]
    assert (root / result.model.path).is_file()


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"partial": True}, "adapter report is invalid"),
        ({"duration_ok": False}, "names or durations"),
        ({"bind_ok": False}, "bind or material signature"),
        ({"image": False}, "independent GLB inspection"),
        ({"corrupt_output": True}, "Top-four GLB skin"),
    ],
)
def test_assembly_gates_partial_duration_bind_and_material(
    config, prompt, tmp_path, options, message
):
    repository, root, durations = _candidate(config, prompt, tmp_path)
    before = repository.load("native_motion_test_001")
    with pytest.raises(FoundryError, match=message):
        service.assemble_meshy_native_character_motion(
            config, "native_motion_test_001", _runner(durations, **options)
        )
    assert repository.load("native_motion_test_001").model_dump(mode="json") == before.model_dump(
        mode="json"
    )
    assert not (root / "processed/meshy-native-character-motion").exists()


@pytest.mark.parametrize("status", ["event_missing", "event_partial", "event_complete"])
def test_assembly_preserves_exact_target_after_post_replace_ambiguity(
    config, prompt, tmp_path, monkeypatch, status
):
    repository, root, durations = _candidate(config, prompt, tmp_path)
    before = repository.load("native_motion_test_001")
    original_save = ManifestRepository.save

    def save_then_fail(self, *args, **kwargs):
        original_save(self, *args, **kwargs)
        raise OSError("simulated lock exit")

    monkeypatch.setattr(ManifestRepository, "save", save_then_fail)
    monkeypatch.setattr(
        ManifestRepository,
        "diagnose_pending_save",
        lambda *_args: SaveDiagnosis(status, "simulated"),
    )
    monkeypatch.setattr(
        ManifestRepository,
        "reconcile_pending_save",
        lambda *_args: SaveDiagnosis("complete", "simulated"),
    )
    result = service.assemble_meshy_native_character_motion(
        config, "native_motion_test_001", _runner(durations)
    )
    live = repository.load("native_motion_test_001")
    assert live.revision == before.revision + 1
    assert any(item.artifact_id == result.report.artifact_id for item in live.artifacts)
    assert (root / result.model.path).is_file()


def test_extended_assembly_retains_twenty_nine_sources_and_deduplicates_identical_names(
    config, prompt, tmp_path
):
    repository, root, durations = _candidate(config, prompt, tmp_path)
    _extend_candidate(config, repository, tmp_path, durations)
    result = service.assemble_meshy_native_character_motion(
        config,
        "native_motion_test_001",
        _runner(durations, extension_mode="identical"),
    )
    manifest = repository.load("native_motion_test_001")
    roots = [
        item for item in manifest.artifacts if item.stage == "source" and not item.derived_from
    ]
    assert len(roots) == 28
    assert set(result.model.derived_from) == service.EXTENDED_ROOTS
    report = json.loads((root / result.report.path).read_text(encoding="utf-8"))
    facts = report["transformation_facts"]
    assert facts["source_animation_entry_count"] == 30
    assert facts["compatible_source_animation_entry_count"] == 29
    assert facts["final_unique_runtime_action_count"] == 25
    assert len(report["clips"]) == 25
    assert len(result.playback) == 13
    assert all(
        item["resolution"] == "deduplicated_identical"
        for item in report["comparison"]["collisions"]
    )
    assert report["comparison"]["eating"]["selected"].endswith(
        "019fe8ca-a6c4-7968-822f-92efebbab5a4"
    )
    assert report["comparison"]["butchering"]["selected"].endswith(
        "019fe8d7-ed16-7b82-a594-728d821ee711"
    )
    assert report["comparison"]["death"]["runtime_policy"] == (
        "play_once_then_hold_final_frame"
    )
    assert report["comparison"]["lie_down_held_pose"]["classified_as_death"] is False


def test_extended_assembly_retains_materially_different_collisions_under_stable_ids(
    config, prompt, tmp_path
):
    repository, root, durations = _candidate(config, prompt, tmp_path)
    _extend_candidate(config, repository, tmp_path, durations)
    result = service.assemble_meshy_native_character_motion(
        config,
        "native_motion_test_001",
        _runner(durations, extension_mode="different"),
    )
    report = json.loads((root / result.report.path).read_text(encoding="utf-8"))
    assert report["transformation_facts"]["final_unique_runtime_action_count"] == 29
    names = {item["exact_name"] for item in report["clips"]}
    for name in COLLISION_NAMES:
        assert f"target_character|{name}" in names
        assert f"target_character|multi_fc7f5947|{name}" in names
    for collision in report["comparison"]["collisions"]:
        assert collision["selected_runtime_action_name"] == (
            f"target_character|{collision['exact_export_name']}"
        )


def test_extended_assembly_rejects_nonidentity_compatible_container(
    config, prompt, tmp_path
):
    repository, root, durations = _candidate(config, prompt, tmp_path)
    _extend_candidate(config, repository, tmp_path, durations)
    before = repository.load("native_motion_test_001")
    with pytest.raises(FoundryError, match="container is not identity-normalized"):
        service.assemble_meshy_native_character_motion(
            config,
            "native_motion_test_001",
            _runner(durations, extension_mode="identical", bad_container=True),
        )
    assert repository.load("native_motion_test_001").model_dump(mode="json") == (
        before.model_dump(mode="json")
    )
    assert not (root / "processed/meshy-native-character-motion/model-002.glb").exists()


def test_extended_assembly_rehashes_late_mutated_multi_root_and_rolls_back(
    config, prompt, tmp_path, monkeypatch
):
    repository, root, durations = _candidate(config, prompt, tmp_path)
    _extend_candidate(config, repository, tmp_path, durations)
    before = repository.load("native_motion_test_001")
    victim = next(
        item
        for item in before.artifacts
        if item.artifact_id == "meshy_native_multi_motion_fbx_root_010"
    )
    original = service._process_artifact
    mutated = False

    def mutate_after_promotion(*args, **kwargs):
        nonlocal mutated
        if not mutated:
            mutated = True
            (root / victim.path).write_bytes(b"late mutation")
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "_process_artifact", mutate_after_promotion)
    with pytest.raises(FoundryError, match="input/output changed"):
        service.assemble_meshy_native_character_motion(
            config,
            "native_motion_test_001",
            _runner(durations, extension_mode="identical"),
        )
    assert repository.load("native_motion_test_001").model_dump(mode="json") == (
        before.model_dump(mode="json")
    )
    assert not (root / "processed/meshy-native-character-motion/model-002.glb").exists()


def test_extended_assembly_save_ambiguity_preserves_exact_target(
    config, prompt, tmp_path, monkeypatch
):
    repository, root, durations = _candidate(config, prompt, tmp_path)
    _extend_candidate(config, repository, tmp_path, durations)
    original = ManifestRepository.save

    def save_then_fail(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise OSError("lock exit")

    monkeypatch.setattr(ManifestRepository, "save", save_then_fail)
    result = service.assemble_meshy_native_character_motion(
        config,
        "native_motion_test_001",
        _runner(durations, extension_mode="identical"),
    )
    live = repository.load("native_motion_test_001")
    assert any(item.artifact_id == result.model.artifact_id for item in live.artifacts)
    assert (root / result.model.path).is_file()
    assert (root / result.report.path).is_file()
