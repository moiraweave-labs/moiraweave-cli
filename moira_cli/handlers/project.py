"""Project initialization and management handler."""

from __future__ import annotations

from typing import Any

from moira_cli.handlers import BaseHandler
from moira_cli.io import (
    check_prereqs,
    ensure_local_env,
    load_moiraweave_config,
    scaffold_workspace_structure,
    write_default_moiraweave_config,
)


class ProjectHandler(BaseHandler):
    """Handle project initialization and management."""

    def init_workspace(
        self,
        project_name: str | None = None,
        registry: str | None = None,
    ) -> dict[str, Any]:
        """Initialize a new workspace.

        :param project_name: Optional project name (defaults to directory name).
        :param registry: Optional OCI registry (defaults to ghcr.io/myorg).
        :returns: Dictionary with created paths and status.
        """
        config_path = self.repo_root / "moiraweave.yaml"

        # Check if already initialized
        if config_path.exists():
            return {
                "status": "already_initialized",
                "config_path": config_path,
                "config": load_moiraweave_config(self.repo_root),
                "prereqs": check_prereqs(),
            }

        # Use defaults if not provided
        final_name = project_name or self.repo_root.name
        final_registry = registry or "ghcr.io/myorg"

        # Write configuration and scaffold
        write_default_moiraweave_config(self.repo_root, final_name, final_registry)
        ensure_local_env(self.repo_root)
        scaffold_workspace_structure(self.repo_root)

        return {
            "status": "created",
            "project_name": final_name,
            "registry": final_registry,
            "config_path": config_path,
            "env_path": self.repo_root / ".env",
            "directories": [
                self.repo_root / ".moiraweave" / "pipelines",
                self.repo_root / ".moiraweave" / "steps",
                self.repo_root / ".moiraweave" / "tasks",
                self.repo_root / ".moiraweave" / "deploy",
            ],
        }

    def get_status(self) -> dict[str, Any]:
        """Get current project status.

        :returns: Dictionary with project metadata.
        """
        config_path = self.repo_root / "moiraweave.yaml"
        if not config_path.exists():
            return {"status": "not_initialized"}

        config = load_moiraweave_config(self.repo_root)
        return {
            "status": "initialized",
            "name": config.name,
            "registry": config.registry,
            "runtime_version": config.runtime_version,
            "environments": list(config.environments.keys()),
            "prereqs": check_prereqs(),
        }
