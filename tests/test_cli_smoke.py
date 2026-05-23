"""Smoke tests for the MoiraWeave workload CLI."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def cli_command() -> list[str]:
    return ["uv", "run", "moira"]


@pytest.fixture
def initialized_workspace(cli_command: list[str], tmp_path: Path) -> Path:
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
    assert init_result.returncode == 0, init_result.stderr
    return workspace


class TestCLISmokeBasic:
    def test_cli_help(self, cli_command: list[str], repo_root: Path) -> None:
        result = subprocess.run(
            [*cli_command, "--help"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "workload" in result.stdout
        assert "run" in result.stdout
        assert "agent" in result.stdout

    def test_init_help(self, cli_command: list[str], repo_root: Path) -> None:
        result = subprocess.run(
            [*cli_command, "init", "--help"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "Initialize" in result.stdout or "moira" in result.stdout.lower()


class TestCLIWorkloads:
    def test_workload_new_creates_manifest(
        self, cli_command: list[str], initialized_workspace: Path
    ) -> None:
        result = subprocess.run(
            [
                *cli_command,
                "workload",
                "new",
                "hermes",
                "--type",
                "agent-service",
                "--image",
                "ghcr.io/nousresearch/hermes-agent:latest",
                "--port",
                "8642",
                "--env",
                "API_SERVER_ENABLED=true",
                "--env",
                "API_SERVER_HOST=0.0.0.0",
                "--env",
                "API_SERVER_PORT=8642",
                "--secret",
                "OPENAI_API_KEY",
                "--adapter",
                "hermes",
                "--channel",
                "telegram",
                "--workspace-mount",
                "/workspace",
                "--auth-token-env",
                "HERMES_API_SERVER_KEY",
                "--model",
                "hermes-agent",
                "--instructions",
                "Be operational.",
                "--poll-interval-seconds",
                "1.5",
            ],
            cwd=initialized_workspace,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

        manifest_path = (
            initialized_workspace / ".moiraweave" / "workloads" / "hermes" / "workload.yaml"
        )
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        assert manifest["metadata"]["name"] == "hermes"
        assert manifest["spec"]["type"] == "agent-service"
        assert manifest["spec"]["ports"][0]["port"] == 8642
        assert manifest["spec"]["env"]["API_SERVER_ENABLED"] == "true"
        assert manifest["spec"]["env"]["API_SERVER_HOST"] == "0.0.0.0"
        assert manifest["spec"]["env"]["API_SERVER_PORT"] == "8642"
        assert manifest["spec"]["agent"]["adapter"] == "hermes"
        assert manifest["spec"]["agent"]["workspaceMount"] == "/workspace"
        assert manifest["spec"]["agent"]["authTokenEnv"] == "HERMES_API_SERVER_KEY"
        assert manifest["spec"]["agent"]["model"] == "hermes-agent"
        assert manifest["spec"]["agent"]["instructions"] == "Be operational."
        assert manifest["spec"]["agent"]["pollIntervalSeconds"] == 1.5
        assert "telegram" in manifest["spec"]["agent"]["exposedChannels"]

    def test_workload_list_succeeds(
        self, cli_command: list[str], initialized_workspace: Path
    ) -> None:
        subprocess.run(
            [
                *cli_command,
                "workload",
                "new",
                "mock-model",
                "--type",
                "model-service",
                "--image",
                "ghcr.io/example/mock-model:latest",
            ],
            cwd=initialized_workspace,
            capture_output=True,
            text=True,
            check=True,
        )
        result = subprocess.run(
            [*cli_command, "workload", "list"],
            cwd=initialized_workspace,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "mock-model" in result.stdout

    def test_deploy_local_generates_compose(
        self, cli_command: list[str], initialized_workspace: Path
    ) -> None:
        subprocess.run(
            [
                *cli_command,
                "workload",
                "new",
                "mock-agent",
                "--type",
                "agent-service",
                "--image",
                "ghcr.io/example/mock-agent:latest",
                "--port",
                "8000",
            ],
            cwd=initialized_workspace,
            capture_output=True,
            text=True,
            check=True,
        )

        result = subprocess.run(
            [*cli_command, "deploy", "local"],
            cwd=initialized_workspace,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        generated = initialized_workspace / ".moiraweave" / "deploy" / "docker-compose.workloads.yml"
        assert generated.exists()
        assert "mock-agent" in generated.read_text(encoding="utf-8")

    def test_init_compose_includes_integrated_ui(
        self, initialized_workspace: Path
    ) -> None:
        compose = yaml.safe_load(
            (initialized_workspace / "docker-compose.yml").read_text(encoding="utf-8")
        )
        ui = compose["services"]["ui"]
        assert ui["image"] == "ghcr.io/moiraweave-labs/moiraweave-ui:latest"
        assert "profiles" not in ui
        assert ui["ports"] == ["${MOIRAWEAVE_UI_PORT:-3000}:80"]


class TestCLIDefaults:
    def test_init_noninteractive_flag_recognized(
        self, cli_command: list[str], repo_root: Path
    ) -> None:
        result = subprocess.run(
            [*cli_command, "init", "--help"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "non-interactive" in result.stdout or result.returncode == 0
