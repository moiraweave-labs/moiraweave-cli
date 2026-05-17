"""Models output presenter."""

from __future__ import annotations

from typing import Any

from moira_cli.presenters import BasePresenter


class ModelsPresenter(BasePresenter):
    """Format model operation results."""

    def present_prefetch(self, pipeline_name: str, result: dict[str, Any]) -> None:
        """Present prefetch result.

        :param pipeline_name: Pipeline name.
        :param result: Prefetch result dict.
        """
        self.ui.header(f"Prefetch: {pipeline_name}")

        status = result.get("status", "unknown")
        if status == "completed":
            self.ui.success("Prefetch completed")
        else:
            self.ui.info(f"Status: {status}")

        steps = result.get("steps", {})
        if steps:
            self.ui.section("Step Status", indent=1)
            for step_id, step_result in steps.items():
                step_status = step_result.get("status", "unknown")
                icon = (
                    "✓"
                    if step_status == "ready"
                    else "⋯"
                    if step_status == "timeout"
                    else "○"
                )
                self.ui.console.print(f"  {icon} {step_id}: {step_status}")

    def present_status(self, pipeline_name: str, result: dict[str, Any]) -> None:
        """Present model status.

        :param pipeline_name: Pipeline name.
        :param result: Model status dict.
        """
        self.ui.header(f"Model Status: {pipeline_name}")

        status = result.get("status", "unknown")
        if status == "completed":
            self.ui.success("Status check completed")
        else:
            self.ui.info(f"Status: {status}")

        steps = result.get("steps", {})
        if steps:
            self.ui.section("Step Models", indent=1)
            for step_id, step_status in steps.items():
                step_result = step_status.get("status", "unknown")
                if step_result == "ready":
                    model = step_status.get("model", step_id)
                    self.ui.console.print(f"  ✓ {step_id}: {model}")
                else:
                    self.ui.console.print(f"  ✗ {step_id}: {step_result}")

    def present_clear(self, pipeline_name: str, result: dict[str, Any]) -> None:
        """Present clear cache result.

        :param pipeline_name: Pipeline name.
        :param result: Clear result dict.
        """
        clear_status = result.get("status", "unknown")

        if clear_status == "cleared":
            self.ui.success(f"Cache cleared for '{pipeline_name}'")
            self.ui.path("Path", result.get("path", ""))
        elif clear_status == "not_found":
            self.ui.info(result.get("message", "Cache not found"))
        else:
            self.ui.error(
                result.get("message", "Failed to clear cache"),
                hint="Check directory permissions",
            )
