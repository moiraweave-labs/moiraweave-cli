"""
Comando CLI para mostrar el flujo del workspace como árbol visual.
"""

import typer

from moira_cli.handlers.flow import show_flow


def flow_command():
    """Muestra el flujo del workspace/proyecto como un árbol visual."""
    show_flow()


app = typer.Typer()
app.command()(flow_command)
