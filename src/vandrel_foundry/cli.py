import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from vandrel_foundry.config import FoundryConfig, load_config, load_lanes
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.lanes import LaneConfiguration
from vandrel_foundry.domain.states import next_actions
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.doctor import run_doctor
from vandrel_foundry.services.inspect_assets import discover_assets, initialize_workspace
from vandrel_foundry.storage.manifests import ManifestRepository

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
    table = Table(show_header=False)
    table.add_row("Asset", manifest.asset.asset_id)
    table.add_row("State", manifest.workflow.state.value)
    table.add_row("Revision", str(manifest.revision))
    table.add_row("Next actions", ", ".join(actions) if actions else "none")
    console.print(table)


def main() -> None:
    app()
