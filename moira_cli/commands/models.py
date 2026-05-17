"""Models command orchestration."""

from __future__ import annotations

from typing import Any

from moira_cli.commands import BaseCommand
from moira_cli.handlers.models import ModelsHandler


class ModelsCommand(BaseCommand):
    """Orchestrate model operations."""

    def __init__(self, repo_root=None, api_url: str = "http://localhost:8000") -> None:
        """Initialize models command.

        :param repo_root: Optional repository root.
        :param api_url: API base URL.
        """
        super().__init__(repo_root)
        self.api_url = api_url

    def execute(
        self,
        action: str,
        pipeline_name: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute models action.

        :param action: Action name (prefetch, status, clear).
        :param pipeline_name: Pipeline name.
        :param kwargs: Additional arguments.
        :returns: Result dictionary.
        """
        if self.repo_root is None:
            return {"status": "error", "message": "Not in a MoiraWeave project"}

        handler = ModelsHandler(self.repo_root, api_url=self.api_url)

        if action == "prefetch" and pipeline_name:
            return self._prefetch(handler, pipeline_name)
        elif action == "status" and pipeline_name:
            return self._status(handler, pipeline_name)
        elif action == "clear" and pipeline_name:
            return self._clear(handler, pipeline_name)
        else:
            return {"status": "error", "message": f"Unknown action: {action}"}

    def _prefetch(self, handler: ModelsHandler, pipeline_name: str) -> dict[str, Any]:
        """Prefetch models for pipeline."""
        try:
            result = handler.prefetch_models(pipeline_name)
            return {
                "status": "success",
                "pipeline": pipeline_name,
                "prefetch": result,
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _status(self, handler: ModelsHandler, pipeline_name: str) -> dict[str, Any]:
        """Get model status for pipeline."""
        try:
            result = handler.get_model_status(pipeline_name)
            return {
                "status": "success",
                "pipeline": pipeline_name,
                "model_status": result,
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _clear(self, handler: ModelsHandler, pipeline_name: str) -> dict[str, Any]:
        """Clear model cache for pipeline."""
        try:
            result = handler.clear_cache(pipeline_name)
            return {
                "status": "success",
                "pipeline": pipeline_name,
                "clear_result": result,
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
