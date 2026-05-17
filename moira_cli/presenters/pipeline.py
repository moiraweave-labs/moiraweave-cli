"""Pipeline output presenter."""

from __future__ import annotations

from typing import Any

from moira_cli.presenters import BasePresenter


class PipelinePresenter(BasePresenter):
    """Format pipeline operation results."""

    def present_list(self, pipelines: list[dict[str, Any]]) -> None:
        """Present pipeline listing.

        :param pipelines: List of pipeline dicts.
        """
        if not pipelines:
            self.ui.info("No pipelines found. Run 'moira pipeline new' to create one.")
            return

        self.ui.header("Pipelines")
        table = self.ui.table()
        table.add_column("Name", style="cyan")
        table.add_column("Description", style="blue")
        table.add_column("Steps", style="yellow")

        for pipeline in pipelines:
            table.add_row(
                pipeline.get("name", ""),
                pipeline.get("description", ""),
                str(pipeline.get("steps_count", 0)),
            )

        self.ui.console.print(table)
        self.ui.hint("Validate pipeline: moira pipeline validate <name>")

    def present_show(self, pipeline_name: str, definition: dict[str, Any]) -> None:
        """Present pipeline definition.

        :param pipeline_name: Pipeline name.
        :param definition: Pipeline YAML content.
        """
        self.ui.header(f"Pipeline: {pipeline_name}")
        self.ui.path("Version", definition.get("version", "N/A"))
        self.ui.path("Description", definition.get("description", "N/A"))

        steps = definition.get("steps", [])
        if steps:
            self.ui.section("Steps", indent=1)
            for i, step in enumerate(steps, 1):
                step_id = step.get("id", f"step-{i}")
                task = step.get("task", "unknown")
                self.ui.console.print(f"  {i}. {step_id} → {task}")

    def present_new(self, pipeline_name: str, created: dict[str, Any]) -> None:
        """Present new pipeline creation.

        :param pipeline_name: Pipeline name.
        :param created: Created pipeline info dict.
        """
        self.ui.success(f"Created pipeline scaffold: {pipeline_name}")
        self.ui.path("Path", created.get("path", ""))
        self.ui.next_steps(
            "Next steps",
            [
                (1, f"moira pipeline show {pipeline_name}", "View pipeline definition"),
                (2, "Edit pipeline.yaml to add steps", "Configure execution flow"),
                (
                    3,
                    f"moira pipeline validate {pipeline_name}",
                    "Validate task compatibility",
                ),
            ],
        )

    def present_validation(
        self, pipeline_name: str, validation: dict[str, Any]
    ) -> None:
        """Present validation result.

        :param pipeline_name: Pipeline name.
        :param validation: Validation result dict.
        """
        status = validation.get("status", "unknown")
        issues = validation.get("issues", [])

        if status == "valid":
            self.ui.success(f"Pipeline '{pipeline_name}' is valid ✓")
            self.ui.info("All task outputs are compatible with next step inputs")
        else:
            self.ui.error(f"Pipeline '{pipeline_name}' has {len(issues)} issue(s)")
            for issue in issues:
                self.ui.console.print(f"  • {issue}")
            self.ui.hint("Edit pipeline.yaml to fix task compatibility")
