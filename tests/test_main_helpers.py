"""Unit tests for internal CLI helpers in moira_cli.main."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import httpx
import pytest
import typer

MODULE_PATH = Path(__file__).resolve().parent.parent / "moira_cli" / "main.py"
SPEC = importlib.util.spec_from_file_location("moira_cli.main", MODULE_PATH)
if SPEC is None or SPEC.loader is None:  # pragma: no cover
    raise RuntimeError("Unable to load moira_cli.main module")
MAIN_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MAIN_MODULE)

_agent_template_manifest = MAIN_MODULE._agent_template_manifest
_doctor_action_guide = MAIN_MODULE._doctor_action_guide
_doctor_has_errors = MAIN_MODULE._doctor_has_errors
_doctor_report = MAIN_MODULE._doctor_report
_docker_image_available = MAIN_MODULE._docker_image_available
_missing_required_env = MAIN_MODULE._missing_required_env
_parse_json_input = MAIN_MODULE._parse_json_input
_ready_response_status = MAIN_MODULE._ready_response_status
_render_local_workload_compose = MAIN_MODULE._render_local_workload_compose
_kubernetes_secret_keys = MAIN_MODULE._kubernetes_secret_keys
_secret_inventory = MAIN_MODULE._secret_inventory
_wait_for_url_reachable = MAIN_MODULE._wait_for_url_reachable


def _write_workspace(tmp_path: Path) -> Path:
    """Create a minimal initialized workspace for helper tests."""
    (tmp_path / "moiraweave.yaml").write_text(
        """
name: test
registry: ghcr.io/test
runtime_version: 0.1.0
workloads_dir: .moiraweave/workloads
artifacts_dir: .moiraweave/artifacts
deploy_dir: .moiraweave/deploy
environments:
  local:
    context: docker-compose
    values: .env
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "API_GATEWAY_PORT=8000\nMOIRAWEAVE_UI_PORT=3000\n",
        encoding="utf-8",
    )
    (tmp_path / "docker-compose.yml").write_text(
        """
services:
  api-gateway:
    ports:
      - "${API_GATEWAY_PORT:-8000}:8000"
  ui:
    ports:
      - "${MOIRAWEAVE_UI_PORT:-3000}:80"
""".strip(),
        encoding="utf-8",
    )
    workload = tmp_path / ".moiraweave" / "workloads" / "demo-agent"
    workload.mkdir(parents=True)
    (tmp_path / ".moiraweave" / "deploy").mkdir(parents=True)
    (workload / "workload.yaml").write_text(
        MAIN_MODULE.yaml.safe_dump(_agent_template_manifest("demo-agent")),
        encoding="utf-8",
    )
    return tmp_path


def test_parse_json_input_inline_object() -> None:
    """Inline JSON objects are parsed as dictionaries."""
    parsed = _parse_json_input('{"name": "demo", "count": 2}')
    assert parsed == {"name": "demo", "count": 2}


def test_parse_json_input_raw_fallback() -> None:
    """Non-JSON inline input falls back to raw_input payload."""
    parsed = _parse_json_input("plain-text")
    assert parsed == {"raw_input": "plain-text"}


def test_parse_json_input_file_json(tmp_path: Path) -> None:
    """JSON files are loaded when the input starts with @."""
    payload = {"a": 1, "b": "two"}
    source = tmp_path / "payload.json"
    source.write_text(json.dumps(payload), encoding="utf-8")

    parsed = _parse_json_input(f"@{source}")
    assert parsed == payload


def test_parse_json_input_file_non_json(tmp_path: Path) -> None:
    """Non-JSON files passed with @ become input_path payloads."""
    source = tmp_path / "payload.txt"
    source.write_text("hello", encoding="utf-8")

    parsed = _parse_json_input(f"@{source}")
    assert parsed == {"input_path": str(source)}


def test_parse_json_input_file_missing_raises_exit(tmp_path: Path) -> None:
    """Missing input files terminate with a Typer exit."""
    source = tmp_path / "missing.json"
    with pytest.raises(typer.Exit):
        _parse_json_input(f"@{source}")


def test_agent_template_manifest_for_hermes() -> None:
    """Hermes first-run template matches the agent runtime contract."""
    manifest = _agent_template_manifest("hermes")

    assert manifest["metadata"]["name"] == "hermes"
    assert manifest["spec"]["image"] == "ghcr.io/nousresearch/hermes-agent:latest"
    assert manifest["spec"]["ports"] == [{"name": "http", "port": 8642}]
    assert manifest["spec"]["secrets"] == ["OPENAI_API_KEY"]
    assert manifest["spec"]["readinessProbe"]["httpGet"] == {
        "path": "/health",
        "port": "http",
    }
    assert manifest["spec"]["livenessProbe"]["httpGet"] == {
        "path": "/health",
        "port": "http",
    }
    assert manifest["spec"]["agent"]["adapter"] == "hermes"
    assert manifest["spec"]["agent"]["authTokenEnv"] == "HERMES_API_SERVER_KEY"
    assert manifest["spec"]["agent"]["toolOwnership"] == "runtime"
    requirements = manifest["spec"]["agent"]["runtimeRequirements"]
    assert requirements["filesystem"]["persistentWorkspace"] is True
    assert requirements["webSearch"]["enabled"] is True
    assert requirements["browser"]["mode"] == "runtime-managed"
    assert requirements["terminal"]["mode"] == "runtime-managed"


def test_agent_template_manifest_for_openclaw() -> None:
    """OpenClaw first-run template carries its adapter and token env."""
    manifest = _agent_template_manifest("openclaw")

    assert manifest["metadata"]["name"] == "openclaw"
    assert manifest["spec"]["ports"] == [{"name": "gateway", "port": 18789}]
    assert "secrets" not in manifest["spec"]
    assert manifest["spec"]["readinessProbe"]["tcpSocket"] == {"port": "gateway"}
    assert manifest["spec"]["livenessProbe"]["tcpSocket"] == {"port": "gateway"}
    assert manifest["spec"]["agent"]["adapter"] == "openclaw"
    assert manifest["spec"]["agent"]["authTokenEnv"] == "OPENCLAW_GATEWAY_TOKEN"
    assert manifest["spec"]["agent"]["toolOwnership"] == "runtime"
    assert (
        manifest["spec"]["agent"]["runtimeRequirements"]["messaging"]["enabled"] is True
    )


def test_agent_template_manifest_for_external_agent_requires_endpoint() -> None:
    """External agents need an endpoint before a manifest can be useful."""
    with pytest.raises(typer.Exit):
        _agent_template_manifest("external-agent")


def test_agent_template_manifest_for_generic_agent_requires_image() -> None:
    """Generic managed agents must not default to a placeholder image."""
    with pytest.raises(typer.Exit):
        _agent_template_manifest("generic-http-agent")


def test_missing_required_env_reads_dotenv(tmp_path: Path) -> None:
    """Secret preflight accepts variables from the process or local .env."""
    manifest = _agent_template_manifest("hermes")
    (tmp_path / ".env").write_text(
        "OPENAI_API_KEY=sk-test\nHERMES_API_SERVER_KEY=server-token\n",
        encoding="utf-8",
    )

    assert _missing_required_env([manifest], tmp_path) == []


def test_missing_required_env_reports_auth_token_env(tmp_path: Path) -> None:
    """Secret preflight includes adapter auth token variables."""
    manifest = _agent_template_manifest("openclaw")

    assert _missing_required_env([manifest], tmp_path) == ["OPENCLAW_GATEWAY_TOKEN"]


def test_secret_inventory_reports_names_without_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Secret inventory exposes only names, sources, and workload references."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("HERMES_API_SERVER_KEY", raising=False)
    manifest = _agent_template_manifest("hermes")
    (tmp_path / ".env").write_text(
        "OPENAI_API_KEY=sk-test\n",
        encoding="utf-8",
    )

    inventory = _secret_inventory([manifest], tmp_path)

    assert "sk-test" not in json.dumps(inventory)
    items = {item["name"]: item for item in inventory["secrets"]}
    assert items["OPENAI_API_KEY"]["present"] is True
    assert items["OPENAI_API_KEY"]["source"] == ".env"
    assert items["HERMES_API_SERVER_KEY"]["present"] is False
    assert items["HERMES_API_SERVER_KEY"]["source"] == "missing"


def test_secret_inventory_includes_runtime_requirement_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runtime-owned browser/MCP secrets are still visible to MoiraWeave."""
    monkeypatch.delenv("BROWSER_USE_API_KEY", raising=False)
    manifest = _agent_template_manifest("hermes")
    manifest["spec"]["agent"]["runtimeRequirements"]["browser"] = {
        "mode": "cloud",
        "requiredSecrets": ["BROWSER_USE_API_KEY"],
    }

    inventory = _secret_inventory([manifest], tmp_path)

    items = {item["name"]: item for item in inventory["secrets"]}
    assert items["BROWSER_USE_API_KEY"]["present"] is False
    assert (
        "hermes:spec.agent.runtimeRequirements.browser.requiredSecrets"
        in items["BROWSER_USE_API_KEY"]["references"]
    )


def test_secret_inventory_can_check_kubernetes_secret_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kubernetes target checks Secret keys instead of local env values."""
    monkeypatch.setenv("HERMES_API_SERVER_KEY", "local-only")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    manifest = _agent_template_manifest("hermes")

    inventory = _secret_inventory(
        [manifest],
        tmp_path,
        target="kubernetes",
        namespace="moiraweave-dev",
        kubernetes_secret="moiraweave-secrets",
        kubernetes_keys={"OPENAI_API_KEY"},
        kubernetes_status={"status": "available"},
    )

    items = {item["name"]: item for item in inventory["secrets"]}
    assert inventory["target"] == "kubernetes"
    assert items["OPENAI_API_KEY"]["present"] is True
    assert (
        items["OPENAI_API_KEY"]["source"]
        == "kubernetes:moiraweave-dev/moiraweave-secrets"
    )
    assert items["HERMES_API_SERVER_KEY"]["present"] is False
    assert items["HERMES_API_SERVER_KEY"]["source"] == "missing"
    assert items["HERMES_API_SERVER_KEY"]["local_source"] == "environment"


def test_kubernetes_secret_keys_exposes_names_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """kubectl Secret inspection never decodes or returns secret values."""

    class Result:
        returncode = 0
        stdout = json.dumps(
            {
                "data": {
                    "OPENAI_API_KEY": "c2stdmFsdWU=",
                    "HERMES_API_SERVER_KEY": "aGVybWVzLXRva2Vu",
                }
            }
        )
        stderr = ""

    def fake_run(command: list[str], **kwargs: object) -> Result:
        assert command == [
            "kubectl",
            "get",
            "secret",
            "moiraweave-secrets",
            "-n",
            "moiraweave-dev",
            "-o",
            "json",
        ]
        assert kwargs["capture_output"] is True
        return Result()

    monkeypatch.setattr(MAIN_MODULE.subprocess, "run", fake_run)

    keys, metadata = _kubernetes_secret_keys("moiraweave-dev", "moiraweave-secrets")

    assert keys == {"OPENAI_API_KEY", "HERMES_API_SERVER_KEY"}
    assert metadata["key_count"] == 2
    serialized = json.dumps((sorted(keys), metadata))
    assert "sk-value" not in serialized
    assert "hermes-token" not in serialized


def test_doctor_action_guide_turns_missing_secrets_into_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Doctor action guide mirrors the UI readiness guidance for real agents."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("HERMES_API_SERVER_KEY", raising=False)
    manifest = _agent_template_manifest("hermes")
    inventory = _secret_inventory([manifest], tmp_path)
    checks = [
        {
            "name": "secrets",
            "status": "error",
            "message": "2 required secret(s) missing.",
            "recommendation": "Run `moira secrets list` and add missing names.",
            "metadata": {"inventory": inventory},
        }
    ]

    guide = _doctor_action_guide(checks, target="local", env="local")

    secret_item = next(item for item in guide if item["title"] == "Set Missing Secrets")
    assert secret_item["state"] == "missing"
    assert "OPENAI_API_KEY" in secret_item["detail"]
    assert "HERMES_API_SERVER_KEY" in secret_item["detail"]
    assert "Values stay outside the CLI, UI, and API." in secret_item["detail"]
    assert secret_item["command"] == (
        "printf 'HERMES_API_SERVER_KEY=...\\nOPENAI_API_KEY=...\\n' >> .env"
    )
    assert any(item["title"] == "Sync Deployment Record" for item in guide)


def test_doctor_report_exposes_action_guide_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Machine-readable doctor output includes actionable onboarding guidance."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("HERMES_API_SERVER_KEY", raising=False)
    workspace = _write_workspace(tmp_path)
    hermes_root = workspace / ".moiraweave" / "workloads" / "hermes"
    hermes_root.mkdir(parents=True)
    (hermes_root / "workload.yaml").write_text(
        MAIN_MODULE.yaml.safe_dump(_agent_template_manifest("hermes")),
        encoding="utf-8",
    )
    monkeypatch.setattr(MAIN_MODULE.shutil, "which", lambda _name: None)
    monkeypatch.setattr(MAIN_MODULE, "_api_ready", lambda _url: (False, "offline"))
    monkeypatch.setattr(
        MAIN_MODULE,
        "_url_reachable",
        lambda _url: (False, "offline"),
    )
    monkeypatch.setattr(MAIN_MODULE, "_is_local_port_open", lambda _port: False)

    report = _doctor_report(
        target="local",
        api_url="http://localhost:8000",
        repo_root=workspace,
    )

    assert "action_guide" in report
    assert "sk-" not in json.dumps(report)
    assert any(
        item["title"] == "Set Missing Secrets" and "OPENAI_API_KEY" in item["detail"]
        for item in report["action_guide"]
    )


def test_render_compose_injects_agent_auth_token_env(tmp_path: Path) -> None:
    """Local Compose exposes auth token envs referenced only by the adapter."""
    manifest = _agent_template_manifest(
        "generic-http-agent",
        image="ghcr.io/example/custom-agent:1.0.0",
    )
    manifest["spec"]["agent"]["authTokenEnv"] = "AGENT_TOKEN"

    compose = _render_local_workload_compose([manifest], tmp_path)

    env = compose["services"]["generic-agent"]["environment"]
    assert env["AGENT_TOKEN"] == "${AGENT_TOKEN:?set AGENT_TOKEN}"


def test_render_compose_does_not_publish_demo_agent_host_port(
    tmp_path: Path,
) -> None:
    """The first-run demo agent must not collide with the API gateway on 8000."""
    manifest = _agent_template_manifest("demo-agent")

    compose = _render_local_workload_compose([manifest], tmp_path)

    assert "ports" not in compose["services"]["demo-agent"]


def test_render_compose_supports_multiple_real_agent_templates(
    tmp_path: Path,
) -> None:
    """Hermes and OpenClaw can run together without port or mount collisions."""
    hermes = _agent_template_manifest("hermes")
    openclaw = _agent_template_manifest("openclaw")

    compose = _render_local_workload_compose([hermes, openclaw], tmp_path)

    services = compose["services"]
    assert set(services) == {"hermes", "openclaw"}
    assert services["hermes"]["ports"] == ["8642:8642"]
    assert services["openclaw"]["ports"] == ["18789:18789"]
    assert services["hermes"]["environment"]["OPENAI_API_KEY"] == (
        "${OPENAI_API_KEY:?set OPENAI_API_KEY}"
    )
    assert services["hermes"]["environment"]["HERMES_API_SERVER_KEY"] == (
        "${HERMES_API_SERVER_KEY:?set HERMES_API_SERVER_KEY}"
    )
    assert services["openclaw"]["environment"]["OPENCLAW_GATEWAY_TOKEN"] == (
        "${OPENCLAW_GATEWAY_TOKEN:?set OPENCLAW_GATEWAY_TOKEN}"
    )
    assert services["hermes"]["volumes"] == [
        f"{tmp_path / '.moiraweave' / 'artifacts' / 'hermes'}:/workspace"
    ]
    assert services["openclaw"]["volumes"] == [
        f"{tmp_path / '.moiraweave' / 'artifacts' / 'openclaw'}:/workspace"
    ]
    assert compose["networks"] == {"moiraweave-net": {"name": "moiraweave-net"}}


def test_doctor_report_blocks_missing_docker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Doctor reports missing Docker as a blocking onboarding error."""
    workspace = _write_workspace(tmp_path)
    monkeypatch.setattr(MAIN_MODULE.shutil, "which", lambda _name: None)
    monkeypatch.setattr(MAIN_MODULE, "_api_ready", lambda _url: (False, "offline"))
    monkeypatch.setattr(
        MAIN_MODULE,
        "_url_reachable",
        lambda _url: (False, "offline"),
    )
    monkeypatch.setattr(MAIN_MODULE, "_is_local_port_open", lambda _port: False)

    report = _doctor_report(
        target="local",
        api_url="http://localhost:8000",
        repo_root=workspace,
    )

    docker_check = next(
        check for check in report["checks"] if check["name"] == "docker-cli"
    )
    assert docker_check["status"] == "error"
    assert _doctor_has_errors(report) is True


def test_doctor_report_detects_duplicate_compose_ports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Doctor catches generated Compose files that publish the same host port."""
    workspace = _write_workspace(tmp_path)
    (workspace / ".moiraweave" / "deploy" / "docker-compose.workloads.yml").write_text(
        """
services:
  agent:
    ports:
      - "8000:8000"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(MAIN_MODULE.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(
        MAIN_MODULE, "_probe_command", lambda *_args, **_kwargs: (True, "ok")
    )
    monkeypatch.setattr(MAIN_MODULE, "_api_ready", lambda _url: (False, "offline"))
    monkeypatch.setattr(
        MAIN_MODULE,
        "_url_reachable",
        lambda _url: (False, "offline"),
    )
    monkeypatch.setattr(MAIN_MODULE, "_is_local_port_open", lambda _port: False)

    report = _doctor_report(
        target="local",
        api_url="http://localhost:8000",
        repo_root=workspace,
    )

    port_check = next(
        check for check in report["checks"] if check["name"] == "compose-ports"
    )
    assert port_check["status"] == "error"
    assert port_check["metadata"]["duplicates"] == [8000]


def test_doctor_report_warns_on_transient_image_registry_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Transient registry failures should not stop a local first run."""
    workspace = _write_workspace(tmp_path)
    (workspace / "docker-compose.yml").write_text(
        """
services:
  api-gateway:
    image: ghcr.io/test/api-gateway:latest
    ports:
      - "${API_GATEWAY_PORT:-8000}:8000"
""".strip(),
        encoding="utf-8",
    )

    def fake_probe(command: list[str], **_kwargs: object) -> tuple[bool, str]:
        if command[:3] == ["docker", "image", "inspect"]:
            return False, "not present locally"
        if command[:3] == ["docker", "manifest", "inspect"]:
            return False, "timed out after 10s"
        return True, "ok"

    monkeypatch.setattr(MAIN_MODULE.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(MAIN_MODULE, "_probe_command", fake_probe)
    monkeypatch.setattr(MAIN_MODULE.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(MAIN_MODULE, "_api_ready", lambda _url: (False, "offline"))
    monkeypatch.setattr(
        MAIN_MODULE,
        "_url_reachable",
        lambda _url: (False, "offline"),
    )
    monkeypatch.setattr(MAIN_MODULE, "_is_local_port_open", lambda _port: False)

    report = _doctor_report(
        target="local",
        api_url="http://localhost:8000",
        repo_root=workspace,
    )

    image_check = next(
        check for check in report["checks"] if check["name"] == "container-images"
    )
    assert image_check["status"] == "warning"
    assert image_check["metadata"]["transient"] == {
        "ghcr.io/test/api-gateway:latest": "timed out after 10s"
    }
    assert image_check["metadata"]["unavailable"] == {}
    assert _doctor_has_errors(report) is False


def test_doctor_report_blocks_fatal_image_registry_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Private or missing images remain blocking onboarding errors."""
    workspace = _write_workspace(tmp_path)
    (workspace / "docker-compose.yml").write_text(
        """
services:
  api-gateway:
    image: ghcr.io/test/private-api-gateway:latest
    ports:
      - "${API_GATEWAY_PORT:-8000}:8000"
""".strip(),
        encoding="utf-8",
    )

    def fake_probe(command: list[str], **_kwargs: object) -> tuple[bool, str]:
        if command[:3] == ["docker", "image", "inspect"]:
            return False, "not present locally"
        if command[:3] == ["docker", "manifest", "inspect"]:
            return False, "denied: requested access to the resource is denied"
        return True, "ok"

    monkeypatch.setattr(MAIN_MODULE.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(MAIN_MODULE, "_probe_command", fake_probe)
    monkeypatch.setattr(MAIN_MODULE, "_api_ready", lambda _url: (False, "offline"))
    monkeypatch.setattr(
        MAIN_MODULE,
        "_url_reachable",
        lambda _url: (False, "offline"),
    )
    monkeypatch.setattr(MAIN_MODULE, "_is_local_port_open", lambda _port: False)

    report = _doctor_report(
        target="local",
        api_url="http://localhost:8000",
        repo_root=workspace,
    )

    image_check = next(
        check for check in report["checks"] if check["name"] == "container-images"
    )
    assert image_check["status"] == "error"
    assert image_check["metadata"]["unavailable"] == {
        "ghcr.io/test/private-api-gateway:latest": (
            "denied: requested access to the resource is denied"
        )
    }
    assert image_check["metadata"]["transient"] == {}
    assert _doctor_has_errors(report) is True


def test_docker_image_available_retries_remote_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Transient registry failures should not block first-run onboarding."""
    remote_attempts = 0

    def fake_probe(command: list[str], **_kwargs: object) -> tuple[bool, str]:
        nonlocal remote_attempts
        if command[:3] == ["docker", "image", "inspect"]:
            return False, "not local"
        remote_attempts += 1
        if remote_attempts == 1:
            return False, "temporary registry error"
        return True, "remote ok"

    monkeypatch.setattr(MAIN_MODULE, "_probe_command", fake_probe)
    monkeypatch.setattr(MAIN_MODULE.time, "sleep", lambda _seconds: None)

    available, message = _docker_image_available("example/image:latest", attempts=2)

    assert available is True
    assert "available remotely" in message
    assert remote_attempts == 2


def test_wait_for_url_reachable_retries_until_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def fake_url_reachable(_url: str) -> tuple[bool, str]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return False, "connection refused"
        return True, "HTTP 200"

    monkeypatch.setattr(MAIN_MODULE, "_url_reachable", fake_url_reachable)
    monkeypatch.setattr(MAIN_MODULE.time, "sleep", lambda _seconds: None)

    reachable, message = _wait_for_url_reachable("http://localhost:3000", 5)

    assert reachable is True
    assert message == "HTTP 200"
    assert attempts == 2


def test_ready_response_status_requires_ready_body() -> None:
    response = httpx.Response(
        200,
        json={
            "status": "not_ready",
            "checks": {
                "redis": {"status": "ok"},
                "run_queue": {"status": "degraded"},
            },
        },
    )

    ready, message = _ready_response_status(response)

    assert ready is False
    assert "not_ready" in message
    assert "run_queue=degraded" in message


def test_ready_response_status_accepts_ready_body() -> None:
    response = httpx.Response(200, json={"status": "ready", "checks": {}})

    ready, message = _ready_response_status(response)

    assert ready is True
    assert message == "ready endpoint status ready"


def test_agent_chat_creates_session_and_sends_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A one-shot chat creates a session before sending the first message."""
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def fake_request_json(
        method: str,
        url: str,
        payload: dict[str, object] | None = None,
        token: str | None = None,
    ) -> dict[str, object]:
        del token
        calls.append((method, url, payload))
        if url.endswith("/v1/agents/demo-agent/sessions"):
            return {"session_id": "session-1"}
        if url.endswith("/v1/agents/demo-agent/sessions/session-1/messages"):
            return {"run_id": "run-1", "session_id": "session-1"}
        raise AssertionError(f"unexpected request: {method} {url}")

    monkeypatch.setattr(MAIN_MODULE, "_request_json", fake_request_json)

    MAIN_MODULE.agent_chat(
        "demo-agent",
        "hello",
        session_id=None,
        metadata='{"source": "test"}',
        context='{"channel": "cli"}',
        watch=False,
        api_url="http://api.test",
    )

    assert calls == [
        (
            "POST",
            "http://api.test/v1/agents/demo-agent/sessions",
            {"metadata": {"source": "test"}},
        ),
        (
            "POST",
            "http://api.test/v1/agents/demo-agent/sessions/session-1/messages",
            {"message": "hello", "context": {"channel": "cli"}},
        ),
    ]


def test_agent_chat_uses_existing_session_and_can_watch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Passing --session-id avoids session creation and can watch the run."""
    watched: list[tuple[str, str, int]] = []
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def fake_request_json(
        method: str,
        url: str,
        payload: dict[str, object] | None = None,
        token: str | None = None,
    ) -> dict[str, object]:
        del token
        calls.append((method, url, payload))
        return {"run_id": "run-2", "session_id": "existing-session"}

    def fake_watch_run(run_id: str, api_url: str, timeout: int) -> None:
        watched.append((run_id, api_url, timeout))

    monkeypatch.setattr(MAIN_MODULE, "_request_json", fake_request_json)
    monkeypatch.setattr(MAIN_MODULE, "_watch_run", fake_watch_run)

    MAIN_MODULE.agent_chat(
        "demo-agent",
        "hello again",
        session_id="existing-session",
        metadata="{}",
        context="{}",
        watch=True,
        api_url="http://api.test",
    )

    assert calls == [
        (
            "POST",
            "http://api.test/v1/agents/demo-agent/sessions/existing-session/messages",
            {"message": "hello again", "context": {}},
        )
    ]
    assert watched == [("run-2", "http://api.test", 3600)]


def test_request_json_refreshes_local_dev_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local API calls transparently refresh and persist a dev token after 401."""
    _write_workspace(tmp_path)
    requests: list[dict[str, str]] = []

    class FakeResponse:
        def __init__(self, status_code: int, payload: dict[str, object]) -> None:
            self.status_code = status_code
            self._payload = payload

        def raise_for_status(self) -> None:
            if self.status_code >= 400:  # pragma: no cover - retry should avoid it
                raise AssertionError("unexpected unrecovered response")

        def json(self) -> dict[str, object]:
            return self._payload

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            del timeout

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def request(
            self,
            method: str,
            url: str,
            json: dict[str, object] | None = None,
            headers: dict[str, str] | None = None,
        ) -> FakeResponse:
            del method, url, json
            requests.append(headers or {})
            if len(requests) == 1:
                return FakeResponse(401, {})
            return FakeResponse(200, {"ok": True})

    monkeypatch.delenv("MOIRA_TOKEN", raising=False)
    monkeypatch.setattr(MAIN_MODULE, "find_repo_root", lambda: tmp_path)
    monkeypatch.setattr(MAIN_MODULE, "_dev_login_token", lambda _api_url: "fresh-token")
    monkeypatch.setattr(MAIN_MODULE.httpx, "Client", FakeClient)

    response = MAIN_MODULE._request_json("GET", "http://localhost:8100/v1/runs")

    assert response == {"ok": True}
    assert requests == [{}, {"Authorization": "Bearer fresh-token"}]
    stored = json.loads((tmp_path / ".moiraweave" / "auth.json").read_text())
    assert stored["access_token"] == "fresh-token"
    assert ".moiraweave/auth.json" in (tmp_path / ".gitignore").read_text()
