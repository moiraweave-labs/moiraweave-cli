"""Pipeline management handler."""

from __future__ import annotations

import yaml
from pathlib import Path
from typing import Any

from moira_cli.handlers import BaseHandler
from moira_cli.handlers.task import TaskHandler
from moira_cli.io import discover_pipelines


class PipelineHandler(BaseHandler):
    """Handle pipeline operations."""

    def list_pipelines(self) -> list[dict[str, Any]]:
        """List all discovered pipelines.

        :returns: List of pipeline dictionaries.
        """
        pipelines = discover_pipelines(self.repo_root)
        return [
            {
                "name": pipeline.name,
                "description": pipeline.description,
                "steps_count": len(pipeline.steps),
                "path": str(pipeline.path),
            }
            for pipeline in pipelines
        ]

    def get_pipeline_definition(self, name: str) -> dict[str, Any]:
        """Get pipeline definition.

        :param name: Pipeline name.
        :returns: Pipeline YAML content.
        :raises FileNotFoundError: If pipeline not found.
        """
        _, _, pipelines_root = self._get_dirs()
        pipeline_path = pipelines_root / name / "pipeline.yaml"
        if not pipeline_path.exists():
            raise FileNotFoundError(f"Pipeline not found: {name}")

        return dict(yaml.safe_load(pipeline_path.read_text(encoding="utf-8")) or {})

    def create_pipeline(self, name: str) -> dict[str, Any]:
        """Create a new pipeline scaffold.

        :param name: Pipeline name.
        :returns: Created pipeline info dict.
        :raises FileExistsError: If pipeline already exists.
        """
        _, _, pipelines_root = self._get_dirs()
        target_dir = pipelines_root / name
        pipeline_path = target_dir / "pipeline.yaml"

        if pipeline_path.exists():
            raise FileExistsError(f"Pipeline already exists: {name}")

        target_dir.mkdir(parents=True, exist_ok=True)

        template = {
            "name": name,
            "version": "1.0",
            "description": f"Pipeline {name}",
            "trigger": {"type": "redis-stream", "stream": f"pipelines:{name}:jobs"},
            "steps": [
                {"id": "step-1", "task": "replace-me", "url": "http://replace-me:8000"},
            ],
        }

        pipeline_path.write_text(
            yaml.safe_dump(template, sort_keys=False), encoding="utf-8"
        )

        return {
            "name": name,
            "path": str(pipeline_path),
        }

    def validate_pipeline(self, name: str) -> dict[str, Any]:
        """Validate task compatibility across sequential pipeline steps.

        :param name: Pipeline name.
        :returns: Validation result dict with status and issues.
        """
        tasks_root = self.repo_root / self.config.tasks_dir

        try:
            pipeline = self.get_pipeline_definition(name)
        except FileNotFoundError:
            return {"status": "error", "message": f"Pipeline not found: {name}"}

        steps = pipeline.get("steps", [])
        issues: list[str] = []
        task_handler = TaskHandler(self.repo_root)

        for i in range(len(steps) - 1):
            left = steps[i]
            right = steps[i + 1]

            left_task = str(left.get("task", ""))
            right_task = str(right.get("task", ""))

            produced = task_handler.get_task_outputs(left_task)
            required = task_handler.get_task_inputs(right_task)

            missing = required - produced
            if missing:
                issues.append(
                    f"{left.get('id', left_task)} → {right.get('id', right_task)}: "
                    f"missing outputs {sorted(missing)}"
                )

        return {
            "status": "valid" if not issues else "invalid",
            "pipeline": name,
            "issues": issues,
        }

    def _get_dirs(self) -> tuple[Path, Path, Path]:
        """Get tasks/steps/pipelines directories."""
        return (
            self.repo_root / self.config.tasks_dir,
            self.repo_root / self.config.steps_dir,
            self.repo_root / self.config.pipelines_dir,
        )
