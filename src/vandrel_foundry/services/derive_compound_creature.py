import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.compound_creature import (
    CompoundContribution,
    CompoundCreatureReport,
    CompoundOutput,
    ContributionRole,
)
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, ScaleCalibration, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.domain.workflow_policy import invalidate_approval, transition_workflow
from vandrel_foundry.services.inspect_glb import inspect_glb
from vandrel_foundry.services.validate_godot import ProcessRunner, run_bounded_process
from vandrel_foundry.storage.atomic import json_bytes
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path

PROCESSOR_NAME = "blender_compound_creature_derivation"
PROCESSOR_VERSION = "1"
REQUIRED_ROLES = frozenset(
    {"mesh_material_source", "material_dependency", "rig_animation_donor"}
)
ALLOWED_STATES = {
    WorkflowState.DOWNLOADED,
    WorkflowState.PROCESSED,
    WorkflowState.STAGED,
    WorkflowState.REVIEW,
    WorkflowState.APPROVED,
}


@dataclass(frozen=True)
class CompoundCreatureResult:
    model: Artifact
    report: Artifact


def derive_compound_creature(
    config: FoundryConfig,
    asset_id: str,
    contributions: list[tuple[ContributionRole, str]],
    runner: ProcessRunner | None = None,
) -> CompoundCreatureResult:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.asset.lane != "creature":
        raise FoundryError("Compound creature derivation requires the creature lane.")
    if manifest.workflow.state not in ALLOWED_STATES:
        raise FoundryError("Compound creature derivation requires downloaded immutable sources.")
    selected = _preflight(manifest.artifacts, contributions)
    executable = config.tools.blender_executable
    if executable is None or not executable.is_absolute() or not executable.is_file():
        raise FoundryError("Configure tools.blender_executable as an existing absolute file.")
    asset_root = repository.asset_directory(asset_id)
    bindings: list[tuple[ContributionRole, Artifact, Path]] = []
    for role, artifact in selected:
        path = contained_path(asset_root, artifact.path)
        _verify(path, artifact)
        bindings.append((role, artifact, path))

    number = (
        sum(
            item.role == "processed_model"
            and item.processor is not None
            and item.processor.name == PROCESSOR_NAME
            for item in manifest.artifacts
        )
        + 1
    )
    model_id = f"compound_creature_model_{number:03d}"
    model_relative = RelativeManifestPath(f"processed/compound_creature/{model_id}.glb")
    report_relative = RelativeManifestPath(f"reports/compound-creature-{number:03d}.json")
    model_path = contained_path(asset_root, model_relative)
    report_path = contained_path(asset_root, report_relative)
    if model_path.exists() or report_path.exists():
        raise FoundryError("Compound creature output or report destination already exists.")

    script = Path(__file__).parents[1] / "blender" / "derive_compound_creature.py"
    temporary_root: Path | None = None
    promoted: list[Path] = []
    rollback_promoted = True
    try:
        temporary_root = Path(tempfile.mkdtemp(prefix=".compound-creature-", dir=asset_root))
        temporary_model = temporary_root / "model.glb"
        adapter_report = temporary_root / "adapter-report.json"
        by_role = {role: path for role, _, path in bindings}
        material_paths = [path for role, _, path in bindings if role == "material_dependency"]
        arguments = [
            str(executable), "--background", "--factory-startup", "--disable-autoexec",
            "--python-exit-code", "1", "--python", str(script), "--",
            str(by_role["mesh_material_source"]), str(by_role["rig_animation_donor"]),
            str(temporary_model), str(adapter_report), *(str(path) for path in material_paths),
        ]
        result = (runner or run_bounded_process)(
            arguments, asset_root, _safe_environment(), config.tools.blender_timeout_seconds,
            config.tools.maximum_output_bytes,
        )
        if result.return_code != 0 or result.timed_out or result.output_limited:
            raise FoundryError("Bounded Blender compound creature derivation failed.")
        if not temporary_model.is_file() or not adapter_report.is_file():
            raise FoundryError("Blender did not create compound model and adapter report.")
        adapter = json.loads(adapter_report.read_text(encoding="utf-8"))
        if not isinstance(adapter.get("tool_version"), str) or not isinstance(
            adapter.get("transformation_facts"), dict
        ):
            raise FoundryError("Compound creature adapter report is invalid.")
        for _, artifact, path in bindings:
            _verify(path, artifact)
        inspection = inspect_glb(temporary_model)
        if (
            inspection.mesh_count < 1
            or inspection.material_count < 1
            or inspection.skin_count != 1
            or inspection.joint_count < 1
            or inspection.animation_count < 1
        ):
            raise FoundryError("Compound GLB fails geometry, material, skin, joint, or animation gates.")
        facts = adapter["transformation_facts"]
        expected = {
            "donor_armatures_retained": 1,
            "material_dependencies_declared": len(material_paths),
            "material_dependencies_used": len(material_paths),
            "animations_exported": True,
            "unweighted_exported_vertex_count": 0,
        }
        if any(facts.get(key) != value for key, value in expected.items()):
            raise FoundryError("Compound adapter facts do not reconcile with declared inputs.")
        if facts.get("output_skin_count") != inspection.skin_count or facts.get(
            "output_animation_count"
        ) != inspection.animation_count:
            raise FoundryError("Compound adapter facts do not reconcile with GLB inspection.")
        model_hash, model_size = _hash_file(temporary_model)
        report = CompoundCreatureReport(
            schema="vandrel_foundry_compound_creature/1.0",
            processor_name=PROCESSOR_NAME,
            processor_version=PROCESSOR_VERSION,
            tool_version=adapter["tool_version"],
            arguments=_logical_arguments(bindings, model_relative, report_relative),
            contributions=[
                CompoundContribution(
                    artifact_id=artifact.artifact_id, path=artifact.path,
                    sha256=artifact.sha256, size_bytes=artifact.size_bytes, role=role,
                )
                for role, artifact, _ in bindings
            ],
            contribution_union=sorted(artifact.artifact_id for _, artifact, _ in bindings),
            transformation_facts={
                **facts,
                "independent_glb_inspection": inspection.__dict__,
            },
            output=CompoundOutput(
                artifact_id=model_id, path=model_relative, sha256=model_hash, size_bytes=model_size
            ),
        )
        temporary_report = temporary_root / "report.json"
        _write_new(temporary_report, json_bytes(report.model_dump(mode="json", by_alias=True)))
        report_hash, report_size = _hash_file(temporary_report)
        model_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        _promote_new(temporary_model, model_path); promoted.append(model_path)
        _promote_new(temporary_report, report_path); promoted.append(report_path)

        processor = Processor(name=PROCESSOR_NAME, version=f"{PROCESSOR_VERSION}+{adapter['tool_version']}")
        roots = [artifact.artifact_id for _, artifact, _ in bindings]
        model = Artifact(
            artifact_id=model_id, role="processed_model", stage="processed", format="glb",
            path=model_relative, sha256=model_hash, size_bytes=model_size,
            derived_from=roots, processor=processor,
        )
        report_artifact = Artifact(
            artifact_id=f"compound_creature_report_{number:03d}",
            role="compound_creature_derivation_report", stage="processing", format="json",
            path=report_relative, sha256=report_hash, size_bytes=report_size,
            derived_from=[*roots, model_id], processor=processor,
        )
        manifest.artifacts.extend([model, report_artifact])
        transition_workflow(manifest, WorkflowState.PROCESSED)
        manifest.validation.result = "not_run"; manifest.validation.checks = []
        manifest.scale_calibration = ScaleCalibration()
        manifest.quality.observed = {}
        invalidate_approval(manifest)
        source_revision = manifest.revision
        manifest.revision += 1; manifest.asset.updated_at = utc_now()
        try:
            rollback_promoted = False
            repository.save(
                manifest,
                "asset.compound_creature_derived",
                expected_revision=manifest.revision - 1,
            )
        except BaseException:
            live = repository.load(asset_id)
            if _is_exact_committed_target(live, manifest.revision, model, report_artifact):
                diagnosis = repository.diagnose_pending_save(asset_id)
                if diagnosis.status in {"event_missing", "event_partial", "event_complete"}:
                    repository.reconcile_pending_save(asset_id)
            elif (
                live.revision == source_revision
                and not _references_artifacts(live.artifacts, model, report_artifact)
            ):
                rollback_promoted = True
                raise
            else:
                raise
        return CompoundCreatureResult(model=model, report=report_artifact)
    except BaseException:
        if rollback_promoted:
            for path in promoted:
                path.unlink(missing_ok=True)
        raise
    finally:
        if temporary_root is not None:
            shutil.rmtree(temporary_root, ignore_errors=True)


def _preflight(artifacts: list[Artifact], contributions: list[tuple[ContributionRole, str]]) -> list[tuple[ContributionRole, Artifact]]:
    roles = [role for role, _ in contributions]
    ids = [artifact_id for _, artifact_id in contributions]
    if (
        roles.count("mesh_material_source") != 1
        or roles.count("rig_animation_donor") != 1
        or roles.count("material_dependency") < 1
        or set(roles) != REQUIRED_ROLES
    ):
        raise FoundryError("Compound creature roles require one mesh, materials, and one donor.")
    if len(set(ids)) != len(ids):
        raise FoundryError("Compound creature contributions must be distinct artifacts.")
    roots = [item for item in artifacts if item.stage == "source" and not item.derived_from]
    if set(ids) != {item.artifact_id for item in roots}:
        raise FoundryError("Declared contributions must equal the complete current root source union.")
    by_id = {item.artifact_id: item for item in artifacts}
    selected = []
    for role, artifact_id in contributions:
        artifact = by_id.get(artifact_id)
        if artifact is None or artifact.stage != "source" or artifact.derived_from:
            raise FoundryError(f"Contribution must be an immutable root source artifact: {artifact_id}")
        selected.append((role, artifact))
    _validate_formats(selected)
    return selected


def _validate_formats(selected: list[tuple[ContributionRole, Artifact]]) -> None:
    allowed = {
        "mesh_material_source": {"fbx", "glb", "gltf"},
        "material_dependency": {"png", "jpg", "jpeg"},
        "rig_animation_donor": {"glb", "gltf"},
    }
    for role, artifact in selected:
        if artifact.format.lower() not in allowed[role]:
            raise FoundryError(f"Unsupported {role} format: {artifact.format}")


def _verify(path: Path, artifact: Artifact) -> None:
    digest, size = _hash_file(path)
    if digest != artifact.sha256 or size != artifact.size_bytes:
        raise FoundryError(f"Compound creature input changed: {artifact.artifact_id}")


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256(); size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk); size += len(chunk)
    return digest.hexdigest(), size


def _write_new(path: Path, value: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(value); stream.flush(); os.fsync(stream.fileno())


def _promote_new(source: Path, destination: Path) -> None:
    """Create a same-volume destination without overwrite; operation cleanup owns source."""
    try:
        os.link(source, destination)
    except FileExistsError as exc:
        raise FoundryError(f"Compound creature destination appeared concurrently: {destination}") from exc
    except OSError as exc:
        raise FoundryError(f"Could not promote compound creature output: {exc}") from exc


def _logical_arguments(
    bindings: list[tuple[ContributionRole, Artifact, Path]],
    output: RelativeManifestPath,
    report: RelativeManifestPath,
) -> list[str]:
    values = ["--background", "--factory-startup", "--disable-autoexec", "--python-exit-code=1"]
    for role, artifact, _ in bindings:
        values.append(f"--{role.replace('_', '-')}={artifact.artifact_id}")
    return [*values, f"--output-role=processed_model:{output}", f"--report-role=compound_creature_derivation_report:{report}"]


def _is_exact_committed_target(
    live, revision: int, model: Artifact, report: Artifact
) -> bool:
    return live.revision == revision and _references_artifacts(live.artifacts, model, report)


def _references_artifacts(artifacts: list[Artifact], model: Artifact, report: Artifact) -> bool:
    by_id = {item.artifact_id: item for item in artifacts}
    return all(
        by_id.get(expected.artifact_id) is not None
        and by_id[expected.artifact_id].model_dump(mode="json") == expected.model_dump(mode="json")
        for expected in (model, report)
    )


def _safe_environment() -> dict[str, str]:
    allowed = {"APPDATA", "HOME", "LOCALAPPDATA", "PATH", "SYSTEMDRIVE", "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE", "WINDIR"}
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}
