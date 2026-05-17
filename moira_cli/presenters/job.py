"""Job output presenter."""

from __future__ import annotations

from typing import Any

import json

from moira_cli.presenters import BasePresenter


class JobPresenter(BasePresenter):
    """Format job operation results."""

    def present_status(self, job_id: str, status: dict[str, Any]) -> None:
        """Present job status.

        :param job_id: Job identifier.
        :param status: Job status dict.
        """
        self.ui.header(f"Job: {job_id}")

        job_state = str(status.get("status", "unknown")).lower()
        if job_state == "completed":
            self.ui.success(f"Status: {job_state}")
        elif job_state in {"failed", "error"}:
            self.ui.error(f"Status: {job_state}")
        else:
            self.ui.info(f"Status: {job_state}")

        for key, value in status.items():
            if key != "status":
                self.ui.path(key.replace("_", " ").title(), str(value)[:100])

    def present_result(self, job_id: str, result: dict[str, Any]) -> None:
        """Present job result.

        :param job_id: Job identifier.
        :param result: Job result dict.
        """
        self.ui.header(f"Result: {job_id}")

        if isinstance(result, dict):
            for key, value in result.items():
                if isinstance(value, (dict, list)):
                    self.ui.console.print(f"[cyan]{key}:[/]")
                    self.ui.console.print(json.dumps(value, indent=2))
                else:
                    self.ui.path(key, str(value)[:100])
        else:
            self.ui.console.print(json.dumps(result, indent=2))

    def present_wait(self, job_id: str, final_status: dict[str, Any]) -> None:
        """Present final status after wait.

        :param job_id: Job identifier.
        :param final_status: Final job status dict.
        """
        job_state = str(final_status.get("status", "unknown")).lower()

        if job_state == "completed":
            self.ui.success(f"Job completed: {job_id}")
        else:
            self.ui.error(f"Job finished with status: {job_state}")

        for key, value in final_status.items():
            if key != "status":
                self.ui.path(key.replace("_", " ").title(), str(value)[:100])
