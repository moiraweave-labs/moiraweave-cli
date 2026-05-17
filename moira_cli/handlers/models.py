"""Model management handler."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx

from moira_cli.handlers import BaseHandler


class ModelsHandler(BaseHandler):
    """Handle model cache and readiness operations."""

    def __init__(self, repo_root=None, api_url: str = "http://localhost:8000") -> None:
        """Initialize models handler.

        :param repo_root: Optional repository root.
        :param api_url: API base URL.
        """
        super().__init__(repo_root)
        self.api_url = api_url

    def prefetch_models(self, pipeline_name: str) -> dict[str, Any]:
        """Probe step readiness to warm model caches.

        :param pipeline_name: Pipeline name.
        :returns: Prefetch result dict with status per step.
        """
        import yaml

        _, _, pipelines_root = self._get_dirs()
        pipeline_path = pipelines_root / pipeline_name / "pipeline.yaml"
        if not pipeline_path.exists():
            return {
                "status": "error",
                "message": f"Pipeline not found: {pipeline_name}",
            }

        pipeline = yaml.safe_load(pipeline_path.read_text(encoding="utf-8"))
        steps = pipeline.get("steps", [])
        results = {}

        for step in steps:
            step_id = str(step.get("id", "step"))
            url = str(step.get("url", "")).rstrip("/")
            if not url:
                results[step_id] = {"status": "skipped", "reason": "no url"}
                continue

            ready_url = f"{url}/v2/health/ready"
            for _ in range(20):
                try:
                    with httpx.Client(timeout=3.0) as client:
                        response = client.get(ready_url)
                        if response.status_code == 200:
                            results[step_id] = {"status": "ready"}
                            break
                except Exception:
                    pass
                time.sleep(1)
            else:
                results[step_id] = {"status": "timeout"}

        return {
            "status": "completed",
            "pipeline": pipeline_name,
            "steps": results,
        }

    def get_model_status(self, pipeline_name: str) -> dict[str, Any]:
        """Show per-step model metadata status.

        :param pipeline_name: Pipeline name.
        :returns: Model status dict per step.
        """
        import yaml

        _, _, pipelines_root = self._get_dirs()
        pipeline_path = pipelines_root / pipeline_name / "pipeline.yaml"
        if not pipeline_path.exists():
            return {
                "status": "error",
                "message": f"Pipeline not found: {pipeline_name}",
            }

        pipeline = yaml.safe_load(pipeline_path.read_text(encoding="utf-8"))
        steps = pipeline.get("steps", [])
        results = {}

        for step in steps:
            step_id = str(step.get("id", "step"))
            url = str(step.get("url", "")).rstrip("/")
            if not url:
                results[step_id] = {"status": "no_url"}
                continue

            metadata_url = f"{url}/v2/models/{step_id}"
            try:
                with httpx.Client(timeout=5.0) as client:
                    response = client.get(metadata_url)
                    response.raise_for_status()
                    data = response.json()
                    model_name = str(data.get("name", step_id))
                    results[step_id] = {"status": "ready", "model": model_name}
            except Exception as exc:
                results[step_id] = {"status": "unreachable", "error": str(exc)}

        return {
            "status": "completed",
            "pipeline": pipeline_name,
            "steps": results,
        }

    def clear_cache(self, pipeline_name: str) -> dict[str, Any]:
        """Clear local model cache for a pipeline.

        :param pipeline_name: Pipeline name.
        :returns: Clear result dict.

        NOTA: La confirmación interactiva debe hacerse en el comando Typer, no aquí.
        """
        cache_path = self.repo_root / ".cache" / "moiraweave" / "models" / pipeline_name

        if not cache_path.exists():
            return {
                "status": "not_found",
                "message": f"No local cache found at {cache_path}",
            }

        try:
            import shutil

            shutil.rmtree(cache_path)
            return {
                "status": "cleared",
                "path": str(cache_path),
            }
        except Exception as exc:
            return {
                "status": "error",
                "message": f"Failed to clear cache: {exc}",
            }

    def _get_dirs(self) -> tuple[Path, Path, Path]:
        """Get tasks/steps/pipelines directories."""
        return (
            self.repo_root / self.config.tasks_dir,
            self.repo_root / self.config.steps_dir,
            self.repo_root / self.config.pipelines_dir,
        )
