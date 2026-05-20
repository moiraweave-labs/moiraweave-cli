"""
Handler for analysing and displaying the workspace flow as a visual tree.
"""

from pathlib import Path

import yaml
from rich.console import Console
from rich.tree import Tree

WORKSPACE_DIR = Path(".moiraweave")
PIPELINES_DIR = WORKSPACE_DIR / "pipelines"
STEPS_DIR = WORKSPACE_DIR / "steps"
TASKS_DIR = WORKSPACE_DIR / "tasks"

console = Console()


def show_flow():
    """
    Analyse and display the workspace flow as a visual tree.
    """
    tree = Tree("[bold magenta]MoiraWeave Workspace[/bold magenta]")

    # Validar existencia de directorios
    if not WORKSPACE_DIR.exists():
        console.print(
            "[red].moiraweave/ directory not found. Run 'moira init' first.[/red]"
        )
        return
    if not PIPELINES_DIR.exists():
        console.print(
            "[yellow]No pipelines defined in .moiraweave/pipelines/.[/yellow]"
        )
        return

    pipeline_files = list(PIPELINES_DIR.glob("*/pipeline.yaml"))
    if not pipeline_files:
        console.print(
            "[yellow]No pipeline files found in .moiraweave/pipelines/.[/yellow]"
        )
        return

    for pipeline_file in pipeline_files:
        pipeline_name = pipeline_file.parent.name
        pipeline_node = tree.add(f"[bold cyan]Pipeline: {pipeline_name}[/bold cyan]")
        try:
            with open(pipeline_file, "r") as f:
                pipeline_data = yaml.safe_load(f) or {}
        except Exception as e:
            pipeline_node.add(f"[red]Error reading YAML: {e}[/red]")
            continue
        steps = pipeline_data.get("steps", [])
        if not steps:
            pipeline_node.add("[dim]No steps defined[/dim]")
            continue
        for step in steps:
            # Supports step as string or dict
            step_name = step.get("id") if isinstance(step, dict) else step
            step_node = pipeline_node.add(f"[green]Step: {step_name}[/green]")
            # Look up associated task if it exists
            step_file = STEPS_DIR / f"{step_name}.yaml"
            if step_file.exists():
                try:
                    with open(step_file, "r") as sf:
                        step_data = yaml.safe_load(sf) or {}
                    task_name = step_data.get("task")
                    if task_name:
                        step_node.add(f"[yellow]Task: {task_name}[/yellow]")
                except Exception as e:
                    step_node.add(f"[red]Error leyendo step: {e}[/red]")
            else:
                step_node.add("[dim]Step definition not found[/dim]")
    console.print(tree)
