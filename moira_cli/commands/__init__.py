"""Base command class for MoiraWeave CLI."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from moira_cli.ui import get_ui


def find_repo_root() -> Path:
    """Find repository root by looking for tasks/ and steps/ directories.

    :returns: Repository root path.
    :raises FileNotFoundError: If workspace not found.
    """
    current = Path.cwd().resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "moiraweave.yaml").is_file():
            return candidate
        if (candidate / "tasks").is_dir() and (candidate / "steps").is_dir():
            return candidate
        if (candidate / ".moiraweave" / "tasks").is_dir() and (
            candidate / ".moiraweave" / "steps"
        ).is_dir():
            return candidate
    raise FileNotFoundError(
        "Not in a MoiraWeave workspace. "
        "Run 'moira init' to create one or navigate to an existing workspace."
    )


class BaseCommand(ABC):
    """Base command class."""

    def __init__(self, repo_root: Path | None = None) -> None:
        """Initialize command.

        :param repo_root: Optional repository root (auto-detected if not provided).
        """
        self.repo_root = repo_root or find_repo_root()
        self.ui = get_ui()

    @abstractmethod
    def execute(self, action: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Execute the command.

        :param action: Command action to execute.
        :param args: Optional positional command arguments.
        :param kwargs: Command-specific keyword arguments.
        :returns: Standardized command result dictionary.
        """
        ...
