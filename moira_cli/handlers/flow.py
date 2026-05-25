"""Handler for displaying workload manifests as a visual tree."""

from pathlib import Path

import yaml
from rich.console import Console
from rich.tree import Tree

WORKSPACE_DIR = Path(".moiraweave")
WORKLOADS_DIR = WORKSPACE_DIR / "workloads"

console = Console()


def show_flow() -> None:
    """Display workload manifests as a compact workspace tree."""
    tree = Tree("[bold magenta]MoiraWeave Workspace[/bold magenta]")

    if not WORKSPACE_DIR.exists():
        console.print(
            "[red].moiraweave/ directory not found. Run 'moira init' first.[/red]"
        )
        return
    if not WORKLOADS_DIR.exists():
        console.print(
            "[yellow]No workloads defined in .moiraweave/workloads/.[/yellow]"
        )
        return

    workload_files = list(WORKLOADS_DIR.glob("*/workload.yaml"))
    if not workload_files:
        console.print(
            "[yellow]No workload files found in .moiraweave/workloads/.[/yellow]"
        )
        return

    for workload_file in sorted(workload_files):
        workload_name = workload_file.parent.name
        workload_node = tree.add(f"[bold cyan]Workload: {workload_name}[/bold cyan]")
        try:
            workload_data = (
                yaml.safe_load(workload_file.read_text(encoding="utf-8")) or {}
            )
        except Exception as exc:
            workload_node.add(f"[red]Error reading YAML: {exc}[/red]")
            continue
        spec = workload_data.get("spec") or {}
        metadata = workload_data.get("metadata") or {}
        if isinstance(metadata, dict) and metadata.get("name"):
            workload_node.add(f"[green]Name: {metadata['name']}[/green]")
        if not isinstance(spec, dict):
            workload_node.add("[red]Invalid spec[/red]")
            continue
        workload_node.add(f"[yellow]Type: {spec.get('type', 'unknown')}[/yellow]")
        execution = spec.get("execution") or {}
        if isinstance(execution, dict):
            workload_node.add(
                f"[blue]Execution: {execution.get('mode', 'unknown')}[/blue]"
            )
        deployment = spec.get("deployment") or {}
        if isinstance(deployment, dict):
            workload_node.add(
                f"[blue]Deployment: {deployment.get('mode', 'managed')}[/blue]"
            )
        if spec.get("endpoint"):
            workload_node.add(f"[dim]Endpoint: {spec['endpoint']}[/dim]")
        elif spec.get("image"):
            workload_node.add(f"[dim]Image: {spec['image']}[/dim]")
        agent = spec.get("agent") or {}
        if isinstance(agent, dict) and agent.get("adapter"):
            workload_node.add(f"[magenta]Agent adapter: {agent['adapter']}[/magenta]")
    console.print(tree)
