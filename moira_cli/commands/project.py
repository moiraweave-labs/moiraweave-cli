"""Project management command."""

from __future__ import annotations

from typing import Any

from moira_cli.commands import BaseCommand
from moira_cli.handlers.project import ProjectHandler


class ProjectInitCommand(BaseCommand):
    """Command to initialize a new MoiraWeave project."""

    def execute(
        self,
        action: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute project initialization.

        :param action: Project action to execute.
        :param kwargs: Additional action-specific keyword arguments.
        :keyword non_interactive: Skip prompts and use defaults.
        :keyword project_name: Optional project name.
        :keyword registry: Optional OCI registry.
        :returns: Initialization result dictionary.
        """
        if action != "init":
            return {"status": "error", "message": f"Unknown action: {action}"}

        _ = bool(kwargs.get("non_interactive", False))
        project_name = kwargs.get("project_name")
        registry = kwargs.get("registry")

        self.ui.header("MoiraWeave Project Initialization")

        # Create handler
        handler = ProjectHandler(self.repo_root)

        # Initialize
        result = handler.init_workspace(project_name, registry)

        if result["status"] == "already_initialized":
            self.ui.warning(f"Project already initialized: {result['config'].name}")
            self.ui.info("Current configuration:")
            self._print_config_summary(result["config"])
            return result

        # Already initialized
        if result["status"] == "created":
            self._print_success_output(result)

        return result

    def _print_success_output(self, result: dict) -> None:
        """Print success message with details.

        :param result: Result dictionary from handler.
        """
        self.ui.success("Project initialized successfully")
        self.ui.section("Configuration", indent=2)
        self.ui.path("Config file", str(result["config_path"]))
        self.ui.path("Environment", str(result["env_path"]))

        self.ui.section("Directories", indent=2)
        for directory in result["directories"]:
            self.ui.hint(str(directory.relative_to(self.repo_root)))

        self.ui.next_steps(
            "Next steps",
            [
                (
                    1,
                    "moira workload new hermes --type agent-service --image ghcr.io/nousresearch/hermes-agent:latest",
                    "Create an agent workload",
                ),
                (2, "moira deploy local", "Generate local workload compose"),
                (3, "moira run submit hermes --input '{}'", "Submit a run"),
            ],
        )

    def _print_config_summary(self, config) -> None:
        """Print configuration summary.

        :param config: MoiraWeaveConfig object.
        """
        self.ui.hint(f"Project: {config.name}")
        self.ui.hint(f"Registry: {config.registry}")
        self.ui.hint(f"Runtime: {config.runtime_version}")
