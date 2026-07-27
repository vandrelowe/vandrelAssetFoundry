import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from vandrel_foundry.config import FoundryConfig, load_config, load_lanes
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.lanes import LaneConfiguration
from vandrel_foundry.domain.states import WorkflowState, next_actions
from vandrel_foundry.providers.meshy.http import MeshyHttpTransport
from vandrel_foundry.services.add_reference import add_reference_image
from vandrel_foundry.services.add_source import add_external_glb, add_external_package
from vandrel_foundry.services.apply_texture_mask import apply_texture_mask
from vandrel_foundry.services.audit_asset import audit_asset
from vandrel_foundry.services.audit_library import audit_library
from vandrel_foundry.services.build_review_gallery import build_review_gallery
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.doctor import run_doctor
from vandrel_foundry.services.download_artifact import download_text_preview_glb
from vandrel_foundry.services.experiment_semantic_mask import experiment_semantic_mask
from vandrel_foundry.services.experiment_shaders import experiment_shader_variants
from vandrel_foundry.services.graft_animations import graft_animations
from vandrel_foundry.services.init_library import initialize_asset_library
from vandrel_foundry.services.inspect_assets import discover_assets, initialize_workspace
from vandrel_foundry.services.inspect_glb import inspect_processed_glb
from vandrel_foundry.services.plan_release import plan_release
from vandrel_foundry.services.poll_task import poll_text_task
from vandrel_foundry.services.prepare_native_character import (
    prepare_provider_native_character,
)
from vandrel_foundry.services.process_asset import process_passthrough
from vandrel_foundry.services.process_blender import process_with_blender
from vandrel_foundry.services.publish_release import publish_release
from vandrel_foundry.services.quantize_semantic_mask import quantize_semantic_mask
from vandrel_foundry.services.reconcile_submission import reconcile_ambiguous_submission
from vandrel_foundry.services.render_animation_samples import render_animation_samples
from vandrel_foundry.services.render_missing_previews import render_missing_previews
from vandrel_foundry.services.render_preview import render_local_preview
from vandrel_foundry.services.retarget_animations import retarget_animations
from vandrel_foundry.services.review_animation_samples import accept_animation_samples
from vandrel_foundry.services.review_asset import (
    approval_checks_pass,
    approve_asset,
    reject_asset,
)
from vandrel_foundry.services.scan_sources import scan_source_directory
from vandrel_foundry.services.select_output import select_output
from vandrel_foundry.services.stage_godot import prepare_godot_sandbox
from vandrel_foundry.services.submit_preview import (
    submit_image_to_3d,
    submit_remesh,
    submit_retexture,
    submit_rigging,
    submit_text_preview,
    submit_text_refine,
)
from vandrel_foundry.services.validate_godot import validate_godot_sandbox
from vandrel_foundry.services.validate_humanoid_retarget import validate_humanoid_retarget
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath

app = typer.Typer(help="Vandrel Asset Foundry local manifest tools.", no_args_is_help=True)
console = Console()
error_console = Console(stderr=True)


def configured(path: Path | None) -> tuple[FoundryConfig, LaneConfiguration]:
    return load_config(path), load_lanes()


def fail(exc: Exception) -> None:
    error_console.print(f"[red]Error:[/red] {exc}")
    raise typer.Exit(1)


@app.command("init")
def initialize(
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Create the configured workspace directories without changing user files."""
    try:
        settings = load_config(config)
        initialize_workspace(settings.foundry.workspace_root)
        console.print(f"[green]Ready:[/green] {settings.foundry.workspace_root}")
    except FoundryError as exc:
        fail(exc)


@app.command("init-library")
def initialize_library(
    confirm_init: Annotated[
        bool,
        typer.Option(
            "--confirm-init",
            help="Confirm creation and baseline commit of the configured asset library.",
        ),
    ] = False,
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Create a new local Git/LFS asset library; never adopt an existing path."""
    if not confirm_init:
        fail(FoundryError("Asset-library initialization requires --confirm-init."))
    try:
        settings = load_config(config)
        result = initialize_asset_library(settings)
        console.print(f"[green]Asset library initialized[/green] {result.destination}")
        console.print("[yellow]No remote was configured and nothing was pushed.[/yellow]")
    except FoundryError as exc:
        fail(exc)


@app.command()
def doctor(
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Check Phase 1 configuration and local paths."""
    try:
        settings, lanes_config = configured(config)
        checks = run_doctor(settings, lanes_config)
    except FoundryError as exc:
        fail(exc)
    table = Table("Check", "Result", "Detail")
    for check in checks:
        table.add_row(
            check.name,
            "[green]OK[/green]" if check.ok else "[red]BLOCKED[/red]",
            check.detail,
        )
    console.print(table)
    if not all(check.ok for check in checks):
        raise typer.Exit(1)


@app.command()
def lanes(
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Display configured asset lanes."""
    try:
        _, lane_config = configured(config)
    except FoundryError as exc:
        fail(exc)
    table = Table("Lane", "Triangles", "Collision", "Skeleton", "Release")
    for lane_id, policy in lane_config.lanes.items():
        triangles = f"{policy.target_triangles or '-'} / {policy.maximum_triangles or '-'}"
        table.add_row(
            lane_id,
            triangles,
            policy.collision_policy,
            "yes" if policy.requires_skeleton else "no",
            "yes" if policy.release_enabled else "no",
        )
    console.print(table)


@app.command("create")
def create(
    asset_id: Annotated[str, typer.Option("--id")],
    lane: Annotated[str, typer.Option("--lane")],
    display_name: Annotated[str, typer.Option("--display-name")],
    prompt_file: Annotated[Path, typer.Option("--prompt-file")],
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Create a draft asset workspace; this never calls a provider."""
    try:
        settings, lane_config = configured(config)
        manifest = create_asset(
            settings,
            lane_config,
            asset_id,
            lane,
            display_name,
            prompt_file,
        )
        console.print(
            f"[green]Created[/green] {manifest.asset.asset_id} ({manifest.workflow.state.value})"
        )
    except FoundryError as exc:
        fail(exc)


@app.command("list")
def list_assets(
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """List asset manifests discovered in the workspace."""
    try:
        settings = load_config(config)
        assets, warnings = discover_assets(settings.foundry.workspace_root)
    except FoundryError as exc:
        fail(exc)
    table = Table("Asset ID", "Display name", "Lane", "State", "Release", "Updated (UTC)")
    table.columns[0].no_wrap = True
    for manifest in assets:
        release = (
            f"r{manifest.release.release_revision:03d}"
            if manifest.release.released and manifest.release.release_revision is not None
            else "-"
        )
        table.add_row(
            manifest.asset.asset_id,
            manifest.asset.display_name,
            manifest.asset.lane,
            manifest.workflow.state.value,
            release,
            manifest.asset.updated_at.isoformat().replace("+00:00", "Z"),
        )
    console.print(table)
    for warning in warnings:
        error_console.print(f"[yellow]Warning:[/yellow] {warning}")


@app.command("scan-sources")
def scan_sources(
    root: Path,
    limit: Annotated[int, typer.Option("--limit", min=1, max=10_000)] = 1000,
    family: Annotated[str | None, typer.Option("--family")] = None,
    lane: Annotated[str | None, typer.Option("--lane")] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit a machine-readable dry-run intake plan.")
    ] = False,
) -> None:
    """Inventory supported external models without copying or converting them."""
    try:
        candidates = scan_source_directory(root, limit, family, lane)
    except FoundryError as exc:
        fail(exc)
    if json_output:
        console.print_json(
            json.dumps(
                [
                    {
                        "path": str(candidate.path),
                        "relative_path": candidate.relative_path,
                        "format": candidate.format,
                        "size_bytes": candidate.size_bytes,
                        "sidecar_count": candidate.sidecar_count,
                        "source_family": candidate.source_family,
                        "suggested_lane": candidate.suggested_lane,
                        "suggested_asset_id": candidate.suggested_asset_id,
                        "warning": candidate.warning,
                    }
                    for candidate in candidates
                ],
                indent=2,
            )
        )
        return
    table = Table("Format", "MiB", "Sidecars", "Family", "Lane", "Suggested ID", "Path")
    for candidate in candidates:
        table.add_row(
            candidate.format,
            f"{candidate.size_bytes / 1024 / 1024:.2f}",
            str(candidate.sidecar_count),
            candidate.source_family,
            candidate.suggested_lane,
            candidate.suggested_asset_id,
            candidate.relative_path,
            style="yellow" if candidate.warning else None,
        )
    console.print(table)
    warnings = sum(candidate.warning is not None for candidate in candidates)
    console.print(
        f"[green]Found[/green] {len(candidates)} supported models"
        + (f"; {warnings} warnings" if warnings else "")
    )


@app.command("add-reference")
def add_reference(
    asset_id: str,
    image: Annotated[Path, typer.Option("--image", help="Local PNG or JPEG file.")],
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Copy a local reference image into a draft asset workspace."""
    try:
        settings = load_config(config)
        relative = add_reference_image(settings, asset_id, image)
        console.print(f"[green]Added reference[/green] {relative}")
    except FoundryError as exc:
        fail(exc)


@app.command("add-source")
def add_source(
    asset_id: str,
    model: Annotated[Path, typer.Option("--model", help="Local GLB source file.")],
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Copy and verify an existing GLB or FBX package without calling Meshy."""
    try:
        settings = load_config(config)
        if model.suffix.lower() in {".fbx", ".gltf"}:
            artifact = add_external_package(settings, asset_id, model)
        else:
            artifact = add_external_glb(settings, asset_id, model)
        console.print(f"[green]Added external source[/green] {artifact.path}")
    except FoundryError as exc:
        fail(exc)


@app.command()
def show(
    asset_id: str,
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Display the complete manifest as readable JSON."""
    try:
        settings = load_config(config)
        manifest = ManifestRepository(settings.foundry.workspace_root).load(asset_id)
        console.print_json(json.dumps(manifest.model_dump(mode="json"), indent=2))
    except FoundryError as exc:
        fail(exc)


@app.command()
def status(
    asset_id: str,
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Display concise workflow status and valid next actions."""
    try:
        settings = load_config(config)
        manifest = ManifestRepository(settings.foundry.workspace_root).load(asset_id)
    except FoundryError as exc:
        fail(exc)
    actions = next_actions(manifest.workflow.state)
    if manifest.workflow.state is WorkflowState.REVIEW and not approval_checks_pass(manifest):
        actions = ["reject"]
    table = Table(show_header=False)
    table.add_row("Asset", manifest.asset.asset_id)
    table.add_row("State", manifest.workflow.state.value)
    table.add_row(
        "Release",
        (
            f"r{manifest.release.release_revision:03d}"
            if manifest.release.released and manifest.release.release_revision is not None
            else "not published"
        ),
    )
    table.add_row("Revision", str(manifest.revision))
    table.add_row("Next actions", ", ".join(actions) if actions else "none")
    console.print(table)


@app.command()
def audit(
    asset_id: str,
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Rehash every recorded artifact and verify manifest relationships."""
    try:
        settings = load_config(config)
        result = audit_asset(settings, asset_id)
    except FoundryError as exc:
        fail(exc)
    table = Table("Artifact", "Result", "Path", "Detail")
    for check in result.artifact_checks:
        table.add_row(
            check.artifact_id,
            "pass" if check.passed else "FAIL",
            check.path,
            check.detail,
            style=None if check.passed else "red",
        )
    console.print(table)
    for check in result.manifest_checks:
        label = "[green]pass[/green]" if check["passed"] else "[red]FAIL[/red]"
        console.print(f"{label} {check['name']}")
    if not result.passed:
        fail(FoundryError(f"Integrity audit failed: {asset_id}"))
    console.print(f"[green]Integrity audit passed[/green] {asset_id}")


@app.command("audit-all")
def audit_all(
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Run read-only integrity audits for every discovered candidate."""
    try:
        settings = load_config(config)
        assets, warnings = discover_assets(settings.foundry.workspace_root)
        results = [audit_asset(settings, manifest.asset.asset_id) for manifest in assets]
    except FoundryError as exc:
        fail(exc)
    table = Table("Asset", "State", "Artifacts", "Result")
    for manifest, result in zip(assets, results, strict=True):
        table.add_row(
            result.asset_id,
            manifest.workflow.state.value,
            str(len(result.artifact_checks)),
            "pass" if result.passed else "FAIL",
            style=None if result.passed else "red",
        )
    console.print(table)
    for warning in warnings:
        error_console.print(f"[red]Discovery failure:[/red] {warning}")
    failed = [result.asset_id for result in results if not result.passed]
    if warnings or failed:
        fail(
            FoundryError(
                f"Workspace audit failed: {len(failed)} candidates and "
                f"{len(warnings)} discovery errors."
            )
        )
    console.print(f"[green]Workspace audit passed[/green] {len(results)} candidates")


@app.command("audit-library")
def audit_asset_library(
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Rehash every cataloged immutable release without changing the library."""
    try:
        settings = load_config(config)
        result = audit_library(settings)
    except FoundryError as exc:
        fail(exc)
    table = Table("Subject", "Result", "Detail")
    for check in result.checks:
        table.add_row(
            check.subject,
            "pass" if check.passed else "FAIL",
            check.detail,
            style=None if check.passed else "red",
        )
    console.print(table)
    if not result.passed:
        fail(FoundryError("Asset-library integrity audit failed."))
    console.print(f"[green]Asset-library audit passed[/green] {len(result.checks)} checks")


@app.command("review-gallery")
def review_gallery(
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Create a new offline HTML snapshot of all review candidates."""
    try:
        settings = load_config(config)
        destination = build_review_gallery(settings)
    except FoundryError as exc:
        fail(exc)
    console.print(f"[green]Review gallery created[/green] {destination}")


@app.command()
def submit(
    asset_id: str,
    confirm_spend: Annotated[
        bool,
        typer.Option(
            "--confirm-spend",
            help="Confirm this paid Meshy generation request.",
        ),
    ] = False,
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Submit one paid Meshy Text to 3D preview request."""
    if not confirm_spend:
        fail(FoundryError("Paid submission requires --confirm-spend."))
    try:
        settings = load_config(config)
        task = submit_text_preview(
            settings,
            asset_id,
            _meshy_transport(settings),
        )
        console.print(
            f"[green]Submitted[/green] {task.task_key} (provider task {task.provider_task_id})"
        )
    except FoundryError as exc:
        fail(exc)


@app.command("submit-image")
def submit_image(
    asset_id: str,
    reference: Annotated[
        str | None,
        typer.Option("--reference", help="Recorded asset-relative reference path."),
    ] = None,
    confirm_spend: Annotated[
        bool,
        typer.Option(
            "--confirm-spend",
            help="Confirm this paid Meshy Image to 3D request.",
        ),
    ] = False,
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Submit one paid Meshy Image to 3D request."""
    if not confirm_spend:
        fail(FoundryError("Paid image submission requires --confirm-spend."))
    try:
        settings = load_config(config)
        selected = RelativeManifestPath(reference) if reference is not None else None
        task = submit_image_to_3d(
            settings,
            asset_id,
            _meshy_transport(settings),
            reference=selected,
        )
        console.print(
            f"[green]Submitted image[/green] {task.task_key} "
            f"(provider task {task.provider_task_id})"
        )
    except (FoundryError, ValueError) as exc:
        fail(FoundryError(str(exc)))


@app.command()
def poll(
    asset_id: str,
    task: Annotated[str | None, typer.Option("--task")] = None,
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Retrieve one Meshy task status update."""
    try:
        settings = load_config(config)
        updated = poll_text_task(
            settings,
            asset_id,
            _meshy_transport(settings),
            task_key=task,
        )
        console.print(
            f"[green]Polled[/green] {updated.task_key}: "
            f"{updated.status.value} ({updated.progress or 0}%)"
        )
    except FoundryError as exc:
        fail(exc)


@app.command()
def refine(
    asset_id: str,
    from_task: Annotated[str, typer.Option("--from", help="Succeeded preview task key.")],
    confirm_spend: Annotated[
        bool,
        typer.Option(
            "--confirm-spend",
            help="Confirm this paid Meshy refine request.",
        ),
    ] = False,
    enable_pbr: Annotated[
        bool,
        typer.Option("--enable-pbr/--no-enable-pbr"),
    ] = True,
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Submit one paid Meshy refinement from a succeeded text preview."""
    if not confirm_spend:
        fail(FoundryError("Paid refinement requires --confirm-spend."))
    try:
        settings = load_config(config)
        task = submit_text_refine(
            settings,
            asset_id,
            from_task,
            _meshy_transport(settings),
            enable_pbr=enable_pbr,
        )
        console.print(
            f"[green]Submitted refine[/green] {task.task_key} "
            f"(provider task {task.provider_task_id})"
        )
    except FoundryError as exc:
        fail(exc)


@app.command()
def remesh(
    asset_id: str,
    target_triangles: Annotated[
        int | None,
        typer.Option("--target-triangles", min=1),
    ] = None,
    confirm_spend: Annotated[
        bool,
        typer.Option("--confirm-spend", help="Confirm this paid Meshy remesh request."),
    ] = False,
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Submit a paid Meshy triangle-remesh task for a succeeded generation."""
    if not confirm_spend:
        fail(FoundryError("Paid remesh requires --confirm-spend."))
    try:
        settings, lane_config = configured(config)
        manifest = ManifestRepository(settings.foundry.workspace_root).load(asset_id)
        lane = lane_config.lanes.get(manifest.asset.lane)
        if lane is None:
            raise FoundryError(f"Lane policy is unavailable: {manifest.asset.lane}")
        target = target_triangles or lane.target_triangles
        if target is None:
            raise FoundryError("No remesh target is configured; use --target-triangles.")
        task = submit_remesh(
            settings,
            asset_id,
            target,
            _meshy_transport(settings),
        )
        console.print(
            f"[green]Submitted remesh[/green] {task.task_key} "
            f"(provider task {task.provider_task_id})"
        )
    except FoundryError as exc:
        fail(exc)


@app.command()
def retexture(
    asset_id: str,
    artifact_id: Annotated[str, typer.Option("--artifact")],
    prompt: Annotated[str, typer.Option("--prompt")],
    label: Annotated[str, typer.Option("--label", help="beauty or semantic")],
    confirm_spend: Annotated[
        bool,
        typer.Option("--confirm-spend", help="Confirm this 10-credit Meshy retexture request."),
    ] = False,
    enable_pbr: Annotated[bool, typer.Option("--enable-pbr/--no-enable-pbr")] = True,
    texture_resolution: Annotated[
        str,
        typer.Option("--texture-resolution", help="2k or 4k"),
    ] = "2k",
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Submit one paid Meshy retexture while preserving the input UV layout."""
    if not confirm_spend:
        fail(FoundryError("Paid retexture requires --confirm-spend."))
    try:
        settings = load_config(config)
        task = submit_retexture(
            settings,
            asset_id,
            artifact_id,
            prompt,
            _meshy_transport(settings),
            task_label=label,
            enable_pbr=enable_pbr,
            texture_resolution=texture_resolution,
        )
        console.print(
            f"[green]Submitted retexture[/green] {task.task_key} "
            f"(provider task {task.provider_task_id})"
        )
    except (FoundryError, ValueError) as exc:
        fail(FoundryError(str(exc)))


@app.command()
def rig(
    asset_id: str,
    from_task: Annotated[str, typer.Option("--from", help="Succeeded beauty task key.")],
    height_meters: Annotated[float, typer.Option("--height-meters", min=0.01)] = 1.7,
    confirm_spend: Annotated[
        bool,
        typer.Option("--confirm-spend", help="Confirm this 5-credit Meshy rigging request."),
    ] = False,
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Submit one paid Meshy rigging task from a succeeded beauty retexture."""
    if not confirm_spend:
        fail(FoundryError("Paid rigging requires --confirm-spend."))
    try:
        settings = load_config(config)
        task = submit_rigging(
            settings,
            asset_id,
            from_task,
            height_meters,
            _meshy_transport(settings),
        )
        console.print(
            f"[green]Submitted rigging[/green] {task.task_key} "
            f"(provider task {task.provider_task_id})"
        )
    except (FoundryError, ValueError) as exc:
        fail(FoundryError(str(exc)))


@app.command("quantize-semantic-mask")
def quantize_mask(
    asset_id: str,
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Convert the latest downloaded semantic texture to a strict ID palette."""
    try:
        settings = load_config(config)
        artifact = quantize_semantic_mask(settings, asset_id)
        console.print(f"[green]Quantized semantic mask[/green] {artifact.path}")
    except FoundryError as exc:
        fail(exc)


@app.command()
def download(
    asset_id: str,
    task: Annotated[str | None, typer.Option("--task")] = None,
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Download and checksum a succeeded Meshy generation GLB."""
    try:
        settings = load_config(config)
        artifact = download_text_preview_glb(
            settings,
            asset_id,
            _meshy_transport(settings),
            task_key=task,
        )
        console.print(
            f"[green]Downloaded[/green] {artifact.artifact_id}: {artifact.path} "
            f"({artifact.size_bytes} bytes)"
        )
    except FoundryError as exc:
        fail(exc)


@app.command("select-output")
def select_provider_output(
    asset_id: str,
    task: Annotated[str, typer.Option("--task")],
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Select a succeeded, downloaded provider task for processing."""
    try:
        settings = load_config(config)
        selected = select_output(settings, asset_id, task)
        console.print(f"[green]Selected[/green] {selected.task_key}")
    except FoundryError as exc:
        fail(exc)


@app.command()
def process(
    asset_id: str,
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Create an immutable pass-through processed artifact."""
    try:
        settings = load_config(config)
        artifact = process_passthrough(settings, asset_id)
        console.print(f"[green]Processed[/green] {artifact.artifact_id}: {artifact.path}")
    except FoundryError as exc:
        fail(exc)


@app.command("process-blender")
def process_blender(
    asset_id: str,
    target_triangles: Annotated[
        int | None,
        typer.Option(
            "--target-triangles",
            min=1,
            help="Explicit local decimation target; omitted means transform cleanup only.",
        ),
    ] = None,
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Apply transforms and optionally decimate through bounded headless Blender."""
    try:
        settings = load_config(config)
        artifact = process_with_blender(settings, asset_id, target_triangles)
        console.print(f"[green]Blender processed[/green] {artifact.path}")
    except FoundryError as exc:
        fail(exc)


@app.command("apply-texture-mask")
def apply_masked_texture_color(
    asset_id: str,
    mask: Annotated[
        Path,
        typer.Option(
            "--mask",
            exists=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Grayscale PNG aligned to the current base-color texture.",
        ),
    ],
    color: Annotated[
        str,
        typer.Option(
            "--color",
            help="Replacement color in #RRGGBB form; source luminance is preserved.",
        ),
    ],
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """Create a new GLB with one texture-atlas region deterministically recolored."""
    try:
        settings = load_config(config)
        result = apply_texture_mask(settings, asset_id, mask, color)
        console.print(f"[green]Applied texture mask[/green] {result.model.path}")
        console.print(f"Recorded {result.mask.path}; coverage {result.coverage_fraction:.2%}")
    except (FoundryError, OSError, ValueError) as exc:
        fail(exc)


@app.command()
def inspect(
    asset_id: str,
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Inspect a processed GLB and evaluate its lane triangle budget."""
    try:
        settings, lane_config = configured(config)
        result = inspect_processed_glb(settings, lane_config, asset_id)
        console.print(
            f"[green]Inspected[/green] {asset_id}: {result.triangle_count} triangles, "
            f"{result.material_count} materials"
        )
    except FoundryError as exc:
        fail(exc)


@app.command("render-preview")
def render_preview(
    asset_id: str,
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Render a local transparent PNG preview through bounded Blender."""
    try:
        settings = load_config(config)
        artifact = render_local_preview(settings, asset_id)
        console.print(f"[green]Rendered preview[/green] {artifact.path}")
    except FoundryError as exc:
        fail(exc)


@app.command("experiment-shaders")
def experiment_shaders(
    asset_id: str,
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Render immutable local PBR shader variants for visual comparison."""
    try:
        settings = load_config(config)
        artifact = experiment_shader_variants(settings, asset_id)
        console.print(f"[green]Shader experiment created[/green] {artifact.path}")
    except FoundryError as exc:
        fail(exc)


@app.command("experiment-semantic-mask")
def experiment_mask(
    asset_id: str,
    mask: Annotated[
        Path,
        typer.Option(
            "--mask",
            exists=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Strict four-color semantic-mask PNG to record and test.",
        ),
    ],
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Record a local semantic mask and render per-channel shader isolation evidence."""
    try:
        settings = load_config(config)
        artifact = experiment_semantic_mask(settings, asset_id, mask)
        console.print(f"[green]Semantic-mask experiment created[/green] {artifact.path}")
        console.print(
            "[yellow]The candidate remains experimental until its isolation previews are "
            "reviewed.[/yellow]"
        )
    except FoundryError as exc:
        fail(exc)


@app.command("render-missing-previews")
def render_missing(
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Render previews only for eligible candidates that do not have one."""
    try:
        settings = load_config(config)
        artifacts = render_missing_previews(settings)
    except FoundryError as exc:
        fail(exc)
    console.print(f"[green]Rendered[/green] {len(artifacts)} missing previews")


@app.command("prepare-godot")
def prepare_godot(
    asset_id: str,
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Create a self-contained Godot validation sandbox outside Vandrel."""
    try:
        settings, lane_config = configured(config)
        _, wrapper = prepare_godot_sandbox(settings, lane_config, asset_id)
        console.print(f"[green]Staged Godot sandbox[/green] {wrapper.path}")
    except FoundryError as exc:
        fail(exc)


@app.command("prepare-native-character")
def prepare_native_character(
    asset_id: str,
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Extract and validate same-task Meshy FBX locomotion without Blender."""
    try:
        settings = load_config(config)
        result = prepare_provider_native_character(settings, asset_id)
        console.print(f"[green]Provider-native character prepared[/green] {result.model.path}")
        console.print(f"Walk: {result.walk.path}")
        console.print(f"Run: {result.run.path}")
        console.print(f"Evidence: {result.report.path}")
    except (FoundryError, OSError, ValueError) as exc:
        fail(exc)


@app.command("validate-godot")
def validate_godot(
    asset_id: str,
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Run bounded headless import in the recorded Godot sandbox."""
    try:
        settings = load_config(config)
        result = validate_godot_sandbox(settings, asset_id)
        if result.return_code != 0 or result.timed_out or result.output_limited:
            raise FoundryError("Godot sandbox validation failed; inspect its report.")
        console.print(f"[green]Godot validation passed[/green] {asset_id}")
    except FoundryError as exc:
        fail(exc)


@app.command("validate-humanoid-rig")
def validate_humanoid_rig(
    asset_id: str,
    animation_donor: Annotated[
        str,
        typer.Option(
            "--animation-donor",
            help="Asset ID containing the processed GLB animation library to compare.",
        ),
    ],
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """Record local Meshy-to-Godot humanoid and shared-animation evidence."""
    try:
        foundry_config, _ = configured(config)
        result = validate_humanoid_retarget(foundry_config, asset_id, animation_donor)
        console.print(f"[green]Retarget evidence:[/green] {result.report.path}")
        console.print(
            "Direct skeleton match: "
            f"{'yes' if result.direct_skeleton_match else 'no'}; "
            "rest transforms match: "
            f"{'yes' if result.direct_rest_transform_match else 'no'}; "
            "humanoid retarget candidate: "
            f"{'yes' if result.humanoid_retarget_candidate else 'no'}; "
            "direct animation transfer candidate: "
            f"{'yes' if result.shared_animation_transfer_candidate else 'no'}"
        )
    except (FoundryError, OSError, ValueError) as exc:
        fail(exc)


@app.command("graft-animations")
def graft_animation_library(
    asset_id: str,
    animation_donor: Annotated[
        str,
        typer.Option(
            "--animation-donor",
            help="Asset ID containing the exact-skeleton processed GLB animation donor.",
        ),
    ],
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """Create a new target GLB with exact-skeleton donor animations."""
    try:
        settings = load_config(config)
        result = graft_animations(settings, asset_id, animation_donor)
        console.print(
            f"[green]Grafted {result.facts.donor_animation_count} animations[/green] "
            f"into {result.model.path}"
        )
        console.print(f"Evidence: {result.report.path}")
    except (FoundryError, OSError, ValueError) as exc:
        fail(exc)


@app.command("retarget-animations")
def retarget_animation_library(
    asset_id: str,
    animation_donor: Annotated[
        str,
        typer.Option(
            "--animation-donor",
            help="Asset ID containing the compatible humanoid animation donor.",
        ),
    ],
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """Bake donor clips onto a compatible humanoid rig through bounded Blender."""
    try:
        settings = load_config(config)
        result = retarget_animations(settings, asset_id, animation_donor)
        console.print(
            f"[green]Retargeted {result.animation_count} animations[/green] "
            f"into {result.model.path}"
        )
        console.print(f"Evidence: {result.report.path}")
    except (FoundryError, OSError, ValueError) as exc:
        fail(exc)


@app.command("render-animation-samples")
def render_animation_sample_sheet(
    asset_id: str,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """Render representative frames from important clips for visual review."""
    try:
        settings = load_config(config)
        result = render_animation_samples(settings, asset_id)
        console.print(f"[green]Rendered animation sample sheet[/green] {result.path}")
    except (FoundryError, OSError, ValueError) as exc:
        fail(exc)


@app.command("accept-animation-samples")
def accept_animation_sample_sheet(
    asset_id: str,
    reviewer: Annotated[str, typer.Option("--reviewer")],
    all_samples_reviewed: Annotated[
        bool,
        typer.Option(
            "--all-samples-reviewed",
            help="Confirm representative animation samples were visually reviewed.",
        ),
    ] = False,
    notes: Annotated[str, typer.Option("--notes")] = "",
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """Bind visual acceptance to the current model and animation sample hashes."""
    if not all_samples_reviewed:
        fail(FoundryError("Animation sample acceptance requires --all-samples-reviewed."))
    try:
        settings = load_config(config)
        result = accept_animation_samples(settings, asset_id, reviewer, notes)
        console.print(f"[green]Accepted animation samples[/green] {result.path}")
    except (FoundryError, OSError, ValueError) as exc:
        fail(exc)


@app.command()
def approve(
    asset_id: str,
    reviewer: Annotated[str, typer.Option("--reviewer")],
    all_required_checks: Annotated[
        bool,
        typer.Option(
            "--all-required-checks",
            help="Confirm the human review and all required checks are complete.",
        ),
    ] = False,
    notes: Annotated[str, typer.Option("--notes")] = "",
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Bind explicit approval to the exact reviewed artifact hashes."""
    if not all_required_checks:
        fail(FoundryError("Approval requires --all-required-checks."))
    try:
        settings = load_config(config)
        manifest = approve_asset(settings, asset_id, reviewer, notes)
        console.print(f"[green]Approved[/green] {asset_id} by {manifest.approval.reviewer}")
    except FoundryError as exc:
        fail(exc)


@app.command()
def reject(
    asset_id: str,
    reason: Annotated[str, typer.Option("--reason")],
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Reject a reviewed candidate with a retained reason."""
    try:
        settings = load_config(config)
        reject_asset(settings, asset_id, reason)
        console.print(f"[yellow]Rejected[/yellow] {asset_id}")
    except FoundryError as exc:
        fail(exc)


@app.command()
def release(
    asset_id: str,
    apply: Annotated[
        bool,
        typer.Option("--apply", help="Publish the planned release."),
    ] = False,
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Plan or explicitly publish one immutable asset-library release."""
    try:
        settings, lane_config = configured(config)
        if apply:
            result = publish_release(settings, lane_config, asset_id)
            action = "Recovered" if result.recovered else "Published"
            console.print(f"[green]{action}[/green] {asset_id} r{result.release_revision:03d}")
            console.print(f"[cyan]Library destination:[/cyan] {result.destination}")
            console.print("[yellow]Asset-library Git commit and push remain separate.[/yellow]")
            return
        plan = plan_release(settings, lane_config, asset_id)
        console.print_json(json.dumps(plan.descriptor, indent=2))
        console.print(f"[cyan]Dry-run destination:[/cyan] {plan.destination}")
    except FoundryError as exc:
        fail(exc)


@app.command()
def reconcile(
    asset_id: str,
    task: Annotated[str, typer.Option("--task")],
    provider_task_id: Annotated[str | None, typer.Option("--provider-task-id")] = None,
    confirm_not_created: Annotated[
        bool,
        typer.Option(
            "--confirm-not-created",
            help="Confirm from provider records that no paid task was created.",
        ),
    ] = False,
    config: Annotated[Path | None, typer.Option("--config", help="Configuration file.")] = None,
) -> None:
    """Resolve an ambiguous submission using a user-verified provider outcome."""
    try:
        settings = load_config(config)
        reconciled = reconcile_ambiguous_submission(
            settings,
            asset_id,
            task,
            provider_task_id=provider_task_id,
            confirm_not_created=confirm_not_created,
        )
        console.print(f"[green]Reconciled[/green] {reconciled.task_key}: {reconciled.status.value}")
    except FoundryError as exc:
        fail(exc)


def _meshy_transport(settings: FoundryConfig) -> MeshyHttpTransport:
    try:
        return MeshyHttpTransport(
            settings.providers.meshy.api_base,
            settings.providers.meshy.request_timeout_seconds,
            maximum_download_bytes=settings.providers.meshy.maximum_download_bytes,
        )
    except ValueError as exc:
        raise FoundryError(f"Invalid Meshy configuration: {exc}") from exc


def main() -> None:
    app()
