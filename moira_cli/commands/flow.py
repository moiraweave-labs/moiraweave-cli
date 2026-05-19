"""
CLI command to show the workspace flow as a visual tree.
"""

import typer

from moira_cli.handlers.flow import show_flow


def flow_command():
    """Show the workspace/project flow as a visual tree."""
    show_flow()


app = typer.Typer()
app.command()(flow_command)
