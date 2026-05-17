"""Task output presenter."""

from __future__ import annotations

from typing import Any

from moira_cli.presenters import BasePresenter


class TaskPresenter(BasePresenter):
    """Format task operation results."""

    def present_list(self, tasks: list[dict[str, Any]]) -> None:
        """Present task listing.

        :param tasks: List of task dicts.
        """
        if not tasks:
            self.ui.info("No tasks found. Run 'moira task new' to create one.")
            return

        self.ui.header("Tasks")
        table = self.ui.table()
        table.add_column("Name", style="cyan")
        table.add_column("Description", style="blue")

        for task in tasks:
            table.add_row(
                task.get("name", ""),
                task.get("description", ""),
            )

        self.ui.console.print(table)
        self.ui.hint("View task details: moira task show <name>")

    def present_show(
        self,
        task_name: str,
        schema: dict[str, Any],
        inputs: list[str],
        outputs: list[str],
    ) -> None:
        """Present task schema.

        :param task_name: Task name.
        :param schema: Task schema dict.
        :param inputs: List of input tensor names.
        :param outputs: List of output tensor names.
        """
        self.ui.header(f"Task: {task_name}")
        self.ui.path("Version", schema.get("version", "N/A"))
        self.ui.path("Description", schema.get("description", "N/A"))

        if inputs:
            self.ui.section("Required Inputs", indent=1)
            for inp in inputs:
                self.ui.console.print(f"  • {inp}")

        if outputs:
            self.ui.section("Outputs", indent=1)
            for out in outputs:
                self.ui.console.print(f"  • {out}")

    def present_new(self, task_name: str, created: dict[str, Any]) -> None:
        """Present new task creation.

        :param task_name: Task name.
        :param created: Created task info dict.
        """
        self.ui.success(f"Created task schema: {task_name}")
        self.ui.path("Path", created.get("path", ""))
        self.ui.path("Inputs", ", ".join(created.get("inputs", [])))
        self.ui.path("Outputs", ", ".join(created.get("outputs", [])))
        self.ui.next_steps(
            "Next steps",
            [
                (1, f"moira task show {task_name}", "View task details"),
                (2, "Edit schema.json to customize inputs/outputs", "Customize tensors"),
                (3, "Add steps using this task", "Build pipelines"),
            ],
        )
