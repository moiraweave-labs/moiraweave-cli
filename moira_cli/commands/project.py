"""Project management command."""

from __future__ import annotations

from pathlib import Path

import questionary

from moira_cli.commands import BaseCommand
from moira_cli.handlers.project import ProjectHandler


class ProjectInitCommand(BaseCommand):
    """Command to initialize a new MoiraWeave project."""

    def execute(
        self,
        non_interactive: bool = False,
        project_name: str | None = None,
        registry: str | None = None,
    ) -> None:
        """Execute project initialization.

        :param non_interactive: Skip prompts and use defaults.
        :param project_name: Optional project name.
        :param registry: Optional OCI registry.
        """
        self.ui.header("MoiraWeave Project Initialization")

        # Create handler
        handler = ProjectHandler(self.repo_root)

        # Initialize
        result = handler.init_workspace(project_name, registry)

        if result["status"] == "already_initialized":
            self.ui.warning(f"Project already initialized: {result['config'].name}")
            self.ui.info("Current configuration:")
            self._print_config_summary(result["config"])
            return

        # Already initialized
        if result["status"] == "created":
            self._print_success_output(result)

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
                (1, "moira step new <task> <impl>", "Scaffold a new step"),
                (2, "moira step add --from-catalog text-embed-fastembed", "Add official step"),
                (3, "moira pipeline new <name>", "Scaffold a pipeline"),
                (4, "moira pipeline dev <name>", "Test locally"),
            ],
        )

    def _print_config_summary(self, config) -> None:
        """Print configuration summary.

        :param config: MoiraWeaveConfig object.
        """
        self.ui.hint(f"Project: {config.name}")
        self.ui.hint(f"Registry: {config.registry}")
        self.ui.hint(f"Runtime: {config.runtime_version}")
