"""Job command orchestration."""

from __future__ import annotations

from typing import Any

from moira_cli.commands import BaseCommand
from moira_cli.handlers.job import JobHandler


class JobCommand(BaseCommand):
    """Orchestrate job operations (query only)."""

    def __init__(self, repo_root=None, api_url: str = "http://localhost:8000") -> None:
        """Initialize job command.

        :param repo_root: Optional repository root.
        :param api_url: API base URL.
        """
        super().__init__(repo_root)
        self.api_url = api_url

    def execute(
        self,
        action: str,
        job_id: str | None = None,
        timeout: int = 120,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute job action.

        :param action: Action name (status, result, wait).
        :param job_id: Job identifier.
        :param timeout: Timeout in seconds for wait action.
        :param kwargs: Additional arguments.
        :returns: Result dictionary.
        """
        handler = JobHandler(self.repo_root, api_url=self.api_url)

        if action == "list":
            return self._list_jobs(
                handler, kwargs.get("pipeline_id"), kwargs.get("limit", 20)
            )
        elif action == "status" and job_id:
            return self._get_status(handler, job_id)
        elif action == "result" and job_id:
            return self._get_result(handler, job_id)
        elif action == "wait" and job_id:
            return self._wait(handler, job_id, timeout)
        else:
            return {"status": "error", "message": f"Unknown action: {action}"}

    def _list_jobs(
        self,
        handler: JobHandler,
        pipeline_id: str | None,
        limit: int,
    ) -> dict[str, Any]:
        """List jobs for the current user."""
        try:
            jobs = handler.list_jobs(pipeline_id=pipeline_id, limit=limit)
            return {"status": "success", "jobs": jobs}
        except RuntimeError as exc:
            return {"status": "error", "message": str(exc)}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _get_status(self, handler: JobHandler, job_id: str) -> dict[str, Any]:
        """Get job status."""
        try:
            status = handler.get_job_status(job_id)
            return {
                "status": "success",
                "job_id": job_id,
                "job_status": status,
            }
        except RuntimeError as exc:
            return {"status": "error", "message": str(exc)}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _get_result(self, handler: JobHandler, job_id: str) -> dict[str, Any]:
        """Get job result."""
        try:
            result = handler.get_job_result(job_id)
            return {
                "status": "success",
                "job_id": job_id,
                "result": result,
            }
        except RuntimeError as exc:
            return {"status": "error", "message": str(exc)}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _wait(self, handler: JobHandler, job_id: str, timeout: int) -> dict[str, Any]:
        """Wait for job completion."""
        try:
            final_status = handler.wait_for_job(job_id, timeout)
            return {
                "status": "success",
                "job_id": job_id,
                "final_status": final_status,
            }
        except RuntimeError as exc:
            return {"status": "error", "message": str(exc)}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
