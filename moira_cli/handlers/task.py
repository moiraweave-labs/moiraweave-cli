"""Task management handler."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from moira_cli.handlers import BaseHandler
from moira_cli.io import discover_tasks


class TaskHandler(BaseHandler):
    """Handle task operations."""

    def list_tasks(self) -> list[dict[str, Any]]:
        """List all discovered tasks.

        :returns: List of task dictionaries.
        """
        tasks = discover_tasks(self.repo_root)
        return [
            {
                "name": task.name,
                "description": task.description,
                "path": str(task.path),
            }
            for task in tasks
        ]

    def get_task_schema(self, name: str) -> dict[str, Any]:
        """Get task schema.

        :param name: Task name.
        :returns: Task schema.
        :raises FileNotFoundError: If task not found.
        """
        tasks_root = self.repo_root / self.config.tasks_dir
        schema_path = tasks_root / name / "schema.json"
        if not schema_path.exists():
            raise FileNotFoundError(f"Task schema not found: {schema_path}")

        return dict(json.loads(schema_path.read_text(encoding="utf-8")))

    def create_task(
        self,
        name: str,
        description: str | None = None,
        input_name: str = "input",
        output_name: str = "output",
    ) -> dict[str, Any]:
        """Create a new task schema.

        :param name: Task name.
        :param description: Optional task description.
        :param input_name: Primary input tensor name.
        :param output_name: Primary output tensor name.
        :returns: Created task info dict.
        :raises FileExistsError: If task already exists.
        """
        tasks_root = self.repo_root / self.config.tasks_dir
        task_dir = tasks_root / name
        schema_path = task_dir / "schema.json"

        if schema_path.exists():
            raise FileExistsError(f"Task already exists: {name}")

        task_dir.mkdir(parents=True, exist_ok=True)

        schema = {
            "task": name,
            "version": "1.0",
            "description": description or f"Task contract for {name}",
            "inputs": [
                {
                    "name": input_name,
                    "datatype": "BYTES",
                    "shape": [1],
                    "description": "Primary input",
                    "required": True,
                }
            ],
            "outputs": [
                {
                    "name": output_name,
                    "datatype": "BYTES",
                    "shape": [1],
                    "description": "Primary output",
                }
            ],
        }

        schema_path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")

        return {
            "name": name,
            "path": str(schema_path),
            "inputs": [input_name],
            "outputs": [output_name],
        }

    def get_task_inputs(self, name: str) -> set[str]:
        """Get required input tensor names for a task.

        :param name: Task name.
        :returns: Set of required input tensor names.
        """
        try:
            schema = self.get_task_schema(name)
            inputs = schema.get("inputs", [])
            return {str(item["name"]) for item in inputs if item.get("required", False)}
        except FileNotFoundError:
            return set()

    def get_task_outputs(self, name: str) -> set[str]:
        """Get output tensor names for a task.

        :param name: Task name.
        :returns: Set of output tensor names.
        """
        try:
            schema = self.get_task_schema(name)
            outputs = schema.get("outputs", [])
            return {str(item["name"]) for item in outputs}
        except FileNotFoundError:
            return set()
