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

_bump_semver = MAIN_MODULE._bump_semver
_agent_template_manifest = MAIN_MODULE._agent_template_manifest
_catalog_raw_url_from_uri = MAIN_MODULE._catalog_raw_url_from_uri
_missing_required_env = MAIN_MODULE._missing_required_env
_parse_json_input = MAIN_MODULE._parse_json_input
_render_local_workload_compose = MAIN_MODULE._render_local_workload_compose
_semver_key = MAIN_MODULE._semver_key


def test_bump_semver_patch() -> None:
    """It bumps patch versions correctly."""
    assert _bump_semver("1.2.3", "patch") == "1.2.4"


def test_bump_semver_minor() -> None:
    """It bumps minor versions and resets patch."""
    assert _bump_semver("1.2.3", "minor") == "1.3.0"


def test_bump_semver_major() -> None:
    """It bumps major versions and resets minor and patch."""
    assert _bump_semver("1.2.3", "major") == "2.0.0"


def test_bump_semver_invalid_raises_exit() -> None:
    """Invalid semantic versions terminate with a Typer exit."""
    with pytest.raises(typer.Exit):
        _bump_semver("1.2", "patch")


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


def test_semver_key_valid_and_invalid() -> None:
    """Version keys are sortable and invalid values degrade to zeros."""
    assert _semver_key("2.4.6") == (2, 4, 6)
    assert _semver_key("x.y.z") == (0, 0, 0)


def test_catalog_raw_url_passthrough_for_http_yaml() -> None:
    """Direct HTTP catalog files are returned unchanged."""
    uri = "https://example.com/catalog.yaml"
    assert _catalog_raw_url_from_uri(uri) == uri


def test_catalog_raw_url_for_github_repo() -> None:
    """GitHub repository URLs are converted to raw catalog URLs."""
    uri = "https://github.com/example/catalog"
    expected = "https://raw.githubusercontent.com/example/catalog/main/catalog.yaml"
    assert _catalog_raw_url_from_uri(uri) == expected


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
