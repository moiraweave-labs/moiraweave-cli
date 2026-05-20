"""Job management handler."""

from __future__ import annotations

import os
from typing import Any

import httpx

from moira_cli.handlers import BaseHandler


class JobHandler(BaseHandler):
    """Handle job operations (query only - no creation)."""

    def __init__(self, repo_root=None, api_url: str = "http://localhost:8000") -> None:
        """Initialize job handler.

        :param repo_root: Optional repository root.
        :param api_url: API base URL for job queries.
        """
        super().__init__(repo_root)
        self.api_url = api_url

    @staticmethod
    def _auth_headers() -> dict[str, str]:
        """Return Authorization header dict when MOIRA_TOKEN is set.

        :returns: Headers dict, empty if no token is configured.
        """
        token = os.environ.get("MOIRA_TOKEN")
        return {"Authorization": f"Bearer {token}"} if token else {}

    def list_jobs(
        self,
        pipeline_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List recent jobs for the current user.

        :param pipeline_id: Optional pipeline name filter.
        :param limit: Maximum number of jobs to return.
        :returns: List of job status dicts, newest first.
        :raises RuntimeError: If API request fails.
        """
        params: list[tuple[str, str]] = []
        if pipeline_id:
            params.append(("pipeline_id", pipeline_id))
        params.append(("limit", str(limit)))
        query = "&".join(f"{k}={v}" for k, v in params)
        url = f"{self.api_url}/v1/pipelines/jobs?{query}"
        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.get(url, headers=self._auth_headers())
                response.raise_for_status()
                data = response.json()
                return data if isinstance(data, list) else []
        except Exception as exc:
            raise RuntimeError(f"Failed to list jobs: {exc}") from exc

    def get_job_status(self, job_id: str) -> dict[str, Any]:
        """Get job status from API.

        :param job_id: Job identifier.
        :returns: Job status dict.
        :raises RuntimeError: If API request fails.
        """
        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.get(
                    f"{self.api_url}/v1/pipelines/jobs/{job_id}",
                    headers=self._auth_headers(),
                )
                response.raise_for_status()
                data = response.json()
                return data if isinstance(data, dict) else {"data": data}
        except Exception as exc:
            raise RuntimeError(f"Failed to get job status: {exc}") from exc

    def get_job_result(self, job_id: str) -> dict[str, Any]:
        """Get job result from API.

        :param job_id: Job identifier.
        :returns: Job result dict.
        :raises RuntimeError: If API request fails or result not found.
        """
        urls = [
            f"{self.api_url}/v1/pipelines/jobs/{job_id}",
        ]

        last_error = None
        for url in urls:
            try:
                with httpx.Client(timeout=15.0) as client:
                    response = client.get(url, headers=self._auth_headers())
                    response.raise_for_status()
                    data = response.json()
                    result = (
                        data.get("result", data) if isinstance(data, dict) else data
                    )
                    return result if isinstance(result, dict) else {"data": result}
            except Exception as exc:
                last_error = exc
                continue

        raise RuntimeError(
            f"No result endpoint available for job {job_id}: {last_error}"
        )

    def wait_for_job(self, job_id: str, timeout_seconds: int = 120) -> dict[str, Any]:
        """Wait for job completion with timeout.

        :param job_id: Job identifier.
        :param timeout_seconds: Max wait time.
        :returns: Final job status.
        :raises RuntimeError: If timeout or error.
        """
        import time

        start = time.time()
        while time.time() - start < timeout_seconds:
            try:
                status = self.get_job_status(job_id)
                state = str(status.get("status", "unknown")).lower()

                if state in {"completed", "failed", "error"}:
                    return status

                time.sleep(1)
            except RuntimeError:
                time.sleep(1)

        raise RuntimeError(f"Job {job_id} did not complete within {timeout_seconds}s")
