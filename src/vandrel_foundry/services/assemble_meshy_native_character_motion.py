import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, ScaleCalibration, utc_now
from vandrel_foundry.domain.meshy_native_character_motion import (
    SEMANTIC_MAPPING,
    MeshyNativeCharacterMotionReport,
    MeshyNativeMotionSemanticEvidence,
)
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.domain.workflow_policy import invalidate_approval
from vandrel_foundry.services.inspect_glb import inspect_glb, load_glb_document
from vandrel_foundry.services.inspect_glb_skin import (
    inspect_top4_glb_skin,
    require_matching_top4_skin,
)
from vandrel_foundry.services.validate_godot import ProcessRunner, run_bounded_process
from vandrel_foundry.services.windows_acl_policy import apply_candidate_acl
from vandrel_foundry.storage.atomic import json_bytes
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path

PROCESSOR_NAME = "blender_meshy_native_character_motion_assembly"
PROCESSOR_VERSION = "3"
CHARACTER_ROOTS = {
    "meshy_native_character_archive_root_001",
    "meshy_native_character_fbx_root_001",
    "meshy_native_walking_fbx_root_001",
    "meshy_native_character_texture_root_001",
}
MOTION_ROOTS = {
    "meshy_native_motion_model_root_001",
    "meshy_native_motion_report_root_001",
}


@dataclass(frozen=True)
class MeshyNativeCharacterMotionResult:
    model: Artifact
    report: Artifact
    semantic_evidence: Artifact
    playback: tuple[Artifact, ...]


def assemble_meshy_native_character_motion(
    config: FoundryConfig,
    asset_id: str,
    runner: ProcessRunner | None = None,
) -> MeshyNativeCharacterMotionResult:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.asset.lane != "humanoid" or manifest.workflow.state is not WorkflowState.PROCESSED:
        raise FoundryError("Meshy-native character motion assembly requires a processed humanoid.")
    current_roots = [
        item for item in manifest.artifacts if item.stage == "source" and not item.derived_from
    ]
    current_root_ids = {item.artifact_id for item in current_roots}
    if frozenset(current_root_ids) not in {
        frozenset(CHARACTER_ROOTS),
        frozenset([*CHARACTER_ROOTS, *MOTION_ROOTS]),
    }:
        raise FoundryError(
            "Meshy-native character motion assembly requires the exact four character roots "
            "or the exact established six-root union."
        )
    by_id = {
        item.artifact_id: item
        for item in current_roots
        if item.artifact_id in CHARACTER_ROOTS
    }
    required = {
        "meshy_native_character_archive_root_001": ("meshy_native_character_archive", "zip"),
        "meshy_native_character_fbx_root_001": ("meshy_native_character_fbx", "fbx"),
        "meshy_native_walking_fbx_root_001": ("meshy_native_walking_fbx", "fbx"),
        "meshy_native_character_texture_root_001": ("meshy_native_character_texture", "png"),
    }
    if any((by_id[key].role, by_id[key].format) != value for key, value in required.items()):
        raise FoundryError("Meshy-native character root roles or formats are invalid.")
    asset_root = repository.asset_directory(asset_id)
    paths = {key: contained_path(asset_root, item.path) for key, item in by_id.items()}
    adding_motion_roots = current_root_ids == CHARACTER_ROOTS
    if adding_motion_roots:
        canary = repository.load("meshy_native_brukk_canary_001")
        motion_model = _artifact(canary, "meshy_native_canary_model_005")
        motion_report = _artifact(canary, "meshy_native_canary_report_005")
        if (
            motion_model.processor is None
            or motion_model.processor.name != "blender_meshy_native_normalization"
        ):
            raise FoundryError(
                "Current Meshy-native canary model is not normalized by the accepted corridor."
            )
        canary_root = repository.asset_directory(canary.asset.asset_id)
        external = {
            "meshy_native_motion_model_root_001": (
                contained_path(canary_root, motion_model.path),
                motion_model,
            ),
            "meshy_native_motion_report_root_001": (
                contained_path(canary_root, motion_report.path),
                motion_report,
            ),
        }
    else:
        motion_by_id = {
            item.artifact_id: item
            for item in current_roots
            if item.artifact_id in MOTION_ROOTS
        }
        motion_model = motion_by_id["meshy_native_motion_model_root_001"]
        motion_report = motion_by_id["meshy_native_motion_report_root_001"]
        if (
            (motion_model.role, motion_model.format)
            != ("meshy_native_motion_model", "glb")
            or (motion_report.role, motion_report.format)
            != ("meshy_native_motion_report", "json")
        ):
            raise FoundryError("Established Meshy-native motion root roles or formats are invalid.")
        external = {
            key: (contained_path(asset_root, item.path), item)
            for key, item in motion_by_id.items()
        }
    _verify_inputs(paths, by_id, external)
    executable = config.tools.blender_executable
    if executable is None or not executable.is_absolute() or not executable.is_file():
        raise FoundryError("Configure tools.blender_executable as an existing absolute file.")
    number = sum(
        item.role == "meshy_native_character_motion_report" for item in manifest.artifacts
    ) + 1
    suffix = f"{number:03d}"
    model_relative = RelativeManifestPath(
        f"processed/meshy-native-character-motion/model-{suffix}.glb"
    )
    report_relative = RelativeManifestPath(
        f"reports/meshy-native-character-motion-{suffix}.json"
    )
    semantic_relative = RelativeManifestPath(
        f"reports/meshy-native-motion-semantics-{suffix}.json"
    )
    assembly_process_relative = RelativeManifestPath(
        f"reports/meshy-native-character-motion-{suffix}.assembly-process.json"
    )
    playback_process_relative = RelativeManifestPath(
        f"reports/meshy-native-character-motion-{suffix}.playback-process.json"
    )
    preview_relative = RelativeManifestPath(
        f"preview/meshy-native-character-motion-{suffix}"
    )
    motion_source_relative = RelativeManifestPath("source/meshy_native_motion_package_001")
    final_paths = [
        contained_path(asset_root, model_relative),
        contained_path(asset_root, report_relative),
        contained_path(asset_root, semantic_relative),
        contained_path(asset_root, assembly_process_relative),
        contained_path(asset_root, playback_process_relative),
        contained_path(asset_root, preview_relative),
        *(
            [contained_path(asset_root, motion_source_relative)]
            if adding_motion_roots
            else []
        ),
    ]
    if any(path.exists() for path in final_paths):
        raise FoundryError("Meshy-native character motion destination already exists.")
    temporary = None
    promoted: list[Path] = []
    rollback = True
    try:
        temporary = Path(tempfile.mkdtemp(prefix=".meshy-native-character-motion-", dir=asset_root))
        apply_candidate_acl(config, temporary)
        temp_motion = temporary / "motion-source"
        temp_motion.mkdir()
        temp_motion_model = temp_motion / "canary.glb"
        temp_motion_report = temp_motion / "canary-report.json"
        _copy_new(external["meshy_native_motion_model_root_001"][0], temp_motion_model)
        _copy_new(external["meshy_native_motion_report_root_001"][0], temp_motion_report)
        if _hash(temp_motion_model) != (motion_model.sha256, motion_model.size_bytes) or _hash(
            temp_motion_report
        ) != (motion_report.sha256, motion_report.size_bytes):
            raise FoundryError("Meshy-native canary contribution changed while copied.")
        temp_model = temporary / "model.glb"
        temp_reference = temporary / "top4-reference.glb"
        adapter_report = temporary / "assembly-adapter.json"
        assembly_script = (
            Path(__file__).parents[1] / "blender" / "assemble_meshy_native_character.py"
        )
        assembly_args = [
            str(executable),
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "--python-exit-code",
            "1",
            "--python",
            str(assembly_script),
            "--",
            str(paths["meshy_native_character_fbx_root_001"]),
            str(paths["meshy_native_character_texture_root_001"]),
            str(temp_motion_model),
            str(temp_reference),
            str(temp_model),
            str(adapter_report),
        ]
        assembly_log, assembly_result = _run(
            config,
            runner,
            assembly_args,
            asset_root,
            temporary,
            "assembly",
            executable,
            assembly_script,
        )
        adapter = _load_json(adapter_report, "Meshy-native assembly adapter")
        if adapter.get("schema") != "vandrel_foundry_meshy_native_character_assembly_adapter/3.0":
            raise FoundryError("Meshy-native assembly adapter report is invalid.")
        facts = adapter.get("transformation_facts")
        clips = adapter.get("clips")
        if not isinstance(facts, dict) or not isinstance(clips, list) or len(clips) != 10:
            raise FoundryError("Meshy-native assembly adapter report is incomplete.")
        _require_facts(facts)
        canary_data = _load_json(temp_motion_report, "Meshy-native canary report")
        canary_clips = canary_data.get("clips")
        if not isinstance(canary_clips, list) or len(canary_clips) != 10:
            raise FoundryError("Bound canary report has an invalid clip inventory.")
        durations = {item["exact_name"]: float(item["duration_seconds"]) for item in canary_clips}
        names = [item.get("exact_name") for item in clips]
        duration_deltas = {
            item["exact_name"]: abs(float(item["duration_seconds"]) - durations[item["exact_name"]])
            for item in clips
            if item.get("exact_name") in durations
        }
        if names != list(durations) or any(value > 0.002 for value in duration_deltas.values()):
            raise FoundryError(
                "Assembled action names or durations do not match the bound canary report: "
                f"names_match={names == list(durations)}, duration_deltas={duration_deltas}."
            )
        inspection = inspect_glb(temp_model)
        if (
            inspection.mesh_count < 1
            or inspection.material_count < 1
            or inspection.image_count < 1
            or inspection.skin_count != 1
            or inspection.joint_count != 24
            or inspection.animation_count != 10
            or _animation_names(temp_model) != names
        ):
            raise FoundryError(
                "Assembled Meshy-native character failed independent GLB inspection."
            )
        reference_skin = inspect_top4_glb_skin(temp_reference)
        output_skin = inspect_top4_glb_skin(temp_model)
        require_matching_top4_skin(
            reference_skin,
            output_skin,
            by_id["meshy_native_character_texture_root_001"].sha256,
        )

        durations_path = temporary / "durations.json"
        _write_new(durations_path, json_bytes(durations))
        frames_root = temporary / "playback-frames"
        playback_adapter = temporary / "playback-adapter.json"
        playback_script = Path(__file__).parents[1] / "blender" / "render_meshy_native_playback.py"
        playback_args = [
            str(executable),
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "--python-exit-code",
            "1",
            "--python",
            str(playback_script),
            "--",
            str(temp_model),
            str(frames_root),
            str(playback_adapter),
            str(durations_path),
        ]
        playback_log, playback_result = _run(
            config,
            runner,
            playback_args,
            asset_root,
            temporary,
            "playback",
            executable,
            playback_script,
        )
        playback_data = _load_json(playback_adapter, "Meshy-native playback adapter")
        playback_clips = playback_data.get("clips")
        if (
            playback_data.get("schema") != "vandrel_foundry_meshy_native_playback/1.0"
            or not isinstance(playback_clips, list)
            or len(playback_clips) != 10
        ):
            raise FoundryError("Meshy-native playback adapter report is invalid.")
        output_skin = inspect_top4_glb_skin(temp_model)
        require_matching_top4_skin(
            reference_skin,
            output_skin,
            by_id["meshy_native_character_texture_root_001"].sha256,
        )
        temp_videos = temporary / "videos"
        temp_videos.mkdir()
        playback_descriptors = []
        for index, item in enumerate(playback_clips, start=1):
            name = item.get("exact_name")
            if name not in durations or abs(float(item.get("duration_delta_seconds", 1))) > 0.002:
                raise FoundryError("Meshy-native playback duration binding failed.")
            video = temp_videos / f"{index:02d}.webp"
            _encode_webp(frames_root, item, video, durations[name])
            digest, size = _hash(video)
            playback_descriptors.append(
                {
                    "artifact_id": (
                        f"meshy_native_character_motion_playback_{suffix}_{index:03d}"
                    ),
                    "exact_name": name,
                    "path": f"{preview_relative}/{index:02d}.webp",
                    "sha256": digest,
                    "size_bytes": size,
                    "duration_seconds": durations[name],
                    "sampled_ground_minimum_range": item.get("sampled_ground_minimum_range"),
                }
            )
        semantic = MeshyNativeMotionSemanticEvidence(
            schema="vandrel_foundry_meshy_native_motion_semantics/1.0",
            observation_basis="user_observed_provider_metadata",
            provider_api_verification="not_performed",
            mappings=SEMANTIC_MAPPING,
        )
        temp_semantic = temporary / "semantic.json"
        _write_new(temp_semantic, json_bytes(semantic.model_dump(mode="json", by_alias=True)))
        semantic_hash, semantic_size = _hash(temp_semantic)
        assembly_process = _write_process(
            temporary / "assembly-process.json", assembly_log, assembly_result
        )
        playback_process = _write_process(
            temporary / "playback-process.json", playback_log, playback_result
        )
        model_hash, model_size = _hash(temp_model)
        root_ids = sorted([*CHARACTER_ROOTS, *MOTION_ROOTS])
        report = MeshyNativeCharacterMotionReport(
            schema="vandrel_foundry_meshy_native_character_motion/1.1",
            asset_id=asset_id,
            processor={
                "name": PROCESSOR_NAME,
                "version": PROCESSOR_VERSION,
                "tool_version": adapter.get("blender_version"),
            },
            source_union=root_ids,
            source_bindings=_source_bindings(list(by_id.values()), motion_model, motion_report),
            semantic_evidence={
                "artifact_id": f"meshy_native_motion_semantic_evidence_{suffix}",
                "sha256": semantic_hash,
                "observation_basis": "user_observed_provider_metadata",
            },
            transformation_facts={
                **facts,
                "independent_glb_inspection": inspection.__dict__,
                "independent_top4_reference_skin": reference_skin.__dict__,
                "independent_final_top4_skin": output_skin.__dict__,
                "independent_top4_reference_match": True,
            },
            clips=clips,
            playback=playback_descriptors,
            comparison=_comparison(),
            runtime_readiness=_runtime_gaps(names),
            output={
                "artifact_id": f"meshy_native_character_animated_model_{suffix}",
                "path": str(model_relative),
                "sha256": model_hash,
                "size_bytes": model_size,
            },
            process_logs=[assembly_process, playback_process],
        )
        temp_report = temporary / "report.json"
        _write_new(temp_report, json_bytes(report.model_dump(mode="json", by_alias=True)))
        report_hash, report_size = _hash(temp_report)
        _verify_inputs(paths, by_id, external)
        promotion_pairs = [
            (temp_model, contained_path(asset_root, model_relative)),
            (temp_semantic, contained_path(asset_root, semantic_relative)),
            (
                temporary / "assembly-process.json",
                contained_path(asset_root, assembly_process_relative),
            ),
            (
                temporary / "playback-process.json",
                contained_path(asset_root, playback_process_relative),
            ),
            (temp_report, contained_path(asset_root, report_relative)),
            (temp_videos, contained_path(asset_root, preview_relative)),
        ]
        if adding_motion_roots:
            promotion_pairs.insert(
                0, (temp_motion, contained_path(asset_root, motion_source_relative))
            )
        for source, destination in promotion_pairs:
            if source.is_dir():
                destination.mkdir(parents=True, exist_ok=False)
                promoted.append(destination)
                for child in source.iterdir():
                    _promote(child, destination / child.name)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                _promote(source, destination)
                promoted.append(destination)
        source_artifacts = (
            _motion_source_artifacts(motion_model, motion_report, motion_source_relative)
            if adding_motion_roots
            else []
        )
        processor = Processor(
            name=PROCESSOR_NAME, version=f"{PROCESSOR_VERSION}+{adapter.get('blender_version')}"
        )
        model_artifact = Artifact(
            artifact_id=f"meshy_native_character_animated_model_{suffix}",
            role="processed_model",
            stage="processed",
            format="glb",
            path=model_relative,
            sha256=model_hash,
            size_bytes=model_size,
            derived_from=root_ids,
            processor=processor,
        )
        semantic_artifact = Artifact(
            artifact_id=f"meshy_native_motion_semantic_evidence_{suffix}",
            role="meshy_native_motion_semantic_evidence",
            stage="review",
            format="json",
            path=semantic_relative,
            sha256=semantic_hash,
            size_bytes=semantic_size,
            derived_from=sorted(MOTION_ROOTS),
            processor=processor,
        )
        playback_artifacts = tuple(
            Artifact(
                artifact_id=item["artifact_id"],
                role="meshy_native_character_motion_playback",
                stage="review",
                format="webp",
                path=item["path"],
                sha256=item["sha256"],
                size_bytes=item["size_bytes"],
                derived_from=[*root_ids, model_artifact.artifact_id],
                processor=processor,
            )
            for item in playback_descriptors
        )
        process_artifacts = [
            _process_artifact(
                "assembly",
                suffix,
                assembly_process_relative,
                assembly_process,
                root_ids,
                model_artifact.artifact_id,
                processor,
            ),
            _process_artifact(
                "playback",
                suffix,
                playback_process_relative,
                playback_process,
                root_ids,
                model_artifact.artifact_id,
                processor,
            ),
        ]
        report_artifact = Artifact(
            artifact_id=f"meshy_native_character_motion_report_{suffix}",
            role="meshy_native_character_motion_report",
            stage="review",
            format="json",
            path=report_relative,
            sha256=report_hash,
            size_bytes=report_size,
            derived_from=[
                *root_ids,
                model_artifact.artifact_id,
                semantic_artifact.artifact_id,
                *(item.artifact_id for item in playback_artifacts),
                *(item.artifact_id for item in process_artifacts),
            ],
            processor=processor,
        )
        targets = [
            *source_artifacts,
            model_artifact,
            semantic_artifact,
            *playback_artifacts,
            *process_artifacts,
            report_artifact,
        ]
        _verify_local(asset_root, targets)
        root_artifacts = [
            *by_id.values(),
            *(
                source_artifacts
                if adding_motion_roots
                else [motion_model, motion_report]
            ),
        ]
        revision = manifest.revision
        manifest.artifacts.extend(targets)
        manifest.validation.result = "not_run"
        manifest.validation.checks = []
        manifest.scale_calibration = ScaleCalibration()
        manifest.quality.observed = {}
        invalidate_approval(manifest)
        manifest.revision += 1
        manifest.asset.updated_at = utc_now()
        try:
            _verify_exact_root_union(asset_root, root_artifacts)
            rollback = False
            repository.save(
                manifest,
                "asset.meshy_native_character_motion_assembled",
                expected_revision=revision,
            )
        except BaseException:
            live = repository.load(asset_id)
            if _exact_target(live, manifest.revision, targets):
                diagnosis = repository.diagnose_pending_save(asset_id)
                if diagnosis.status in {"event_missing", "event_partial", "event_complete"}:
                    repository.reconcile_pending_save(asset_id)
            elif live.revision == revision and not _references(live, targets):
                rollback = True
                raise
            else:
                raise
        _verify_exact_root_union(asset_root, root_artifacts)
        _verify_local(asset_root, targets)
        return MeshyNativeCharacterMotionResult(
            model_artifact, report_artifact, semantic_artifact, playback_artifacts
        )
    except BaseException:
        if rollback:
            for path in reversed(promoted):
                shutil.rmtree(path, ignore_errors=True) if path.is_dir() else path.unlink(
                    missing_ok=True
                )
        raise
    finally:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)


def _run(config, runner, arguments, cwd, temporary, phase, executable, script):
    started_at = utc_now().isoformat()
    result = (runner or run_bounded_process)(
        arguments,
        cwd,
        _safe_environment(),
        config.tools.blender_timeout_seconds,
        config.tools.maximum_output_bytes,
    )
    if result.return_code or result.timed_out or result.output_limited:
        raise FoundryError(
            f"Meshy-native {phase} subprocess failed: {(result.stderr or result.stdout)[-2000:]}"
        )
    ended_at = utc_now().isoformat()
    return {
        "schema": "vandrel_foundry_bounded_process/1.0",
        "processor_name": f"{PROCESSOR_NAME}_{phase}",
        "processor_version": PROCESSOR_VERSION,
        "tool_version": "reported_in_bound_adapter",
        "logical_arguments": [
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            f"--phase={phase}",
        ],
        "return_code": result.return_code,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_seconds": result.duration_seconds,
        "timeout_seconds": config.tools.blender_timeout_seconds,
        "maximum_output_bytes": config.tools.maximum_output_bytes,
        "timed_out": result.timed_out,
        "output_limited": result.output_limited,
        "stdout": _redact(result.stdout, executable, script, cwd, temporary),
        "stderr": _redact(result.stderr, executable, script, cwd, temporary),
    }, result


def _write_process(path, value, _result):
    _write_new(path, json_bytes(value))
    digest, size = _hash(path)
    return {
        "phase": value["processor_name"].rsplit("_", 1)[-1],
        "sha256": digest,
        "size_bytes": size,
        "process": {key: item for key, item in value.items() if key not in {"stdout", "stderr"}},
    }


def _require_facts(facts):
    required = {
        "target_joint_count": 24,
        "source_joint_count": 24,
        "exact_native_joint_hierarchy_match": True,
        "semantic_transfer_policy": "native_joint_identity_global_pose_reconstruction",
        "index_or_mixamo_graft": False,
        "target_rest_translation_policy": (
            "preserve_target_rest_translations_and_bone_lengths"
        ),
        "target_pose_scale_policy": "identity_preserves_target_bone_lengths",
        "old_target_global_rest_postfactor_applied": False,
        "direct_matrix_basis_copy_applied": False,
        "bind_matrices_preserved": True,
        "material_texture_preserved": True,
        "skin_weight_policy": "deterministic_top4_normalized",
        "skin_weights_exactly_preserved": False,
        "top4_normalized": True,
        "preexport_unweighted_vertex_count": 0,
        "output_action_count": 10,
    }
    if any(facts.get(key) != value for key, value in required.items()):
        raise FoundryError("Meshy-native assembly facts violate the contract.")
    if facts.get("target_bind_matrix_signature_before") != facts.get(
        "target_bind_matrix_signature_after"
    ) or facts.get("target_material_signature_before") != facts.get(
        "target_material_signature_after"
    ):
        raise FoundryError("Meshy-native bind or material signature changed.")
    for key in (
        "maximum_sampled_global_orientation_delta_degrees",
        "maximum_sampled_parent_local_orientation_delta_degrees",
    ):
        value = facts.get(key)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) > 0.001
        ):
            raise FoundryError("Meshy-native H4 orientation reconstruction did not close.")


def _comparison():
    return {
        "basis": "visible_semantics_deformation_and_loopability",
        "eating": {
            "selected": "target_character|019fe8ca-a6c4-7968-822f-92efebbab5a4",
            "retained_alternative": "target_character|019fe8c8-1952-7ce9-a611-33851c9cf0b2",
            "assessment": "stronger hand-to-mouth reach; non-looping and does not visibly prove chewing",
        },
        "butchering": {
            "selected": "target_character|019fe8d7-ed16-7b82-a594-728d821ee711",
            "retained_alternative": "target_character|019fe8d4-0feb-798a-bcbb-81126f26e17f",
            "assessment": "clearer forward ground-work reach; non-looping and does not visibly prove repeated cutting",
        },
        "clean_motion_claimed": False,
    }


def _runtime_gaps(names):
    return {
        "vandrel_ready": False,
        "available_named_locomotion": [
            name for name in names if name.endswith(("|Walking", "|Running"))
        ],
        "missing_required_motions": [
            "neutral_idle_loop",
            "death_or_fall_with_stable_held_final_pose",
        ],
        "smallest_provider_motion_request": [
            "one Meshy-native neutral standing idle loop",
            "one Meshy-native death/fall clip that settles into a stable held final pose",
        ],
        "substitution_policy": "do_not_substitute_unrelated_motion",
    }


def _encode_webp(root, clip, destination, duration):
    files = clip.get("frame_files")
    if not isinstance(files, list) or len(files) < 2:
        raise FoundryError("Meshy-native playback frames are incomplete.")
    images = []
    try:
        for name in files:
            path = contained_path(root, RelativeManifestPath(name))
            images.append(Image.open(path).convert("RGB"))
        total = round(duration * 1000)
        base, remainder = divmod(total, len(images))
        if base < 1:
            raise FoundryError("Meshy-native playback duration is too short.")
        durations = [base + (index < remainder) for index in range(len(images))]
        images[0].save(
            destination,
            format="WEBP",
            save_all=True,
            append_images=images[1:],
            duration=durations,
            loop=0,
            lossless=True,
        )
    finally:
        for image in images:
            image.close()


def _source_bindings(roots, model, report):
    values = [
        {
            "artifact_id": item.artifact_id,
            "role": item.role,
            "sha256": item.sha256,
            "size_bytes": item.size_bytes,
        }
        for item in roots
    ]
    values.extend(
        [
            {
                "artifact_id": "meshy_native_motion_model_root_001",
                "role": "meshy_native_motion_model",
                "origin_asset_id": "meshy_native_brukk_canary_001",
                "origin_artifact_id": model.artifact_id,
                "sha256": model.sha256,
                "size_bytes": model.size_bytes,
            },
            {
                "artifact_id": "meshy_native_motion_report_root_001",
                "role": "meshy_native_motion_report",
                "origin_asset_id": "meshy_native_brukk_canary_001",
                "origin_artifact_id": report.artifact_id,
                "sha256": report.sha256,
                "size_bytes": report.size_bytes,
            },
        ]
    )
    return values


def _motion_source_artifacts(model, report, root):
    processor = Processor(name="local_meshy_native_motion_contribution_intake", version="1")
    return [
        Artifact(
            artifact_id="meshy_native_motion_model_root_001",
            role="meshy_native_motion_model",
            stage="source",
            format="glb",
            path=f"{root}/canary.glb",
            sha256=model.sha256,
            size_bytes=model.size_bytes,
            processor=processor,
        ),
        Artifact(
            artifact_id="meshy_native_motion_report_root_001",
            role="meshy_native_motion_report",
            stage="source",
            format="json",
            path=f"{root}/canary-report.json",
            sha256=report.sha256,
            size_bytes=report.size_bytes,
            processor=processor,
        ),
    ]


def _process_artifact(phase, suffix, path, value, roots, model_id, processor):
    return Artifact(
        artifact_id=f"meshy_native_character_motion_{phase}_process_log_{suffix}",
        role="meshy_native_character_motion_process_log",
        stage="processing",
        format="json",
        path=path,
        sha256=value["sha256"],
        size_bytes=value["size_bytes"],
        derived_from=[*roots, model_id],
        processor=processor,
    )


def _artifact(manifest, artifact_id):
    values = [item for item in manifest.artifacts if item.artifact_id == artifact_id]
    if len(values) != 1:
        raise FoundryError(f"Missing exact Meshy-native canary artifact: {artifact_id}")
    return values[0]


def _animation_names(path):
    animations = load_glb_document(path).get("animations", [])
    names = [item.get("name") for item in animations if isinstance(item, dict)]
    if len(names) != len(animations) or any(not isinstance(name, str) for name in names):
        raise FoundryError("Assembled GLB has invalid animation names.")
    return names


def _load_json(path, label):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FoundryError(f"{label} is unreadable: {exc}") from exc


def _verify_inputs(paths, by_id, external):
    for key, artifact in by_id.items():
        _verify(paths[key], artifact)
    for path, artifact in external.values():
        _verify(path, artifact)


def _verify_local(root, artifacts):
    for artifact in artifacts:
        _verify(contained_path(root, artifact.path), artifact)


def _verify_exact_root_union(root, artifacts):
    ids = [artifact.artifact_id for artifact in artifacts]
    if len(ids) != 6 or len(set(ids)) != 6 or set(ids) != CHARACTER_ROOTS | MOTION_ROOTS:
        raise FoundryError("Meshy-native motion save requires the exact six-root union.")
    _verify_local(root, artifacts)


def _verify(path, artifact):
    if not path.is_file() or _hash(path) != (artifact.sha256, artifact.size_bytes):
        raise FoundryError(f"Meshy-native motion input/output changed: {artifact.artifact_id}")


def _hash(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _copy_new(source, destination):
    with source.open("rb") as first, destination.open("xb") as second:
        shutil.copyfileobj(first, second, 1024 * 1024)
        second.flush()
        os.fsync(second.fileno())


def _write_new(path, value):
    with path.open("xb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def _promote(source, destination):
    try:
        os.link(source, destination)
    except FileExistsError as exc:
        raise FoundryError(
            f"Meshy-native motion destination appeared concurrently: {destination}"
        ) from exc


def _exact_target(manifest, revision, artifacts):
    return manifest.revision == revision and _references(manifest, artifacts)


def _references(manifest, artifacts):
    values = {item.artifact_id: item for item in manifest.artifacts}
    return all(
        values.get(item.artifact_id) is not None
        and values[item.artifact_id].model_dump(mode="json") == item.model_dump(mode="json")
        for item in artifacts
    )


def _redact(value, *paths):
    for path in sorted((str(item) for item in paths), key=len, reverse=True):
        value = value.replace(path, "<local-path>").replace(path.replace("\\", "/"), "<local-path>")
    value = re.sub(r"(?i)[a-z]:[\\/][^\r\n]*", "<local-path>", value)
    return re.sub(
        r"(?i)(authorization\s*:\s*bearer|api[_-]?key|token|secret)\s*[=:]\s*\S+",
        r"\1=<redacted>",
        value,
    )


def _safe_environment():
    allowed = {
        "APPDATA",
        "HOME",
        "LOCALAPPDATA",
        "PATH",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    }
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}
