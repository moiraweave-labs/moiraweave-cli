"""
Handler para analizar y mostrar el flujo del workspace como árbol visual.
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
    Analiza y muestra el flujo del workspace como árbol visual.
    Consistente, robusto y sin complicar la UX.
    """
    tree = Tree("[bold magenta]MoiraWeave Workspace[/bold magenta]")

    # Validar existencia de directorios
    if not WORKSPACE_DIR.exists():
        console.print(
            "[red]No se encontró la carpeta .moiraweave/. Ejecuta 'moiraweave init' primero.[/red]"
        )
        return
    if not PIPELINES_DIR.exists():
        console.print(
            "[yellow]No hay pipelines definidos en .moiraweave/pipelines/.[/yellow]"
        )
        return

    pipeline_files = list(PIPELINES_DIR.glob("*.yaml"))
    if not pipeline_files:
        console.print(
            "[yellow]No hay archivos de pipeline en .moiraweave/pipelines/.[/yellow]"
        )
        return

    for pipeline_file in pipeline_files:
        pipeline_name = pipeline_file.stem
        pipeline_node = tree.add(f"[bold cyan]Pipeline: {pipeline_name}[/bold cyan]")
        try:
            with open(pipeline_file, "r") as f:
                pipeline_data = yaml.safe_load(f) or {}
        except Exception as e:
            pipeline_node.add(f"[red]Error leyendo YAML: {e}[/red]")
            continue
        steps = pipeline_data.get("steps", [])
        if not steps:
            pipeline_node.add("[dim]Sin steps definidos[/dim]")
            continue
        for step in steps:
            # Soporta step como string o dict
            step_name = step.get("name") if isinstance(step, dict) else step
            step_node = pipeline_node.add(f"[green]Step: {step_name}[/green]")
            # Buscar el task asociado si existe
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
                step_node.add("[dim]No se encontró definición de step[/dim]")
    console.print(tree)
