"""Pipeline command orchestration."""

from __future__ import annotations

from typing import Any

from moira_cli.commands import BaseCommand
from moira_cli.handlers.pipeline import PipelineHandler


class PipelineCommand(BaseCommand):
    """Orchestrate pipeline operations."""

    def execute(
        self,
        action: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute pipeline action.

        :param action: Action name (list, show, new, validate).
        :param kwargs: Additional arguments.
        :keyword pipeline_name: Pipeline name for specific operations.
        :returns: Result dictionary.
        """
        pipeline_name = kwargs.get("pipeline_name")

        if self.repo_root is None:
            return {"status": "error", "message": "Not in a MoiraWeave project"}

        handler = PipelineHandler(self.repo_root)

        if action == "list":
            return self._list_pipelines(handler)
        elif action == "show" and pipeline_name:
            return self._show_pipeline(handler, pipeline_name)
        elif action == "new" and pipeline_name:
            return self._new_pipeline(handler, pipeline_name)
        elif action == "validate" and pipeline_name:
            return self._validate_pipeline(handler, pipeline_name)
        else:
            return {"status": "error", "message": f"Unknown action: {action}"}

    def _list_pipelines(self, handler: PipelineHandler) -> dict[str, Any]:
        """List pipelines."""
        try:
            pipelines = handler.list_pipelines()
            return {
                "status": "success",
                "pipelines": pipelines,
                "count": len(pipelines),
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _show_pipeline(self, handler: PipelineHandler, name: str) -> dict[str, Any]:
        """Show pipeline definition."""
        try:
            definition = handler.get_pipeline_definition(name)
            return {
                "status": "success",
                "pipeline": name,
                "definition": definition,
            }
        except FileNotFoundError as exc:
            return {"status": "error", "message": str(exc)}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _new_pipeline(self, handler: PipelineHandler, name: str) -> dict[str, Any]:
        """Create new pipeline."""
        try:
            result = handler.create_pipeline(name)
            return {
                "status": "success",
                "pipeline": name,
                "created": result,
            }
        except FileExistsError as exc:
            return {"status": "error", "message": str(exc)}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _validate_pipeline(self, handler: PipelineHandler, name: str) -> dict[str, Any]:
        """Validate pipeline task compatibility."""
        try:
            result = handler.validate_pipeline(name)
            return {
                "status": "success",
                "pipeline": name,
                "validation": result,
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
