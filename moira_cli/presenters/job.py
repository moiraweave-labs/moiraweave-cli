"""Job output presenter."""

from __future__ import annotations

import json
from typing import Any

from rich.table import Table

from moira_cli.presenters import BasePresenter

_STATUS_STYLE: dict[str, str] = {
    "completed": "green",
    "failed": "red",
    "error": "red",
    "pending": "yellow",
    "running": "cyan",
}


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

    def present_list(self, jobs: list[dict[str, Any]]) -> None:
        """Present a table of jobs, newest first.

        :param jobs: List of job status dicts from the API.
        """
        if not jobs:
            self.ui.info("No jobs found.")
            return

        table = Table(
            show_header=True,
            header_style="bold cyan",
            border_style="dim",
            expand=False,
        )
        table.add_column("Job ID", style="dim", max_width=36)
        table.add_column("Pipeline")
        table.add_column("Status")
        table.add_column("Created At", style="dim")

        for job in jobs:
            job_state = str(job.get("status", "unknown")).lower()
            style = _STATUS_STYLE.get(job_state, "white")
            table.add_row(
                str(job.get("job_id", "")),
                str(job.get("pipeline_id", "")),
                f"[{style}]{job_state}[/]",
                str(job.get("created_at", ""))[:19],
            )

        self.ui.console.print(table)
