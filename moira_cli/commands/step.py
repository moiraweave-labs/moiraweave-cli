"""Step command orchestration."""

from __future__ import annotations

from typing import Any

from moira_cli.commands import BaseCommand
from moira_cli.handlers.step import StepHandler


class StepCommand(BaseCommand):
    """Orchestrate step operations."""

    def execute(
        self,
        action: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute step action.

        :param action: Action name (list, show, test, build, push).
        :param kwargs: Additional arguments.
        :keyword step_name: Step name for specific operations.
        :keyword bump: Version bump type (patch, minor, major) for push.
        :returns: Result dictionary.
        """
        step_name = kwargs.get("step_name")
        bump = kwargs.get("bump")

        if self.repo_root is None:
            return {"status": "error", "message": "Not in a MoiraWeave project"}

        handler = StepHandler(self.repo_root)

        if action == "list":
            return self._list_steps(handler)
        elif action == "show" and step_name:
            return self._show_step(handler, step_name)
        elif action == "test" and step_name:
            return self._test_step(handler, step_name)
        elif action == "build" and step_name:
            return self._build_step(handler, step_name)
        elif action == "push" and step_name:
            return self._push_step(handler, step_name, bump)
        else:
            return {"status": "error", "message": f"Unknown action: {action}"}

    def _list_steps(self, handler: StepHandler) -> dict[str, Any]:
        """List steps."""
        try:
            steps = handler.list_steps()
            return {
                "status": "success",
                "steps": steps,
                "count": len(steps),
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _show_step(self, handler: StepHandler, name: str) -> dict[str, Any]:
        """Show step details."""
        try:
            info = handler.get_step_info(name)
            return {
                "status": "success",
                "step": name,
                "info": info,
            }
        except FileNotFoundError as exc:
            return {"status": "error", "message": str(exc)}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _test_step(self, handler: StepHandler, name: str) -> dict[str, Any]:
        """Test step."""
        try:
            result = handler.test_step(name)
            return {
                "status": "success",
                "step": name,
                "test_result": result,
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _build_step(self, handler: StepHandler, name: str) -> dict[str, Any]:
        """Build step image."""
        try:
            result = handler.build_step(name)
            return {
                "status": "success",
                "step": name,
                "build_result": result,
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _push_step(
        self, handler: StepHandler, name: str, bump: str | None = None
    ) -> dict[str, Any]:
        """Push step image."""
        try:
            result = handler.push_step(name, bump)
            return {
                "status": "success",
                "step": name,
                "push_result": result,
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
