"""Smoke tests for the MoiraWeave workload CLI."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from moira_cli import main as cli_main


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
        assert "demo" in result.stdout
        assert "up" in result.stdout

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
    def test_demo_agent_creates_runnable_manifest(
        self, cli_command: list[str], initialized_workspace: Path
    ) -> None:
        result = subprocess.run(
            [*cli_command, "demo", "agent"],
            cwd=initialized_workspace,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

        manifest_path = (
            initialized_workspace
            / ".moiraweave"
            / "workloads"
            / "demo-agent"
            / "workload.yaml"
        )
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        assert manifest["spec"]["image"] == "python:3.13-slim"
        assert manifest["spec"]["agent"]["messagePath"] == "/message"
        assert manifest["spec"]["command"] == ["python", "-u", "-c"]
        assert "OPENAI_API_KEY" not in manifest["spec"].get("secrets", [])

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
            initialized_workspace
            / ".moiraweave"
            / "workloads"
            / "hermes"
            / "workload.yaml"
        )
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        assert manifest["metadata"]["name"] == "hermes"
        assert manifest["spec"]["type"] == "agent-service"
        assert manifest["spec"]["ports"][0]["port"] == 8642
        assert manifest["spec"]["env"]["API_SERVER_ENABLED"] == "true"
        assert manifest["spec"]["env"]["API_SERVER_HOST"] == "0.0.0.0"
        assert manifest["spec"]["env"]["API_SERVER_PORT"] == "8642"
        assert manifest["spec"]["deployment"]["mode"] == "managed"
        assert manifest["spec"]["deployment"]["targets"] == ["local", "kubernetes"]
        assert manifest["spec"]["agent"]["adapter"] == "hermes"
        assert manifest["spec"]["agent"]["workspaceMount"] == "/workspace"
        assert manifest["spec"]["agent"]["authTokenEnv"] == "HERMES_API_SERVER_KEY"
        assert manifest["spec"]["agent"]["model"] == "hermes-agent"
        assert manifest["spec"]["agent"]["instructions"] == "Be operational."
        assert manifest["spec"]["agent"]["pollIntervalSeconds"] == 1.5
        assert "telegram" in manifest["spec"]["agent"]["exposedChannels"]

    def test_workload_new_external_agent_requires_endpoint(
        self, cli_command: list[str], initialized_workspace: Path
    ) -> None:
        result = subprocess.run(
            [
                *cli_command,
                "workload",
                "new",
                "external-hermes",
                "--type",
                "agent-service",
                "--deployment-mode",
                "external",
                "--endpoint",
                "https://agents.example.com/hermes",
                "--adapter",
                "hermes",
            ],
            cwd=initialized_workspace,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

        manifest_path = (
            initialized_workspace
            / ".moiraweave"
            / "workloads"
            / "external-hermes"
            / "workload.yaml"
        )
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        assert "image" not in manifest["spec"]
        assert manifest["spec"]["endpoint"] == "https://agents.example.com/hermes"
        assert manifest["spec"]["deployment"]["mode"] == "external"

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
        generated = (
            initialized_workspace
            / ".moiraweave"
            / "deploy"
            / "docker-compose.workloads.yml"
        )
        assert generated.exists()
        parsed = yaml.safe_load(generated.read_text(encoding="utf-8"))
        assert "mock-agent" in parsed["services"]
        assert parsed["services"]["mock-agent"]["networks"] == ["moiraweave-net"]
        assert parsed["networks"]["moiraweave-net"]["name"] == "moiraweave-net"

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
        assert ui["networks"] == ["moiraweave-net"]
        assert compose["networks"]["moiraweave-net"]["name"] == "moiraweave-net"


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


class TestCLIDeployRegistration:
    def test_up_initializes_generates_starts_and_registers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        commands: list[list[str]] = []
        registered: list[dict[str, object]] = []

        def fake_run(command: list[str], cwd: Path | None = None) -> str:
            del cwd
            commands.append(command)
            return "started"

        def fake_register(
            manifests: list[dict[str, object]],
            *,
            target: str,
            status: str,
            api_url: str,
        ) -> None:
            assert target == "local"
            assert status == "running"
            assert api_url == "http://api:8000"
            registered.extend(manifests)

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(cli_main, "_run_command", fake_run)
        monkeypatch.setattr(cli_main, "_wait_for_api_ready", lambda *_args: True)
        monkeypatch.setattr(cli_main, "_dev_login_token", lambda _api_url: "token")
        monkeypatch.setattr(cli_main, "_register_workload_deployments", fake_register)

        cli_main.up(
            api_url="http://api:8000",
            wait_timeout=1,
            demo_agent=True,
            register=True,
        )

        assert (tmp_path / "moiraweave.yaml").exists()
        assert (
            tmp_path / ".moiraweave" / "deploy" / "docker-compose.workloads.yml"
        ).exists()
        assert commands[0][:5] == [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
        ]
        assert registered[0]["metadata"]["name"] == "demo-agent"

    def test_register_workload_deployments_posts_manifest_and_deployment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, str, dict[str, object] | None]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object] | None = None,
        ) -> dict[str, object]:
            calls.append((method, url, payload))
            return {}

        monkeypatch.setattr(cli_main, "_request_json", fake_request)
        manifest = {
            "apiVersion": "moiraweave.io/v1alpha1",
            "kind": "Workload",
            "metadata": {"name": "hermes"},
            "spec": {
                "type": "agent-service",
                "image": "ghcr.io/nousresearch/hermes-agent:latest",
                "deployment": {
                    "mode": "managed",
                    "targets": ["local", "kubernetes"],
                    "serviceName": "hermes",
                },
                "ports": [{"name": "http", "port": 8642}],
                "agent": {"adapter": "hermes"},
            },
            "_path": "/tmp/workload.yaml",
        }

        cli_main._register_workload_deployments(
            [manifest],
            target="local",
            status="running",
            api_url="http://api:8000",
        )

        assert calls[0] == (
            "POST",
            "http://api:8000/v1/workloads",
            {key: value for key, value in manifest.items() if key != "_path"},
        )
        assert calls[1][0] == "POST"
        assert calls[1][1] == "http://api:8000/v1/workloads/hermes/deployments"
        assert calls[1][2] is not None
        assert calls[1][2]["target"] == "local"
        assert calls[1][2]["status"] == "running"
        assert calls[1][2]["endpoint"] == "http://hermes:8642"
        metadata = calls[1][2]["metadata"]
        assert isinstance(metadata, dict)
        assert metadata["service_name"] == "hermes"

    def test_register_workload_deployments_records_external_agents(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, str, dict[str, object] | None]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object] | None = None,
        ) -> dict[str, object]:
            calls.append((method, url, payload))
            return {}

        monkeypatch.setattr(cli_main, "_request_json", fake_request)
        manifest = {
            "apiVersion": "moiraweave.io/v1alpha1",
            "kind": "Workload",
            "metadata": {"name": "external-hermes"},
            "spec": {
                "type": "agent-service",
                "endpoint": "https://agents.example.com/hermes",
                "deployment": {"mode": "external"},
                "agent": {"adapter": "hermes"},
            },
        }

        cli_main._register_workload_deployments(
            [manifest],
            target="local",
            status="running",
            api_url="http://api:8000",
        )

        assert calls[1][1] == (
            "http://api:8000/v1/workloads/external-hermes/deployments"
        )
        assert calls[1][2] is not None
        assert calls[1][2]["target"] == "external"
        assert calls[1][2]["endpoint"] == "https://agents.example.com/hermes"
