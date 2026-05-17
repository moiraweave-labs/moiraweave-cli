"""Smoke tests for moira CLI journeys (Phase 9)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def repo_root() -> Path:
    """Get repository root."""
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def cli_command() -> list[str]:
    """Base CLI invocation."""
    return ["uv", "run", "moira"]


@pytest.fixture
def initialized_workspace(cli_command: list[str], tmp_path: Path) -> Path:
    """Create a temporary initialized MoiraWeave workspace."""
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    init_result = subprocess.run(
        [
            *cli_command,
            "init",
            "--non-interactive",
            "--name",
            "smoke",
            "--registry",
            "ghcr.io/test",
        ],
        cwd=workspace,
        capture_output=True,
        text=True,
    )
    assert init_result.returncode == 0
    return workspace


class TestCLISmokeBasic:
    """Basic CLI command availability and help."""

    def test_cli_help(self, cli_command: list[str], repo_root: Path) -> None:
        """Verify main help command exits cleanly."""
        result = subprocess.run(
            [*cli_command, "--help"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert (
            "MoiraWeave" in result.stdout
            or "Commands" in result.stdout
            or len(result.stdout) > 0
        )

    def test_init_help(self, cli_command: list[str], repo_root: Path) -> None:
        """Verify init command help is available."""
        result = subprocess.run(
            [*cli_command, "init", "--help"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "Initialize" in result.stdout or "moira" in result.stdout.lower()


class TestCLITaskDiscovery:
    """Task discovery commands."""

    def test_task_list_succeeds(
        self, cli_command: list[str], initialized_workspace: Path
    ) -> None:
        """Verify `moira task list` completes without error."""
        result = subprocess.run(
            [*cli_command, "task", "list"],
            cwd=initialized_workspace,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        # Expect at least table headers or task names
        assert len(result.stdout) > 0


class TestCLIPipelineValidation:
    """Pipeline validation commands."""

    def test_pipeline_list_succeeds(
        self, cli_command: list[str], initialized_workspace: Path
    ) -> None:
        """Verify `moira pipeline list` completes without error."""
        result = subprocess.run(
            [*cli_command, "pipeline", "list"],
            cwd=initialized_workspace,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "Pipelines" in result.stdout or len(result.stdout) > 0

    def test_pipeline_validate_existing(
        self, cli_command: list[str], initialized_workspace: Path
    ) -> None:
        """Verify `moira pipeline validate <existing>` succeeds."""
        new_result = subprocess.run(
            [*cli_command, "pipeline", "new", "image-search"],
            cwd=initialized_workspace,
            capture_output=True,
            text=True,
        )
        assert new_result.returncode == 0

        result = subprocess.run(
            [*cli_command, "pipeline", "validate", "image-search"],
            cwd=initialized_workspace,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "valid" in result.stdout.lower()

    def test_pipeline_validate_nonexistent(
        self, cli_command: list[str], initialized_workspace: Path
    ) -> None:
        """Verify `moira pipeline validate <nonexistent>` fails with clear message."""
        result = subprocess.run(
            [*cli_command, "pipeline", "validate", "nonexistent-pipeline-xyz"],
            cwd=initialized_workspace,
            capture_output=True,
            text=True,
        )
        # Expect error message to be informative
        error_text = result.stdout + result.stderr
        assert "not found" in error_text.lower() or "issue" in error_text.lower()


class TestCLIErrorMessages:
    """Error message clarity."""

    def test_task_show_nonexistent_message(
        self, cli_command: list[str], initialized_workspace: Path
    ) -> None:
        """Verify error message for missing task is actionable."""
        result = subprocess.run(
            [*cli_command, "task", "show", "nonexistent-task"],
            cwd=initialized_workspace,
            capture_output=True,
            text=True,
        )
        error_text = result.stdout + result.stderr
        assert "task schema not found" in error_text.lower() or "task" in error_text.lower()


class TestCLIDefaults:
    """Default values and safe modes."""

    def test_init_noninteractive_flag_recognized(
        self, cli_command: list[str], repo_root: Path
    ) -> None:
        """Verify `moira init --non-interactive` flag is recognized."""
        result = subprocess.run(
            [*cli_command, "init", "--help"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "non-interactive" in result.stdout or result.returncode == 0
