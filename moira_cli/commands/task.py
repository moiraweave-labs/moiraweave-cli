"""Task command orchestration."""

from __future__ import annotations

from typing import Any

from moira_cli.commands import BaseCommand
from moira_cli.handlers.task import TaskHandler


class TaskCommand(BaseCommand):
    """Orchestrate task operations."""

    def execute(
        self,
        action: str,
        task_name: str | None = None,
        description: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute task action.

        :param action: Action name (list, show, new).
        :param task_name: Task name for specific operations.
        :param description: Task description for creation.
        :param kwargs: Additional arguments.
        :returns: Result dictionary.
        """
        if self.repo_root is None:
            return {"status": "error", "message": "Not in a MoiraWeave project"}

        handler = TaskHandler(self.repo_root)

        if action == "list":
            return self._list_tasks(handler)
        elif action == "show" and task_name:
            return self._show_task(handler, task_name)
        elif action == "new" and task_name:
            return self._new_task(handler, task_name, description)
        else:
            return {"status": "error", "message": f"Unknown action: {action}"}

    def _list_tasks(self, handler: TaskHandler) -> dict[str, Any]:
        """List tasks."""
        try:
            tasks = handler.list_tasks()
            return {
                "status": "success",
                "tasks": tasks,
                "count": len(tasks),
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _show_task(self, handler: TaskHandler, name: str) -> dict[str, Any]:
        """Show task schema."""
        try:
            schema = handler.get_task_schema(name)
            inputs = handler.get_task_inputs(name)
            outputs = handler.get_task_outputs(name)
            return {
                "status": "success",
                "task": name,
                "schema": schema,
                "inputs": sorted(inputs),
                "outputs": sorted(outputs),
            }
        except FileNotFoundError as exc:
            return {"status": "error", "message": str(exc)}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _new_task(
        self, handler: TaskHandler, name: str, description: str | None = None
    ) -> dict[str, Any]:
        """Create new task schema."""
        try:
            result = handler.create_task(name, description)
            return {
                "status": "success",
                "task": name,
                "created": result,
            }
        except FileExistsError as exc:
            return {"status": "error", "message": str(exc)}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
