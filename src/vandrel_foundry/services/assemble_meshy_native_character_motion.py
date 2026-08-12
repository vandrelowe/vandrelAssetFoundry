import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PIL import Image

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, ScaleCalibration, utc_now
from vandrel_foundry.domain.meshy_native_character_motion import (
    SEMANTIC_MAPPING,
    MeshyNativeCharacterMotionReport,
    MeshyNativeMotionSemanticEvidence,
)
from vandrel_foundry.domain.meshy_native_multi_motion import (
    MeshyNativeMultiMotionIntakeReport,
)
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.domain.workflow_policy import invalidate_approval
from vandrel_foundry.services.add_meshy_native_character_package import (
    API_CHARACTER_SOURCE,
    LEGACY_CHARACTER_SOURCE,
    resolve_meshy_native_character_source,
)
from vandrel_foundry.services.add_meshy_native_multi_motion_package import (
    ROOT_IDS as MULTI_ROOT_IDS,
)
from vandrel_foundry.services.add_meshy_native_multi_motion_package import package_identity
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
PROCESSOR_VERSION = "5"
CHARACTER_ROOTS = set(LEGACY_CHARACTER_SOURCE.root_ids)
API_CHARACTER_ROOTS = set(API_CHARACTER_SOURCE.root_ids)
MOTION_ROOTS = {
    "meshy_native_motion_model_root_001",
    "meshy_native_motion_report_root_001",
}
BASE_ROOTS = CHARACTER_ROOTS | MOTION_ROOTS
EXTENDED_ROOTS = BASE_ROOTS | set(MULTI_ROOT_IDS)


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
    playback_profile: Literal["release_review", "representative_batch"] = "release_review",
) -> MeshyNativeCharacterMotionResult:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.asset.lane != "humanoid" or manifest.workflow.state is not WorkflowState.PROCESSED:
        raise FoundryError("Meshy-native character motion assembly requires a processed humanoid.")
    current_roots = [
        item for item in manifest.artifacts if item.stage == "source" and not item.derived_from
    ]
    profile, character_root_by_id, texture_artifact = resolve_meshy_native_character_source(
        manifest.artifacts
    )
    character_root_ids = set(profile.root_ids)
    asset_root = repository.asset_directory(asset_id)
    current_root_ids = {item.artifact_id for item in current_roots}
    multi_packages = _load_multi_packages(asset_root, manifest)
    multi_root_ids = set().union(
        *(identity.root_ids for identity, _report, _artifacts in multi_packages)
    )
    allowed_root_unions = {
        frozenset(character_root_ids),
        frozenset(character_root_ids | MOTION_ROOTS),
        frozenset(character_root_ids | multi_root_ids),
        frozenset(character_root_ids | MOTION_ROOTS | multi_root_ids),
    }
    if frozenset(current_root_ids) not in allowed_root_unions:
        raise FoundryError(
            "Meshy-native character motion assembly requires the exact four character roots "
            "the established six-root union, or that union plus complete numbered motion packages."
        )
    by_id = {**character_root_by_id, texture_artifact.artifact_id: texture_artifact}
    paths = {key: contained_path(asset_root, item.path) for key, item in by_id.items()}
    motion_root_presence = current_root_ids & MOTION_ROOTS
    if motion_root_presence and motion_root_presence != MOTION_ROOTS:
        raise FoundryError("Meshy-native character motion roots are incomplete.")
    adding_motion_roots = not motion_root_presence
    extended_motion = bool(multi_packages)
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
    multi_by_id: dict[str, Artifact] = {}
    multi_report_data: list[MeshyNativeMultiMotionIntakeReport] = []
    if extended_motion:
        for identity, report, artifacts in multi_packages:
            package_roots = {
                item.artifact_id: item
                for item in artifacts
                if item.artifact_id in identity.root_ids
            }
            _require_multi_root_roles(package_roots, identity)
            multi_by_id.update(package_roots)
            multi_report_data.append(report)
    _verify_inputs(paths, by_id, external)
    _verify_local(asset_root, list(multi_by_id.values()))
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
        extension_manifest = None
        if extended_motion:
            if not multi_report_data:
                raise FoundryError("Meshy multi-motion intake evidence is unavailable.")
            extension_manifest = temporary / "multi-motion-entries.json"
            extension_entries = []
            for package in multi_report_data:
                for entry in package.entries:
                    if entry.role != "meshy_native_multi_animation_fbx":
                        continue
                    artifact = multi_by_id[entry.artifact_id]
                    if (artifact.sha256, artifact.size_bytes) != (
                        entry.sha256,
                        entry.size_bytes,
                    ):
                        raise FoundryError(
                            "Meshy multi-motion intake entry does not match its root artifact."
                        )
                    extension_entries.append(
                        {
                            "artifact_id": artifact.artifact_id,
                            "exact_export_name": entry.exact_export_name,
                            "runtime_eligibility": entry.runtime_eligibility,
                            "source_package_number": package.package_number,
                            "source_qualifier": package.source_qualifier,
                            "path": str(contained_path(asset_root, artifact.path)),
                        }
                    )
            _write_new(extension_manifest, json_bytes({"entries": extension_entries}))
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
            str(paths[texture_artifact.artifact_id]),
            str(temp_motion_model),
            str(temp_reference),
            str(temp_model),
            str(adapter_report),
        ]
        if extension_manifest is not None:
            assembly_args.append(str(extension_manifest))
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
        expected_adapter_schemas = (
            {
                "vandrel_foundry_meshy_native_character_assembly_adapter/4.0",
                "vandrel_foundry_meshy_native_character_assembly_adapter/5.0",
            }
            if extended_motion and len(multi_report_data) == 1
            else {
                "vandrel_foundry_meshy_native_character_assembly_adapter/5.0"
                if extended_motion
                else "vandrel_foundry_meshy_native_character_assembly_adapter/3.0"
            }
        )
        if adapter.get("schema") not in expected_adapter_schemas:
            raise FoundryError("Meshy-native assembly adapter report is invalid.")
        facts = adapter.get("transformation_facts")
        clips = adapter.get("clips")
        if not isinstance(facts, dict) or not isinstance(clips, list):
            raise FoundryError("Meshy-native assembly adapter report is incomplete.")
        names = [item.get("exact_name") for item in clips if isinstance(item, dict)]
        if len(names) != len(clips) or any(not isinstance(name, str) for name in names):
            raise FoundryError("Meshy-native assembly action inventory is invalid.")
        if len(set(names)) != len(names):
            raise FoundryError("Meshy-native assembly emitted duplicate runtime action names.")
        expected_extension_entries = sum(
            package.animation_entry_count for package in multi_report_data
        )
        expected_compatible_entries = sum(
            entry.runtime_eligibility == "identity_normalized"
            for package in multi_report_data
            for entry in package.entries
            if entry.role == "meshy_native_multi_animation_fbx"
        )
        _require_facts(
            facts,
            len(names),
            extended_motion,
            expected_extension_entries,
            expected_compatible_entries,
        )
        canary_data = _load_json(temp_motion_report, "Meshy-native canary report")
        canary_clips = canary_data.get("clips")
        if not isinstance(canary_clips, list) or len(canary_clips) != 10:
            raise FoundryError("Bound canary report has an invalid clip inventory.")
        canary_durations = {
            item["exact_name"]: float(item["duration_seconds"]) for item in canary_clips
        }
        clip_durations = {
            item["exact_name"]: float(item["duration_seconds"]) for item in clips
        }
        duration_deltas = {
            name: abs(clip_durations.get(name, math.inf) - duration)
            for name, duration in canary_durations.items()
        }
        if any(value > 0.002 for value in duration_deltas.values()):
            raise FoundryError(
                "Base action names or durations do not match the bound canary report: "
                f"duration_deltas={duration_deltas}."
            )
        extension_entries = adapter.get("extension_entries", [])
        collisions = adapter.get("collisions", [])
        if extended_motion:
            _require_multi_extension(
                extension_entries,
                collisions,
                facts,
                names,
                multi_report_data,
            )
        elif extension_entries or collisions or len(names) != 10:
            raise FoundryError("Base Meshy-native assembly unexpectedly contains extensions.")
        inspection = inspect_glb(temp_model)
        if (
            inspection.mesh_count < 1
            or inspection.material_count < 1
            or inspection.image_count < 1
            or inspection.skin_count != 1
            or inspection.joint_count != 24
            or inspection.animation_count != len(names)
            or set(_animation_names(temp_model)) != set(names)
        ):
            raise FoundryError(
                "Assembled Meshy-native character failed independent GLB inspection."
            )
        reference_skin = inspect_top4_glb_skin(temp_reference)
        output_skin = inspect_top4_glb_skin(temp_model)
        require_matching_top4_skin(
            reference_skin,
            output_skin,
            texture_artifact.sha256,
        )

        playback_names = _playback_names(
            names,
            extended_motion,
            extension_entries,
            playback_profile,
        )
        durations = {name: clip_durations[name] for name in playback_names}
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
            or len(playback_clips) != len(durations)
        ):
            raise FoundryError("Meshy-native playback adapter report is invalid.")
        output_skin = inspect_top4_glb_skin(temp_model)
        require_matching_top4_skin(
            reference_skin,
            output_skin,
            texture_artifact.sha256,
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
        base_root_ids = character_root_ids | MOTION_ROOTS
        root_ids = sorted(base_root_ids | multi_root_ids if extended_motion else base_root_ids)
        report = MeshyNativeCharacterMotionReport(
            schema=(
                "vandrel_foundry_meshy_native_character_motion/1.4"
                if playback_profile == "representative_batch"
                else
                "vandrel_foundry_meshy_native_character_motion/1.3"
                if extended_motion and len(multi_report_data) > 1
                else "vandrel_foundry_meshy_native_character_motion/1.2"
                if extended_motion
                else "vandrel_foundry_meshy_native_character_motion/1.1"
            ),
            asset_id=asset_id,
            processor={
                "name": PROCESSOR_NAME,
                "version": PROCESSOR_VERSION,
                "tool_version": adapter.get("blender_version"),
            },
            source_union=root_ids,
            source_bindings=_source_bindings(
                [*character_root_by_id.values(), *multi_by_id.values()],
                motion_model,
                motion_report,
            ),
            semantic_evidence={
                "artifact_id": f"meshy_native_motion_semantic_evidence_{suffix}",
                "sha256": semantic_hash,
                "observation_basis": "user_observed_provider_metadata",
            },
            transformation_facts={
                **facts,
                "playback_evidence_profile": playback_profile,
                "independent_glb_inspection": inspection.__dict__,
                "independent_top4_reference_skin": reference_skin.__dict__,
                "independent_final_top4_skin": output_skin.__dict__,
                "independent_top4_reference_match": True,
                "source_animation_entry_count": (
                    10 + expected_extension_entries if extended_motion else 10
                ),
                "compatible_source_animation_entry_count": (
                    10 + expected_compatible_entries if extended_motion else 10
                ),
                "final_unique_runtime_action_count": len(names),
                "extension_package_count": len(multi_report_data),
            },
            clips=clips,
            playback=playback_descriptors,
                comparison=(
                    _comparison(collisions) if extended_motion else _comparison()
                ),
            runtime_readiness=_runtime_gaps(names, extended_motion),
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
        _verify_local(asset_root, list(multi_by_id.values()))
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
            *character_root_by_id.values(),
            *multi_by_id.values(),
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
            _verify_exact_root_union(asset_root, root_artifacts, set(root_ids))
            _verify_local(asset_root, [texture_artifact])
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
        _verify_exact_root_union(asset_root, root_artifacts, set(root_ids))
        _verify_local(asset_root, [texture_artifact])
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


def _require_facts(
    facts,
    expected_action_count,
    extended,
    expected_extension_entries=0,
    expected_compatible_entries=0,
):
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
        "output_action_count": expected_action_count,
    }
    if any(facts.get(key) != value for key, value in required.items()):
        raise FoundryError("Meshy-native assembly facts violate the contract.")
    if extended:
        extended_required = {
            "base_action_count": 10,
            "extension_source_entry_count": expected_extension_entries,
            "extension_compatible_entry_count": expected_compatible_entries,
            "extension_provenance_only_entry_count": (
                expected_extension_entries - expected_compatible_entries
            ),
        }
        if any(facts.get(key) != value for key, value in extended_required.items()):
            raise FoundryError("Meshy-native extended assembly facts violate the contract.")
        if facts.get("runtime_deduplicated_collision_count", 0) + facts.get(
            "runtime_source_qualified_collision_count", 0
        ) != facts.get("runtime_collision_count"):
            raise FoundryError("Meshy-native collision accounting is incomplete.")
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


def _require_multi_extension(entries, collisions, facts, names, packages):
    expected_entries = sum(package.animation_entry_count for package in packages)
    if not isinstance(entries, list) or len(entries) != expected_entries:
        raise FoundryError("Meshy multi-motion entry evidence is incomplete.")
    if not isinstance(collisions, list):
        raise FoundryError("Meshy multi-motion collision evidence is incomplete.")
    compatible = [
        item for item in entries if item.get("runtime_eligibility") == "identity_normalized"
    ]
    excluded = [
        item
        for item in entries
        if item.get("runtime_eligibility") == "provenance_only_legacy_outlier"
    ]
    expected_compatible = sum(
        entry.runtime_eligibility == "identity_normalized"
        for package in packages
        for entry in package.entries
        if entry.role == "meshy_native_multi_animation_fbx"
    )
    if len(compatible) != expected_compatible or any(
        item.get("exact_export_name") != "019fee70-fd9d-7b6e-914a-d6dad2a49eeb"
        for item in excluded
    ):
        raise FoundryError("Meshy multi-motion compatibility partition is invalid.")
    for package in packages:
        rest_signatures = {
            item.get("rest_signature")
            for item in compatible
            if item.get("source_package_number", 1) == package.package_number
        }
        if len(rest_signatures) != 1 or None in rest_signatures:
            raise FoundryError("Meshy multi-motion package rest signatures differ.")
    if any(abs(float(item.get("container_rotation_degrees", math.inf))) > 0.01 for item in compatible):
        raise FoundryError("Meshy multi-motion compatible container is not identity-normalized.")
    for item in excluded:
        legacy_angle = float(item.get("container_rotation_degrees", 0.0))
        if not 89.0 <= legacy_angle <= 91.0 or item.get("runtime_action_name") is not None:
            raise FoundryError("Meshy multi-motion legacy outlier was not excluded correctly.")
    for item in collisions:
        if (
            item.get("selected_runtime_action_name") not in names
            or item.get("resolution")
            not in {
                "deduplicated_identical",
                "deduplicated_identical_curve",
                "source_qualified_alternative",
            }
        ):
            raise FoundryError("Meshy multi-motion collision resolution is invalid.")
        if item["resolution"] in {
            "deduplicated_identical",
            "deduplicated_identical_curve",
        }:
            if item.get("retained_alternative_action_name") is not None:
                raise FoundryError("Identical Meshy collision retained a duplicate action.")
        else:
            qualifier = item.get("source_qualifier") or (
                "fc7f5947" if len(packages) == 1 else None
            )
            if qualifier is None:
                raise FoundryError("Meshy collision source qualifier is missing.")
            expected = (
                f"target_character|multi_{qualifier}|"
                f"{item['exact_export_name']}"
            )
            if item.get("retained_alternative_action_name") != expected or expected not in names:
                raise FoundryError("Materially different Meshy collision lost its stable ID.")
    minimum_names = 25 if len(packages) == 1 else 29
    if facts.get("output_action_count") != len(names) or len(names) < minimum_names:
        raise FoundryError("Meshy multi-motion final unique action count is invalid.")


def _playback_names(names, extended, entries=None, profile="release_review"):
    if not extended:
        return names
    if profile == "representative_batch":
        work_name = next(
            (
                name
                for name in (
                    "target_character|Pull_Radish",
                    "target_character|Collect_Object",
                )
                if name in names
            ),
            None,
        )
        selected = [
            "target_character|Idle_6",
            "target_character|Walking",
            work_name,
        ]
        missing = [name for name in selected if not isinstance(name, str) or name not in names]
        if missing:
            raise FoundryError(
                f"Meshy representative batch playback is missing: {missing}."
            )
        return [name for name in selected if isinstance(name, str)]
    if profile != "release_review":
        raise FoundryError(f"Unsupported Meshy-native playback evidence profile: {profile}")
    selected = [
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
    missing = [name for name in selected if name not in names]
    if missing:
        raise FoundryError(f"Meshy multi-motion proportional playback is missing: {missing}.")
    additions = []
    for item in entries or []:
        if item.get("source_package_number", 1) < 2:
            continue
        if item.get("collision_resolution") in {
            "deduplicated_identical",
            "deduplicated_identical_curve",
        }:
            continue
        name = item.get("runtime_action_name")
        if isinstance(name, str) and name in names and name not in selected and name not in additions:
            additions.append(name)
    return [*selected, *additions]


def _comparison(collisions=None):
    value = {
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
    if collisions is not None:
        value.update(
            {
                "default_idle": {
                    "selected": "target_character|Idle_6",
                    "policy": "user_directed_candidate_mapping",
                },
                "death": {
                    "selected": "target_character|Dead",
                    "runtime_policy": "play_once_then_hold_final_frame",
                    "motionless_final_ten_frame_plateau_required": False,
                },
                "lie_down_held_pose": {
                    "selected": "target_character|Stand_To_Side_Lying",
                    "classified_as_death": False,
                },
                "gender_policy": (
                    "female_prefix_is_provenance_only_and_does_not_restrict_humanoid_use"
                ),
                "provider_named_technical_mappings": {
                    "sleep_loop": "target_character|Sleep_Normally",
                    "drink": "target_character|Stand_and_Drink",
                    "mining_or_flint_placeholder": "target_character|Heavy_Hammer_Swing",
                    "gather_bend_pick_inspect": (
                        "target_character|Female_Bend_Over_Pick_Up_Inspect"
                    ),
                    "gather_pull_root": "target_character|Pull_Radish",
                },
                "explicitly_unmapped_ambiguous_clips": [
                    "target_character|Sumo_High_Pull",
                    "target_character|Attack",
                ],
                "collisions": collisions,
                "runtime_action_selection_authority": "user_directed_candidate_only",
            }
        )
    return value


def _runtime_gaps(names, extended):
    if extended:
        return {
            "vandrel_ready": False,
            "motion_set_ready": True,
            "available_named_locomotion": [
                name for name in names if name.endswith(("|Walking", "|Running"))
            ],
            "missing_required_motions": [],
            "death_runtime_policy": "play_once_then_hold_final_frame",
            "motionless_final_ten_frame_plateau_required": False,
            "remaining_gate": "Vandrel consumer validation and explicit adoption",
            "substitution_policy": "frozen_eat_butcher_and_explicit_collision_selection",
        }
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


def _load_multi_packages(asset_root, manifest):
    reports = sorted(
        (
            item
            for item in manifest.artifacts
            if item.role == "meshy_native_multi_motion_intake_report"
        ),
        key=lambda item: item.artifact_id,
    )
    by_id = {item.artifact_id: item for item in manifest.artifacts}
    result = []
    for number, report_artifact in enumerate(reports, start=1):
        _verify(contained_path(asset_root, report_artifact.path), report_artifact)
        report = MeshyNativeMultiMotionIntakeReport.model_validate(
            _load_json(
                contained_path(asset_root, report_artifact.path),
                "Meshy multi-motion intake report",
            )
        )
        identity = package_identity(number, report.animation_entry_count)
        if (
            report.package_number != number
            or report_artifact.artifact_id != identity.report_id
            or set(report_artifact.derived_from) != set(identity.root_ids)
        ):
            raise FoundryError("Meshy multi-motion package lineage is invalid.")
        roots = []
        for artifact_id in identity.root_ids:
            artifact = by_id.get(artifact_id)
            if artifact is None:
                raise FoundryError("Meshy multi-motion source root union is incomplete.")
            roots.append(artifact)
        _verify_local(asset_root, roots)
        result.append((identity, report, [*roots, report_artifact]))
    return result


def _require_multi_root_roles(roots, identity):
    if set(roots) != set(identity.root_ids):
        raise FoundryError("Meshy multi-motion package root union is incomplete.")
    archive = roots[identity.archive_id]
    texture = roots[identity.texture_id]
    if (archive.role, archive.format) != ("meshy_native_multi_motion_archive", "zip"):
        raise FoundryError("Meshy multi-motion archive root role is invalid.")
    if (texture.role, texture.format) != ("meshy_native_multi_motion_texture", "png"):
        raise FoundryError("Meshy multi-motion texture root role is invalid.")
    for artifact_id in identity.fbx_ids:
        artifact = roots[artifact_id]
        if (artifact.role, artifact.format) != ("meshy_native_multi_motion_fbx", "fbx"):
            raise FoundryError("Meshy multi-motion FBX root role is invalid.")


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


def _verify_exact_root_union(root, artifacts, expected):
    ids = [artifact.artifact_id for artifact in artifacts]
    authorized_bases = {
        frozenset(CHARACTER_ROOTS | MOTION_ROOTS),
        frozenset(API_CHARACTER_ROOTS | MOTION_ROOTS),
    }
    if set(ids) != expected or sum(base <= expected for base in authorized_bases) != 1:
        raise FoundryError("Meshy-native motion save requires an exact authorized root union.")
    if len(ids) != len(set(ids)):
        raise FoundryError("Meshy-native motion save root union contains duplicates.")
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
