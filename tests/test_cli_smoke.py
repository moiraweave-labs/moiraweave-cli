"""Smoke tests for the MoiraWeave workload CLI."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest
import yaml

from moira_cli import main as cli_main


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def cli_command() -> list[str]:
    return ["uv", "run", "--frozen", "moira"]


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
        assert "security" in result.stdout
        assert "env" in result.stdout

    def test_init_help(self, cli_command: list[str], repo_root: Path) -> None:
        result = subprocess.run(
            [*cli_command, "init", "--help"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "Initialize" in result.stdout or "moira" in result.stdout.lower()


class TestDeploymentControllerHeartbeat:
    def test_controller_command_heartbeats_while_command_runs(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        heartbeats: list[tuple[str, str, str]] = []

        monkeypatch.setattr(
            cli_main,
            "_heartbeat_deployment_operation",
            lambda api_url, operation_id, controller_id, **_kwargs: (
                heartbeats.append((api_url, operation_id, controller_id)) or {}
            ),
        )

        def fake_run(command: list[str], cwd: Path | None = None) -> tuple[int, str]:
            del command, cwd
            deadline = time.monotonic() + 1.0
            while len(heartbeats) < 2 and time.monotonic() < deadline:
                time.sleep(0.005)
            return 0, "done"

        monkeypatch.setattr(cli_main, "_run_controller_command", fake_run)

        result = cli_main._run_controller_command_with_heartbeat(
            ["helm", "upgrade"],
            cwd=tmp_path,
            api_url="http://api:8000",
            operation_id="op-1",
            controller_id="controller-1",
            interval_seconds=0.01,
        )

        assert result == (0, "done")
        assert len(heartbeats) >= 2
        assert set(heartbeats) == {("http://api:8000", "op-1", "controller-1")}

    def test_controller_lists_queued_and_expired_running_operations(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        requests: list[str] = []

        def fake_request(
            method: str, url: str, payload: dict[str, object] | None = None
        ) -> dict[str, object]:
            del method, payload
            requests.append(url)
            if "status=queued" in url:
                return {
                    "data": [
                        {
                            "operation_id": "queued-1",
                            "status": "queued",
                            "lease_expires_at": None,
                        }
                    ]
                }
            if "status=running" in url:
                return {
                    "data": [
                        {
                            "operation_id": "running-expired",
                            "status": "running",
                            "lease_expires_at": "2020-01-01T00:00:00+00:00",
                        },
                        {
                            "operation_id": "running-active",
                            "status": "running",
                            "lease_expires_at": "2999-01-01T00:00:00+00:00",
                        },
                    ]
                }
            return {"data": []}

        monkeypatch.setattr(cli_main, "_request_json", fake_request)

        operations = cli_main._list_controller_operations(
            "http://api:8000",
            target="kubernetes",
            env="dev",
            limit=5,
        )

        assert [operation["operation_id"] for operation in operations] == [
            "queued-1",
            "running-expired",
        ]
        assert any("status=queued" in url for url in requests)
        assert any("status=running" in url for url in requests)


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
                "--external-channel",
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
        assert manifest["spec"]["persistence"] == {
            "enabled": True,
            "mountPath": "/workspace",
        }
        assert manifest["spec"]["agent"]["adapter"] == "hermes"
        assert manifest["spec"]["agent"]["workspaceMount"] == "/workspace"
        assert manifest["spec"]["agent"]["authTokenEnv"] == "HERMES_API_SERVER_KEY"
        assert manifest["spec"]["agent"]["model"] == "hermes-agent"
        assert manifest["spec"]["agent"]["instructions"] == "Be operational."
        assert manifest["spec"]["agent"]["pollIntervalSeconds"] == 1.5
        assert manifest["spec"]["agent"]["exposedChannels"] == ["ui", "api"]
        assert manifest["spec"]["agent"]["externalOwnedChannels"] == ["telegram"]
        assert manifest["spec"]["agent"]["toolOwnership"] == "runtime"
        requirements = manifest["spec"]["agent"]["runtimeRequirements"]
        assert requirements["filesystem"]["persistentWorkspace"] is True
        assert requirements["network"]["egress"] == "enabled"
        assert requirements["webSearch"]["enabled"] is True
        assert requirements["browser"]["mode"] == "runtime-managed"

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

    def test_secrets_list_shows_required_names(
        self, cli_command: list[str], initialized_workspace: Path
    ) -> None:
        subprocess.run(
            [
                *cli_command,
                "workload",
                "new",
                "hermes",
                "--type",
                "agent-service",
                "--image",
                "ghcr.io/nousresearch/hermes-agent:latest",
                "--secret",
                "OPENAI_API_KEY",
                "--auth-token-env",
                "HERMES_API_SERVER_KEY",
            ],
            cwd=initialized_workspace,
            capture_output=True,
            text=True,
            check=True,
        )

        result = subprocess.run(
            [*cli_command, "secrets", "list", "--workload", "hermes"],
            cwd=initialized_workspace,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "OPENAI_API_KEY" in result.stdout
        assert "HERMES_API_SERVER_KEY" in result.stdout
        assert "sk-" not in result.stdout

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
        api_gateway = compose["services"]["api-gateway"]
        assert api_gateway["environment"]["EMBEDDING_MODEL"] == "${EMBEDDING_MODEL:-}"
        assert api_gateway["environment"]["HF_HOME"] == "/tmp/huggingface"
        assert api_gateway["environment"]["FASTEMBED_CACHE_PATH"] == "/tmp/fastembed"

        env_file = (initialized_workspace / ".env").read_text(encoding="utf-8")
        assert "EMBEDDING_MODEL=\n" in env_file

        ui = compose["services"]["ui"]
        assert ui["image"] == (
            "${MOIRAWEAVE_UI_IMAGE:-ghcr.io/moiraweave-labs/moiraweave-ui:latest}"
        )
        assert "profiles" not in ui
        assert ui["ports"] == ["${MOIRAWEAVE_UI_PORT:-3000}:80"]
        assert ui["networks"] == ["moiraweave-net"]
        assert compose["networks"]["moiraweave-net"]["name"] == "moiraweave-net"

    def test_workload_preflight_prints_api_action_guide(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, str, dict[str, object] | None]] = []
        printed_guides: list[object] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object] | None = None,
        ) -> dict[str, object]:
            calls.append((method, url, payload))
            return {
                "workload_name": "hermes",
                "target": "kubernetes",
                "status": "warning",
                "checks": [
                    {
                        "name": "deployment_record",
                        "status": "warning",
                        "message": "No kubernetes deployment record is registered.",
                        "remediation": "Sync deployment record.",
                        "metadata": {},
                    }
                ],
                "recommendations": ["Sync deployment record."],
                "action_guide": [
                    {
                        "title": "Sync Deployment Record",
                        "state": "warning",
                        "detail": "Register or sync the kubernetes/dev deployment record.",
                        "command": "moira deploy k8s --env dev --register",
                    }
                ],
            }

        monkeypatch.setattr(cli_main, "_request_json", fake_request)
        monkeypatch.setattr(
            cli_main,
            "_print_action_guide",
            lambda action_guide: printed_guides.append(action_guide),
        )

        cli_main.workload_preflight(
            "hermes",
            target="k8s",
            env="dev",
            api_url="http://api:8000",
            json_output=False,
        )

        assert calls == [
            (
                "POST",
                "http://api:8000/v1/workloads/hermes/preflight",
                {"target": "kubernetes", "env": "dev"},
            )
        ]
        assert printed_guides == [
            [
                {
                    "title": "Sync Deployment Record",
                    "state": "warning",
                    "detail": "Register or sync the kubernetes/dev deployment record.",
                    "command": "moira deploy k8s --env dev --register",
                }
            ]
        ]


class TestCLIRuns:
    def test_run_list_filters_by_workload_and_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, str, dict[str, object] | None]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object] | None = None,
        ) -> dict[str, object]:
            calls.append((method, url, payload))
            return {"data": [{"run_id": "run-prod", "status": "succeeded"}]}

        monkeypatch.setattr(cli_main, "_request_json", fake_request)

        cli_main.run_list(
            workload="hermes",
            env="prod",
            limit=25,
            offset=10,
            api_url="http://api:8000",
        )

        assert calls == [
            (
                "GET",
                "http://api:8000/v1/runs?limit=25&offset=10&workload_name=hermes&env=prod",
                None,
            )
        ]

    def test_run_artifacts_can_filter_by_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, str, dict[str, object] | None]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object] | None = None,
        ) -> dict[str, object]:
            calls.append((method, url, payload))
            return {"data": [{"name": "prod.json"}]}

        monkeypatch.setattr(cli_main, "_request_json", fake_request)

        cli_main.run_artifacts(
            "run-prod",
            env="prod",
            api_url="http://api:8000",
        )

        assert calls == [
            (
                "GET",
                "http://api:8000/v1/artifacts?run_id=run-prod&env=prod",
                None,
            )
        ]

    def test_run_dead_letter_list_fetches_entries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, str, dict[str, object] | None]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object] | None = None,
        ) -> dict[str, object]:
            calls.append((method, url, payload))
            return {
                "data": [
                    {
                        "message_id": "1-0",
                        "reason": "invalid_run_message",
                        "source_id": "0-0",
                    }
                ]
            }

        monkeypatch.setattr(cli_main, "_request_json", fake_request)

        cli_main.run_dead_letter_list(
            limit=25,
            api_url="http://api:8000",
            json_output=False,
        )

        assert calls == [
            (
                "GET",
                "http://api:8000/v1/runs/dead-letter?limit=25",
                None,
            )
        ]

    def test_run_dead_letter_purge_deletes_entry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, str, dict[str, object] | None]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object] | None = None,
        ) -> dict[str, object]:
            calls.append((method, url, payload))
            return {"message_id": "1-0", "reason": "invalid_run_message"}

        monkeypatch.setattr(cli_main, "_request_json", fake_request)

        cli_main.run_dead_letter_purge("1-0", api_url="http://api:8000")

        assert calls == [
            (
                "DELETE",
                "http://api:8000/v1/runs/dead-letter/1-0",
                None,
            )
        ]

    def test_run_dead_letter_replay_posts_entry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, str, dict[str, object] | None]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object] | None = None,
        ) -> dict[str, object]:
            calls.append((method, url, payload))
            return {
                "message_id": "1-0",
                "replayed_message_id": "2-0",
                "run_id": "run-1",
            }

        monkeypatch.setattr(cli_main, "_request_json", fake_request)

        cli_main.run_dead_letter_replay("1-0", api_url="http://api:8000")

        assert calls == [
            (
                "POST",
                "http://api:8000/v1/runs/dead-letter/1-0/replay",
                None,
            )
        ]


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


class TestCLISecurity:
    def test_security_bootstrap_admin_posts_bootstrap_payload(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, str, dict[str, object] | None, bool | None]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object] | None = None,
            *,
            retry_local_login: bool = True,
        ) -> dict[str, object]:
            calls.append((method, url, payload, retry_local_login))
            return {
                "subject": "owner",
                "role": "admin",
                "access_token": "token",
            }

        monkeypatch.setattr(cli_main, "_request_json", fake_request)

        cli_main.security_bootstrap_admin(
            "owner",
            password="very-strong-password",
            display_name="Owner",
            api_url="http://api:8000",
        )

        assert calls == [
            (
                "POST",
                "http://api:8000/auth/bootstrap/admin",
                {
                    "subject": "owner",
                    "password": "very-strong-password",
                    "display_name": "Owner",
                },
                False,
            )
        ]

    def test_security_user_create_posts_user_payload(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, str, dict[str, object] | None]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object] | None = None,
        ) -> dict[str, object]:
            calls.append((method, url, payload))
            return {
                "subject": "alice",
                "role": "operator",
                "display_name": "Alice Operator",
            }

        monkeypatch.setattr(cli_main, "_request_json", fake_request)

        cli_main.security_user_create(
            "alice",
            password="correct-horse",
            role="operator",
            display_name="Alice Operator",
            api_url="http://api:8000",
        )

        assert calls == [
            (
                "POST",
                "http://api:8000/auth/users",
                {
                    "subject": "alice",
                    "password": "correct-horse",
                    "role": "operator",
                    "display_name": "Alice Operator",
                },
            )
        ]

    def test_security_user_update_patches_metadata(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, str, dict[str, object] | None]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object] | None = None,
        ) -> dict[str, object]:
            calls.append((method, url, payload))
            return {"subject": "alice", "role": "viewer"}

        monkeypatch.setattr(cli_main, "_request_json", fake_request)

        cli_main.security_user_update(
            "alice",
            role="viewer",
            display_name="Alice Viewer",
            api_url="http://api:8000",
        )

        assert calls == [
            (
                "PATCH",
                "http://api:8000/auth/users/alice",
                {"display_name": "Alice Viewer", "role": "viewer"},
            )
        ]

    def test_security_user_password_and_enable_commands(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, str, dict[str, object] | None]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object] | None = None,
        ) -> dict[str, object]:
            calls.append((method, url, payload))
            return {"subject": "alice", "role": "operator"}

        monkeypatch.setattr(cli_main, "_request_json", fake_request)

        cli_main.security_user_password_change(
            "alice",
            current_password="correct-horse",
            new_password="new-correct-horse",
            api_url="http://api:8000",
        )
        cli_main.security_user_password_reset(
            "alice",
            new_password="reset-correct-horse",
            api_url="http://api:8000",
        )
        cli_main.security_user_enable("alice", api_url="http://api:8000")

        assert calls == [
            (
                "POST",
                "http://api:8000/auth/users/alice/password/change",
                {
                    "current_password": "correct-horse",
                    "new_password": "new-correct-horse",
                },
            ),
            (
                "POST",
                "http://api:8000/auth/users/alice/password/reset",
                {"new_password": "reset-correct-horse"},
            ),
            ("POST", "http://api:8000/auth/users/alice/enable", None),
        ]

    def test_security_team_update_patches_metadata(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, str, dict[str, object] | None]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object] | None = None,
        ) -> dict[str, object]:
            calls.append((method, url, payload))
            return {"team_id": "agents", "name": "Agent Platform"}

        monkeypatch.setattr(cli_main, "_request_json", fake_request)

        cli_main.security_team_update(
            "agents",
            name="Agent Platform",
            description="Prod agent ops",
            api_url="http://api:8000",
        )

        assert calls == [
            (
                "PATCH",
                "http://api:8000/auth/teams/agents",
                {"name": "Agent Platform", "description": "Prod agent ops"},
            )
        ]

    def test_security_team_add_member_posts_membership(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, str, dict[str, object] | None]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object] | None = None,
        ) -> dict[str, object]:
            calls.append((method, url, payload))
            return {"team_id": "agents", "subject": "team-bot", "role": "operator"}

        monkeypatch.setattr(cli_main, "_request_json", fake_request)

        cli_main.security_team_add_member(
            "agents",
            "team-bot",
            role="operator",
            api_url="http://api:8000",
        )

        assert calls == [
            (
                "POST",
                "http://api:8000/auth/teams/agents/members",
                {"subject": "team-bot", "role": "operator"},
            )
        ]

    def test_security_team_remove_member_deletes_membership(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, str, dict[str, object] | None]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object] | None = None,
        ) -> dict[str, object]:
            calls.append((method, url, payload))
            return {"team_id": "agents", "subject": "team-bot", "role": "operator"}

        monkeypatch.setattr(cli_main, "_request_json", fake_request)

        cli_main.security_team_remove_member(
            "agents",
            "team-bot",
            api_url="http://api:8000",
        )

        assert calls == [
            (
                "DELETE",
                "http://api:8000/auth/teams/agents/members/team-bot",
                None,
            )
        ]

    def test_security_api_key_create_posts_team_scope(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, str, dict[str, object] | None]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object] | None = None,
        ) -> dict[str, object]:
            calls.append((method, url, payload))
            return {
                "key_id": "key-1",
                "name": "team automation",
                "subject": "team-bot",
                "role": "operator",
                "team_id": "agents",
                "secret": "mwk_test",
            }

        monkeypatch.setattr(cli_main, "_request_json", fake_request)

        cli_main.security_api_key_create(
            "team automation",
            "team-bot",
            role="operator",
            team_id="agents",
            api_url="http://api:8000",
        )

        assert calls == [
            (
                "POST",
                "http://api:8000/auth/api-keys",
                {
                    "name": "team automation",
                    "subject": "team-bot",
                    "role": "operator",
                    "team_id": "agents",
                },
            )
        ]

    def test_environment_list_fetches_control_plane_environments(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, str, dict[str, object] | None]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object] | None = None,
        ) -> dict[str, object]:
            calls.append((method, url, payload))
            return {
                "data": [
                    {
                        "name": "local",
                        "workload_count": 1,
                        "deployment_count": 1,
                        "operation_count": 0,
                    }
                ]
            }

        monkeypatch.setattr(cli_main, "_request_json", fake_request)

        cli_main.environment_list(api_url="http://api:8000", json_output=False)

        assert calls == [("GET", "http://api:8000/v1/environments", None)]

    def test_ops_alerts_fetches_operations_alerts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, str, dict[str, object] | None]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object] | None = None,
        ) -> dict[str, object]:
            calls.append((method, url, payload))
            return {
                "data": [
                    {
                        "severity": "warning",
                        "title": "Dead-letter messages need review",
                        "detail": "1 message",
                        "action": "Replay or purge",
                        "command": "moira run dead-letter list",
                    }
                ]
            }

        monkeypatch.setattr(cli_main, "_request_json", fake_request)

        cli_main.ops_alerts(
            env="prod",
            scope="all",
            api_url="http://api:8000",
            json_output=False,
        )

        assert calls == [
            (
                "GET",
                "http://api:8000/v1/operations/alerts?env=prod&scope=all",
                None,
            )
        ]


class TestCLIDeployRegistration:
    def test_up_initializes_generates_starts_and_registers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        commands: list[list[str]] = []
        registered: list[dict[str, object]] = []
        ui_waits: list[tuple[str, int]] = []

        def fake_run(command: list[str], cwd: Path | None = None) -> str:
            del cwd
            commands.append(command)
            return "started"

        def fake_register(
            manifests: list[dict[str, object]],
            *,
            target: str,
            env: str,
            status: str,
            api_url: str,
        ) -> None:
            assert target == "local"
            assert env == "local"
            assert status == "running"
            assert api_url == "http://api:8000"
            registered.extend(manifests)

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(cli_main, "_run_command", fake_run)
        monkeypatch.setattr(cli_main, "_wait_for_api_ready", lambda *_args: True)
        monkeypatch.setattr(
            cli_main,
            "_wait_for_url_reachable",
            lambda url, timeout: ui_waits.append((url, timeout)) or (True, "HTTP 200"),
        )
        monkeypatch.setattr(cli_main, "_dev_login_token", lambda _api_url: "token")
        monkeypatch.setattr(cli_main, "_register_workload_deployments", fake_register)

        cli_main.up(
            api_url="http://api:8000",
            wait_timeout=1,
            ui_wait_timeout=2,
            demo_agent=True,
            register=True,
            skip_doctor=True,
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
        assert ui_waits == [("http://localhost:3000/agents", 2)]
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
            env="local",
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
        assert calls[1][2]["env"] == "local"
        assert calls[1][2]["status"] == "running"
        assert calls[1][2]["endpoint"] == "http://hermes:8642"
        metadata = calls[1][2]["metadata"]
        assert isinstance(metadata, dict)
        assert metadata["service_name"] == "hermes"
        assert metadata["environment"] == "local"

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
            env="local",
            status="running",
            api_url="http://api:8000",
        )

        assert calls[1][1] == (
            "http://api:8000/v1/workloads/external-hermes/deployments"
        )
        assert calls[1][2] is not None
        assert calls[1][2]["target"] == "external"
        assert calls[1][2]["env"] == "local"
        assert calls[1][2]["endpoint"] == "https://agents.example.com/hermes"

    def test_deployment_controller_claims_and_completes_apply(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        events: list[tuple[str, str, str, dict[str, object] | None]] = []
        heartbeats: list[tuple[str, str, str]] = []
        completions: list[
            tuple[
                str,
                str,
                str,
                str | None,
                str | None,
                dict[str, object] | None,
            ]
        ] = []
        commands: list[list[str]] = []
        operation = {
            "operation_id": "op-1",
            "action": "apply",
            "workload_name": "hermes",
            "target": "kubernetes",
            "env": "dev",
        }

        monkeypatch.setattr(
            cli_main,
            "_list_controller_operations",
            lambda *_args, **_kwargs: [operation],
        )
        monkeypatch.setattr(
            cli_main,
            "_claim_deployment_operation",
            lambda *_args, **_kwargs: operation,
        )
        monkeypatch.setattr(
            cli_main,
            "_load_workload_manifests",
            lambda _repo_root: [{"metadata": {"name": "hermes"}, "spec": {}}],
        )
        monkeypatch.setattr(
            cli_main,
            "_render_helm_values",
            lambda _manifests: {"workloads": [{"name": "hermes"}]},
        )
        monkeypatch.setattr(
            cli_main,
            "_environment_namespace",
            lambda _repo_root, _env: "moiraweave-dev",
        )
        monkeypatch.setattr(
            cli_main,
            "_heartbeat_deployment_operation",
            lambda api_url, operation_id, controller_id, **_kwargs: (
                heartbeats.append((api_url, operation_id, controller_id)) or {}
            ),
        )
        monkeypatch.setattr(
            cli_main,
            "_append_deployment_operation_event",
            lambda api_url, operation_id, event_type, message, data=None: events.append(
                (api_url, operation_id, event_type, data)
            ),
        )
        monkeypatch.setattr(
            cli_main,
            "_complete_deployment_operation",
            lambda api_url, operation_id, status, message, stdout_summary=None, stderr_summary=None, metadata=None: (
                completions.append(
                    (
                        api_url,
                        operation_id,
                        status,
                        stdout_summary,
                        stderr_summary,
                        metadata,
                    )
                )
                or {}
            ),
        )

        def fake_run(command: list[str], cwd: Path | None = None) -> tuple[int, str]:
            del cwd
            commands.append(command)
            return 0, "release upgraded"

        monkeypatch.setattr(cli_main, "_run_controller_command", fake_run)

        processed, failed = cli_main._run_deployment_controller_once(
            api_url="http://api:8000",
            target="kubernetes",
            env="dev",
            controller_id="controller-1",
            limit=5,
            repo_root=tmp_path,
            chart_ref="infra/helm/moiraweave",
            namespace=None,
            release="moiraweave",
        )

        assert (processed, failed) == (1, 0)
        assert heartbeats == [("http://api:8000", "op-1", "controller-1")]
        assert commands == [
            [
                "helm",
                "upgrade",
                "--install",
                "moiraweave",
                "infra/helm/moiraweave",
                "--namespace",
                "moiraweave-dev",
                "--create-namespace",
                "-f",
                str(tmp_path / ".moiraweave" / "deploy" / "values-workloads-dev.yaml"),
            ]
        ]
        assert events[0][2] == "controller.command"
        assert events[1][2] == "controller.output"
        assert completions == [
            (
                "http://api:8000",
                "op-1",
                "succeeded",
                "release upgraded",
                None,
                {"command": commands[0], "returncode": 0},
            )
        ]

    def test_deployment_controller_completes_failed_command(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        completions: list[tuple[str, str, str | None, dict[str, object] | None]] = []
        operation = {
            "operation_id": "op-2",
            "action": "logs",
            "workload_name": "hermes",
            "target": "kubernetes",
            "env": "dev",
        }

        monkeypatch.setattr(
            cli_main,
            "_environment_namespace",
            lambda _repo_root, _env: "moiraweave-dev",
        )
        monkeypatch.setattr(
            cli_main,
            "_heartbeat_deployment_operation",
            lambda *_args, **_kwargs: {},
        )
        monkeypatch.setattr(
            cli_main,
            "_append_deployment_operation_event",
            lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(
            cli_main,
            "_complete_deployment_operation",
            lambda _api_url, operation_id, status, message, stdout_summary=None, stderr_summary=None, metadata=None: (
                completions.append((status, operation_id, stderr_summary, metadata))
                or {}
            ),
        )
        monkeypatch.setattr(
            cli_main,
            "_run_controller_command",
            lambda _command, cwd=None: (1, "pods not found"),
        )

        ok = cli_main._run_deployment_controller_operation(
            operation,
            api_url="http://api:8000",
            controller_id="controller-1",
            repo_root=tmp_path,
            chart_ref="infra/helm/moiraweave",
            namespace=None,
            release="moiraweave",
        )

        assert ok is False
        assert completions[0][0] == "failed"
        assert completions[0][1] == "op-2"
        assert completions[0][2] == "pods not found"
        assert completions[0][3] is not None
        assert completions[0][3]["returncode"] == 1
        assert completions[0][3]["output"] == "pods not found"

    def test_deployment_controller_can_apply_from_api_manifest(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        operation = {
            "operation_id": "op-3",
            "action": "apply",
            "workload_name": "remote-agent",
            "target": "kubernetes",
            "env": "prod",
        }
        command_calls: list[list[str]] = []

        monkeypatch.setattr(cli_main, "_load_workload_manifests", lambda _root: [])
        monkeypatch.setattr(
            cli_main,
            "_fetch_workload_manifest",
            lambda _api_url, _name: {
                "apiVersion": "moiraweave.io/v1alpha1",
                "kind": "Workload",
                "metadata": {"name": "remote-agent"},
                "spec": {
                    "type": "agent-service",
                    "image": "ghcr.io/example/remote-agent:latest",
                    "ports": [{"name": "http", "port": 8080}],
                },
            },
        )
        monkeypatch.setattr(
            cli_main,
            "_heartbeat_deployment_operation",
            lambda *_args, **_kwargs: {},
        )
        monkeypatch.setattr(
            cli_main,
            "_append_deployment_operation_event",
            lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(
            cli_main,
            "_complete_deployment_operation",
            lambda *_args, **_kwargs: {},
        )

        def fake_run(command: list[str], cwd: Path | None = None) -> tuple[int, str]:
            del cwd
            command_calls.append(command)
            return 0, "release upgraded"

        monkeypatch.setattr(cli_main, "_run_controller_command", fake_run)

        ok = cli_main._run_deployment_controller_operation(
            operation,
            api_url="http://api:8000",
            controller_id="controller-1",
            repo_root=tmp_path,
            chart_ref="oci://ghcr.io/moiraweave-labs/charts/moiraweave",
            namespace="moiraweave-prod",
            release="mw-prod",
        )

        assert ok is True
        assert command_calls == [
            [
                "helm",
                "upgrade",
                "--install",
                "mw-prod",
                "oci://ghcr.io/moiraweave-labs/charts/moiraweave",
                "--namespace",
                "moiraweave-prod",
                "--create-namespace",
                "-f",
                str(tmp_path / ".moiraweave" / "deploy" / "values-workloads-prod.yaml"),
            ]
        ]
        values = yaml.safe_load(
            (
                tmp_path / ".moiraweave" / "deploy" / "values-workloads-prod.yaml"
            ).read_text(encoding="utf-8")
        )
        assert values["workloads"]["remote-agent"]["image"] == (
            "ghcr.io/example/remote-agent:latest"
        )
