"""Unified UI system for MoiraWeave CLI."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.style import Style
from rich.table import Table
from rich.text import Text


class UIPresenter:
    """Centralized UI system for consistent, professional output."""

    # Unicode symbols (no emojis)
    ICONS = {
        "check": "✓",
        "cross": "✗",
        "arrow": "→",
        "warn": "⚠",
        "diamond": "◆",
        "square": "■",
        "circle": "○",
        "bullet": "•",
    }

    # Color palette
    COLORS = {
        "primary": "cyan",
        "success": "green",
        "error": "red",
        "warning": "yellow",
        "info": "blue",
        "secondary": "bright_black",
    }

    def __init__(self) -> None:
        """Initialize UI presenter with Rich console."""
        self.console = Console()

    def success(self, message: str, icon: str = "check") -> None:
        """Print success message with icon.

        :param message: Message text.
        :param icon: Icon key (default: check).
        """
        icon_char = self.ICONS.get(icon, "✓")
        text = Text(f"{icon_char} {message}", style=Style(color=self.COLORS["success"]))
        self.console.print(text)

    def error(self, message: str, hint: str | None = None) -> None:
        """Print error message with optional hint.

        :param message: Error message.
        :param hint: Optional suggestion for resolution.
        """
        text = Text(
            f"{self.ICONS['cross']} {message}", style=Style(color=self.COLORS["error"])
        )
        self.console.print(text)
        if hint:
            self.console.print(
                f"  → {hint}", style=Style(color=self.COLORS["secondary"])
            )

    def warning(self, message: str) -> None:
        """Print warning message.

        :param message: Warning text.
        """
        text = Text(
            f"{self.ICONS['warn']} {message}", style=Style(color=self.COLORS["warning"])
        )
        self.console.print(text)

    def info(self, message: str) -> None:
        """Print info message.

        :param message: Info text.
        """
        text = Text(
            f"{self.ICONS['circle']} {message}", style=Style(color=self.COLORS["info"])
        )
        self.console.print(text)

    def header(self, title: str) -> None:
        """Print section header with panel.

        :param title: Header title.
        """
        panel = Panel.fit(
            Text(title, style=Style(color=self.COLORS["primary"], bold=True)),
            border_style=self.COLORS["primary"],
        )
        self.console.print(panel)

    def section(self, name: str, indent: int = 2) -> None:
        """Print section name with indentation.

        :param name: Section name.
        :param indent: Indentation spaces.
        """
        text = Text(
            f"{self.ICONS['diamond']} {name}",
            style=Style(color=self.COLORS["primary"], bold=True),
        )
        self.console.print(Text(" " * indent) + text)

    def hint(self, command: str) -> None:
        """Print command hint as inline code.

        :param command: Command to execute.
        """
        text = Text(
            f"  $ {command}", style=Style(color=self.COLORS["secondary"], italic=True)
        )
        self.console.print(text)

    def path(self, description: str, path: str) -> None:
        """Print file path with description.

        :param description: What was created/modified.
        :param path: File path.
        """
        text = Text(
            f"{self.ICONS['arrow']} {description}: ",
            style=Style(color=self.COLORS["secondary"]),
        )
        text.append(path, style=Style(color=self.COLORS["info"], bold=True))
        self.console.print(text)

    @contextmanager
    def spinner(self, message: str) -> Generator[None, None, None]:
        """Context manager for progress spinner.

        :param message: Status message.
        :yields: Context for long-running operation.
        """
        with Progress(
            SpinnerColumn(style=self.COLORS["primary"]),
            TextColumn("{task.description}", style=self.COLORS["secondary"]),
            transient=True,
        ) as progress:
            progress.add_task(message, total=None)
            try:
                yield
            finally:
                progress.stop()

    def progress_bar(self, items: list, label: str = "Processing") -> Progress:
        """Create a progress bar for iteration.

        :param items: Items to iterate.
        :param label: Progress label.
        :returns: Progress object for use with `with` statement.
        """
        return Progress(
            SpinnerColumn(style=self.COLORS["primary"]),
            TextColumn("{task.description}", style=self.COLORS["secondary"]),
            transient=True,
        )

    def table(
        self,
        title: str | None = None,
        columns: list[tuple[str, str]] | None = None,
    ) -> Table:
        """Create a themed Rich table.

        :param title: Table title.
        :param columns: List of (name, width) tuples.
        :returns: Configured Rich Table.
        """
        table = Table(title=title, border_style=self.COLORS["primary"])
        if columns:
            for col_name, col_style in columns:
                table.add_column(col_name, style=col_style or self.COLORS["secondary"])
        return table

    def print_table(self, table: Table) -> None:
        """Print a table.

        :param table: Rich Table instance.
        """
        self.console.print(table)

    def next_steps(self, title: str, steps: list[tuple[int, str, str]]) -> None:
        """Print next steps context.

        :param title: Section title (e.g., "Next steps").
        :param steps: List of (number, command, description) tuples.
        """
        self.section(title)
        for num, cmd, desc in steps:
            text = Text(f"  {num}. ", style=Style(color=self.COLORS["secondary"]))
            text.append(cmd, style=Style(color=self.COLORS["info"], bold=True))
            text.append(f"  {self.ICONS['bullet']} {desc}")
            self.console.print(text)

    def list_items(self, items: list[str], prefix: str = "") -> None:
        """Print a bulleted list.

        :param items: Items to list.
        :param prefix: Prefix string.
        """
        for item in items:
            text = Text(f"  {self.ICONS['bullet']} {item}")
            self.console.print(text)

    def print_raw(self, content: str) -> None:
        """Print raw content without formatting.

        :param content: Content to print.
        """
        self.console.print(content)

    def print_panel(self, content: str, title: str | None = None) -> None:
        """Print content in a panel.

        :param content: Panel content.
        :param title: Panel title.
        """
        panel = Panel(content, title=title, border_style=self.COLORS["primary"])
        self.console.print(panel)


# Global UI instance
_ui: UIPresenter | None = None


def get_ui() -> UIPresenter:
    """Get global UI presenter instance.

    :returns: UIPresenter instance.
    """
    global _ui
    if _ui is None:
        _ui = UIPresenter()
    return _ui
