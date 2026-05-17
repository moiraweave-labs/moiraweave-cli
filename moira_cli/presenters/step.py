"""Step output presenter."""

from __future__ import annotations

from typing import Any

from moira_cli.presenters import BasePresenter


class StepPresenter(BasePresenter):
    """Format step operation results."""

    def present_list(self, steps: list[dict[str, Any]]) -> None:
        """Present step listing.

        :param steps: List of step dicts.
        """
        if not steps:
            self.ui.info("No steps found. Run 'moira step new' to create one.")
            return

        self.ui.header("Steps")
        table = self.ui.table()
        table.add_column("Name", style="cyan")
        table.add_column("Task", style="blue")
        table.add_column("Version", style="green")
        table.add_column("Has Dockerfile", style="yellow")

        for step in steps:
            dockerfile = "✓" if step.get("has_dockerfile") else "✗"
            table.add_row(
                step.get("name", ""),
                step.get("task", ""),
                step.get("version", ""),
                dockerfile,
            )

        self.ui.console.print(table)
        self.ui.hint("View step details: moira step show <name>")

    def present_show(self, step_name: str, info: dict[str, Any]) -> None:
        """Present step details.

        :param step_name: Step name.
        :param info: Step metadata dict.
        """
        self.ui.header(f"Step: {step_name}")
        self.ui.path("Task", info.get("task", "N/A"))
        self.ui.path("Version", info.get("version", "N/A"))
        self.ui.path("Description", info.get("description", "N/A"))

        if info.get("inputs"):
            self.ui.section("Inputs", indent=1)
            for inp in info.get("inputs", []):
                self.ui.console.print(f"  • {inp.get('name')}: {inp.get('type')}")

        if info.get("outputs"):
            self.ui.section("Outputs", indent=1)
            for out in info.get("outputs", []):
                self.ui.console.print(f"  • {out.get('name')}: {out.get('type')}")

    def present_test_result(self, step_name: str, result: dict[str, Any]) -> None:
        """Present test result.

        :param step_name: Step name.
        :param result: Test result dict.
        """
        status = result.get("status", "unknown")
        if status == "not_found":
            self.ui.warning(f"No tests found at {result.get('path')}")
            return

        if status == "passed":
            self.ui.success(f"Tests passed for step '{step_name}'")
        else:
            self.ui.error(
                f"Tests failed for step '{step_name}' (exit code: {result.get('returncode')})"
            )
            output = result.get("output", "")
            if output:
                self.ui.console.print(output)

    def present_build_result(self, step_name: str, result: dict[str, Any]) -> None:
        """Present build result.

        :param step_name: Step name.
        :param result: Build result dict.
        """
        status = result.get("status", "unknown")
        image = result.get("image", "unknown")

        if status == "success":
            self.ui.success(f"Built image: {image}")
        else:
            self.ui.error(
                f"Build failed (exit code: {result.get('returncode')})",
                hint="Check Dockerfile and dependencies",
            )
            output = result.get("output", "")
            if output:
                self.ui.console.print(output)

    def present_push_result(self, step_name: str, result: dict[str, Any]) -> None:
        """Present push result.

        :param step_name: Step name.
        :param result: Push result dict.
        """
        status = result.get("status", "unknown")
        image = result.get("image", "unknown")
        version = result.get("version", "unknown")
        bumped = result.get("bumped", False)

        if status == "success":
            msg = f"Pushed {image}"
            if bumped:
                msg += f" (version bumped to {version})"
            self.ui.success(msg)
            self.ui.hint("Step is now available for pipelines to use")
        else:
            self.ui.error(
                f"Push failed (exit code: {result.get('returncode')})",
                hint="Verify registry credentials and image name",
            )
            output = result.get("output", "")
            if output:
                self.ui.console.print(output)
