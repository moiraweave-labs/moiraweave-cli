"""Base handler class for MoiraWeave operations."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from moira_cli.io import load_moiraweave_config

if TYPE_CHECKING:
    from moira_cli.models import MoiraWeaveConfig


class BaseHandler:
    """Base handler with common context and utilities."""

    def __init__(self, repo_root: Path) -> None:
        """Initialize handler with repository root.

        :param repo_root: Path to repository root.
        """
        self.repo_root = repo_root
        self._config: MoiraWeaveConfig | None = None

    @property
    def config(self) -> MoiraWeaveConfig:
        """Get cached or loaded moiraweave.yaml configuration.

        :returns: Parsed configuration.
        :raises FileNotFoundError: If moiraweave.yaml not found.
        """
        if self._config is None:
            self._config = load_moiraweave_config(self.repo_root)
        return self._config

    @property
    def tasks_dir(self) -> Path:
        """Get tasks directory path.

        :returns: Absolute path to tasks directory.
        """
        return self.repo_root / self.config.tasks_dir

    @property
    def steps_dir(self) -> Path:
        """Get steps directory path.

        :returns: Absolute path to steps directory.
        """
        return self.repo_root / self.config.steps_dir

    @property
    def pipelines_dir(self) -> Path:
        """Get pipelines directory path.

        :returns: Absolute path to pipelines directory.
        """
        return self.repo_root / self.config.pipelines_dir

    def _get_dirs(self) -> tuple[Path, Path, Path]:
        """Return ``(tasks_dir, steps_dir, pipelines_dir)`` as a convenience tuple.

        :returns: Tuple of absolute paths for tasks, steps, and pipelines directories.
        """
        return self.tasks_dir, self.steps_dir, self.pipelines_dir
