"""Integration tests for workload-oriented moira CLI workflows."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml


def _run(
    args: list[str], cwd: Path, *, expect_rc: int = 0
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["uv", "run", "moira", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    assert result.returncode == expect_rc, (
        f"moira {' '.join(args)} exited {result.returncode} "
        f"(expected {expect_rc})\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    return result


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    _run(
        ["init", "--non-interactive", "--name", "integ", "--registry", "ghcr.io/integ"],
        cwd=ws,
    )
    return ws


@pytest.mark.integration
class TestInitWorkflow:
    def test_moiraweave_yaml_created(self, workspace: Path) -> None:
        assert (workspace / "moiraweave.yaml").exists()

    def test_moiraweave_yaml_has_required_keys(self, workspace: Path) -> None:
        config = yaml.safe_load((workspace / "moiraweave.yaml").read_text())
        for key in ("name", "registry", "workloads_dir", "artifacts_dir", "deploy_dir"):
            assert key in config, f"moiraweave.yaml missing key: {key}"

    def test_default_dirs_created(self, workspace: Path) -> None:
        config = yaml.safe_load((workspace / "moiraweave.yaml").read_text())
        for dir_key in ("workloads_dir", "artifacts_dir", "deploy_dir"):
            expected = workspace / config[dir_key]
            assert expected.exists(), f"Directory {config[dir_key]} was not created"

    def test_generated_compose_includes_ui_by_default(self, workspace: Path) -> None:
        compose = yaml.safe_load((workspace / "docker-compose.yml").read_text())
        ui = compose["services"]["ui"]
        assert ui["image"] == "ghcr.io/moiraweave-labs/moiraweave-ui:latest"
        assert "profiles" not in ui
        assert ui["environment"]["API_PROXY_PASS"] == "http://api-gateway:8000"

    def test_generated_env_exposes_platform_ports(self, workspace: Path) -> None:
        env_text = (workspace / ".env").read_text()
        assert "API_GATEWAY_PORT=8000" in env_text
        assert "MOIRAWEAVE_UI_PORT=3000" in env_text


@pytest.mark.integration
class TestWorkloadScaffolding:
    def test_agent_workload_new_creates_directory(self, workspace: Path) -> None:
        _run(
            [
                "workload",
                "new",
                "hermes",
                "--type",
                "agent-service",
                "--image",
                "ghcr.io/nousresearch/hermes-agent:latest",
                "--mode",
                "session",
            ],
            cwd=workspace,
        )
        config = yaml.safe_load((workspace / "moiraweave.yaml").read_text())
        workload_dir = workspace / config["workloads_dir"] / "hermes"
        assert workload_dir.is_dir()

    def test_model_workload_yaml_is_valid(self, workspace: Path) -> None:
        _run(
            [
                "workload",
                "new",
                "mock-model",
                "--type",
                "model-service",
                "--image",
                "ghcr.io/example/mock-model:latest",
                "--mode",
                "sync",
                "--port",
                "8000",
            ],
            cwd=workspace,
        )
        config = yaml.safe_load((workspace / "moiraweave.yaml").read_text())
        workload_yaml = (
            workspace / config["workloads_dir"] / "mock-model" / "workload.yaml"
        )
        parsed = yaml.safe_load(workload_yaml.read_text())
        assert parsed["kind"] == "Workload"
        assert parsed["spec"]["type"] == "model-service"

    def test_workload_list_shows_created_workload(self, workspace: Path) -> None:
        _run(
            [
                "workload",
                "new",
                "mock-agent",
                "--type",
                "agent-service",
                "--image",
                "ghcr.io/example/mock-agent:latest",
            ],
            cwd=workspace,
        )
        result = _run(["workload", "list"], cwd=workspace)
        assert "mock-agent" in result.stdout


@pytest.mark.integration
class TestDeployGeneration:
    def test_deploy_local_generates_workload_compose(self, workspace: Path) -> None:
        _run(
            [
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
            cwd=workspace,
        )
        _run(["deploy", "local"], cwd=workspace)
        generated = (
            workspace / ".moiraweave" / "deploy" / "docker-compose.workloads.yml"
        )
        parsed = yaml.safe_load(generated.read_text())
        assert "mock-agent" in parsed["services"]
        assert parsed["services"]["mock-agent"]["networks"] == ["moiraweave-net"]

    def test_deploy_local_generates_multiple_agent_services(
        self, workspace: Path
    ) -> None:
        _run(
            [
                "workload",
                "new",
                "hermes",
                "--type",
                "agent-service",
                "--image",
                "ghcr.io/nousresearch/hermes-agent:latest",
                "--port",
                "8642",
                "--adapter",
                "hermes",
                "--service-name",
                "hermes",
            ],
            cwd=workspace,
        )
        _run(
            [
                "workload",
                "new",
                "openclaw",
                "--type",
                "agent-service",
                "--image",
                "ghcr.io/openclaw/openclaw:latest",
                "--port",
                "18789",
                "--adapter",
                "openclaw",
                "--service-name",
                "openclaw",
            ],
            cwd=workspace,
        )

        _run(["deploy", "local"], cwd=workspace)

        generated = (
            workspace / ".moiraweave" / "deploy" / "docker-compose.workloads.yml"
        )
        parsed = yaml.safe_load(generated.read_text())
        assert {"hermes", "openclaw"} <= set(parsed["services"])
        assert parsed["services"]["hermes"]["networks"] == ["moiraweave-net"]
        assert parsed["services"]["openclaw"]["networks"] == ["moiraweave-net"]
        assert parsed["services"]["hermes"]["ports"] == ["8642:8642"]
        assert parsed["services"]["openclaw"]["ports"] == ["18789:18789"]

    def test_deploy_k8s_generates_values(self, workspace: Path) -> None:
        _run(
            [
                "workload",
                "new",
                "mock-model",
                "--type",
                "model-service",
                "--image",
                "ghcr.io/example/mock-model:latest",
            ],
            cwd=workspace,
        )
        _run(["deploy", "k8s", "--env", "dev"], cwd=workspace)
        generated = workspace / ".moiraweave" / "deploy" / "values-workloads-dev.yaml"
        parsed = yaml.safe_load(generated.read_text())
        assert parsed["workloads"]["mock-model"]["type"] == "model-service"
        assert parsed["workloads"]["mock-model"]["deployment"]["mode"] == "managed"

    def test_deploy_k8s_generates_multiple_agent_workloads(
        self, workspace: Path
    ) -> None:
        for name, image, adapter, port in [
            (
                "hermes",
                "ghcr.io/nousresearch/hermes-agent:latest",
                "hermes",
                "8642",
            ),
            ("openclaw", "ghcr.io/openclaw/openclaw:latest", "openclaw", "18789"),
        ]:
            _run(
                [
                    "workload",
                    "new",
                    name,
                    "--type",
                    "agent-service",
                    "--image",
                    image,
                    "--port",
                    port,
                    "--adapter",
                    adapter,
                    "--service-name",
                    name,
                ],
                cwd=workspace,
            )

        _run(["deploy", "k8s", "--env", "dev"], cwd=workspace)

        generated = workspace / ".moiraweave" / "deploy" / "values-workloads-dev.yaml"
        parsed = yaml.safe_load(generated.read_text())
        assert {"hermes", "openclaw"} <= set(parsed["workloads"])
        assert parsed["workloads"]["hermes"]["deployment"]["serviceName"] == "hermes"
        assert (
            parsed["workloads"]["openclaw"]["deployment"]["serviceName"] == "openclaw"
        )
        assert parsed["workloads"]["openclaw"]["agent"]["adapter"] == "openclaw"
