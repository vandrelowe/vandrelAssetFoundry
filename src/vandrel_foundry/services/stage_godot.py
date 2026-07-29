import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.lanes import LaneConfiguration
from vandrel_foundry.domain.manifest import Artifact, Processor, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.domain.workflow_policy import transition_workflow
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path

STAGER_VERSION = "1"
PROJECT_TEXT = """; Generated validation sandbox. Not a Vandrel runtime project.
config_version=5

[application]
config/name="Vandrel Asset Foundry Validation"
run/main_scene="res://wrapper.tscn"

[rendering]
renderer/rendering_method="gl_compatibility"
"""
WRAPPER_TEXT = """[gd_scene load_steps=2 format=3]

[ext_resource type="PackedScene" path="res://model.glb" id="1_model"]

[node name="AssetValidationWrapper" type="Node3D"]

[node name="Model" parent="." instance=ExtResource("1_model")]
"""


def prepare_godot_sandbox(
    config: FoundryConfig,
    lanes: LaneConfiguration,
    asset_id: str,
) -> tuple[Artifact, Artifact]:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.workflow.state is not WorkflowState.PROCESSED:
        raise FoundryError(f"Godot staging requires processed state: {asset_id}")
    lane = lanes.lanes.get(manifest.asset.lane)
    if lane is None:
        raise FoundryError(f"Lane policy is unavailable: {manifest.asset.lane}")
    processed = [item for item in manifest.artifacts if item.role == "processed_model"]
    if not processed:
        raise FoundryError(f"No processed artifact exists: {asset_id}")
    source = processed[-1]
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    source_path = contained_path(asset_root, source.path)
    digest, size = _hash_file(source_path)
    if digest != source.sha256 or size != source.size_bytes:
        raise FoundryError(f"Processed artifact hash or size changed: {source.artifact_id}")

    directory_name = f"{source.artifact_id}-{source.sha256[:12]}"
    staging_root = asset_root / "godot_staging"
    final_directory = staging_root / directory_name
    if final_directory.exists():
        raise FoundryError(f"Godot staging directory already exists: {directory_name}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{directory_name}-", dir=staging_root))
    try:
        model_path = temporary / "model.glb"
        _copy_new(source_path, model_path)
        copied_digest, copied_size = _hash_file(model_path)
        if copied_digest != digest or copied_size != size:
            raise FoundryError("Staged model does not match its processed source.")
        _write_new_text(temporary / "project.godot", PROJECT_TEXT)
        _write_new_text(temporary / "wrapper.tscn", WRAPPER_TEXT)
        try:
            os.rename(temporary, final_directory)
        except FileExistsError as exc:
            raise FoundryError(f"Godot staging directory already exists: {directory_name}") from exc
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise

    model_number = sum(item.role == "godot_staged_model" for item in manifest.artifacts) + 1
    wrapper_number = sum(item.role == "godot_wrapper_scene" for item in manifest.artifacts) + 1
    project_number = sum(item.role == "godot_validation_project" for item in manifest.artifacts) + 1
    model_relative = RelativeManifestPath(f"godot_staging/{directory_name}/model.glb")
    wrapper_relative = RelativeManifestPath(f"godot_staging/{directory_name}/wrapper.tscn")
    project_relative = RelativeManifestPath(f"godot_staging/{directory_name}/project.godot")
    wrapper_digest, wrapper_size = _hash_file(contained_path(asset_root, wrapper_relative))
    project_digest, project_size = _hash_file(contained_path(asset_root, project_relative))
    processor = Processor(name="godot_sandbox_stager", version=STAGER_VERSION)
    model_artifact = Artifact(
        artifact_id=f"godot_staged_model_{model_number:03d}",
        role="godot_staged_model",
        stage="staged",
        format="glb",
        path=model_relative,
        sha256=copied_digest,
        size_bytes=copied_size,
        derived_from=[source.artifact_id],
        source_task_key=source.source_task_key,
        processor=processor,
    )
    wrapper_artifact = Artifact(
        artifact_id=f"godot_wrapper_scene_{wrapper_number:03d}",
        role="godot_wrapper_scene",
        stage="staged",
        format="tscn",
        path=wrapper_relative,
        sha256=wrapper_digest,
        size_bytes=wrapper_size,
        derived_from=[model_artifact.artifact_id],
        source_task_key=source.source_task_key,
        processor=processor,
    )
    project_artifact = Artifact(
        artifact_id=f"godot_validation_project_{project_number:03d}",
        role="godot_validation_project",
        stage="staged",
        format="godot",
        path=project_relative,
        sha256=project_digest,
        size_bytes=project_size,
        derived_from=[wrapper_artifact.artifact_id],
        source_task_key=source.source_task_key,
        processor=processor,
    )
    manifest.artifacts.extend([model_artifact, wrapper_artifact, project_artifact])
    manifest.quality.targets["collision_recommendation"] = lane.collision_policy
    transition_workflow(manifest, WorkflowState.STAGED)
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    repository.save(
        manifest,
        "godot.sandbox_staged",
        expected_revision=manifest.revision - 1,
    )
    return model_artifact, wrapper_artifact


def _copy_new(source: Path, destination: Path) -> None:
    try:
        with source.open("rb") as input_stream, destination.open("xb") as output_stream:
            while chunk := input_stream.read(1024 * 1024):
                output_stream.write(chunk)
            output_stream.flush()
            os.fsync(output_stream.fileno())
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise FoundryError(f"Could not stage model: {exc}") from exc


def _write_new_text(path: Path, value: str) -> None:
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        path.unlink(missing_ok=True)
        raise FoundryError(f"Could not create Godot sandbox file: {exc}") from exc


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise FoundryError(f"Could not hash staged input: {exc}") from exc
    return digest.hexdigest(), size
