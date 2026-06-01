"""Unit tests for internal CLI helpers in moira_cli.main."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import typer

MODULE_PATH = Path(__file__).resolve().parent.parent / "moira_cli" / "main.py"
SPEC = importlib.util.spec_from_file_location("moira_cli.main", MODULE_PATH)
if SPEC is None or SPEC.loader is None:  # pragma: no cover
    raise RuntimeError("Unable to load moira_cli.main module")
MAIN_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MAIN_MODULE)

_agent_template_manifest = MAIN_MODULE._agent_template_manifest
_missing_required_env = MAIN_MODULE._missing_required_env
_parse_json_input = MAIN_MODULE._parse_json_input
_render_local_workload_compose = MAIN_MODULE._render_local_workload_compose
_secret_inventory = MAIN_MODULE._secret_inventory


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
    assert manifest["spec"]["secrets"] == [
        "OPENAI_API_KEY",
        "HERMES_API_SERVER_KEY",
    ]
    assert manifest["spec"]["agent"]["adapter"] == "hermes"
    assert manifest["spec"]["agent"]["authTokenEnv"] == "HERMES_API_SERVER_KEY"


def test_agent_template_manifest_for_openclaw() -> None:
    """OpenClaw first-run template carries its adapter and token env."""
    manifest = _agent_template_manifest("openclaw")

    assert manifest["metadata"]["name"] == "openclaw"
    assert manifest["spec"]["ports"] == [{"name": "gateway", "port": 18789}]
    assert manifest["spec"]["secrets"] == ["OPENCLAW_GATEWAY_TOKEN"]
    assert manifest["spec"]["agent"]["adapter"] == "openclaw"
    assert manifest["spec"]["agent"]["authTokenEnv"] == "OPENCLAW_GATEWAY_TOKEN"


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
