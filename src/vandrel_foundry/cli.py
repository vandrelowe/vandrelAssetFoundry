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
from vandrel_foundry.services.audit_asset import audit_asset
from vandrel_foundry.services.build_review_gallery import build_review_gallery
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.doctor import run_doctor
from vandrel_foundry.services.download_artifact import download_text_preview_glb
from vandrel_foundry.services.inspect_assets import discover_assets, initialize_workspace
from vandrel_foundry.services.inspect_glb import inspect_processed_glb
from vandrel_foundry.services.plan_release import plan_release
from vandrel_foundry.services.poll_task import poll_text_task
from vandrel_foundry.services.process_asset import process_passthrough
from vandrel_foundry.services.process_blender import process_with_blender
from vandrel_foundry.services.reconcile_submission import reconcile_ambiguous_submission
from vandrel_foundry.services.render_missing_previews import render_missing_previews
from vandrel_foundry.services.render_preview import render_local_preview
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
    submit_text_preview,
    submit_text_refine,
)
from vandrel_foundry.services.validate_godot import validate_godot_sandbox
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
    table = Table("Asset ID", "Display name", "Lane", "State", "Updated (UTC)")
    for manifest in assets:
        table.add_row(
            manifest.asset.asset_id,
            manifest.asset.display_name,
            manifest.asset.lane,
            manifest.workflow.state.value,
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
    """Print a read-only immutable release plan; publication remains blocked."""
    if apply:
        fail(FoundryError("Release publication is not implemented; dry-run only."))
    try:
        settings, lane_config = configured(config)
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
