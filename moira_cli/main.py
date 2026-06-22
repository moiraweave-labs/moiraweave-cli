"""Typer entrypoint for the MoiraWeave CLI."""

from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import time
from collections import Counter
from threading import Event, Thread
from typing import Any, NoReturn
from urllib.parse import quote, urlencode, urlparse

import httpx
import typer
import yaml
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.syntax import Syntax

from moira_cli.commands import find_repo_root
from moira_cli.commands import flow as flow_command_module
from moira_cli.commands.project import ProjectInitCommand
from moira_cli.io import (
    load_moiraweave_config,
)
from moira_cli.ui import get_ui

DEFAULT_API_URL = "http://localhost:8000"
_TERMINAL_RUN_STATES = {"succeeded", "failed", "canceled", "lost"}
_DOCTOR_STATUS_ORDER = {"ok": 0, "warning": 1, "error": 2}
_LOCAL_PLATFORM_PORTS = {
    "api-gateway": ("API_GATEWAY_PORT", 8000),
    "ui": ("MOIRAWEAVE_UI_PORT", 3000),
    "postgres": ("POSTGRES_PORT", 5432),
    "redis": ("REDIS_PORT", 6379),
    "qdrant": ("QDRANT_PORT", 6333),
}
_FATAL_IMAGE_ERROR_MARKERS = (
    "authentication required",
    "denied",
    "insufficient_scope",
    "invalid reference format",
    "manifest unknown",
    "name unknown",
    "no such manifest",
    "not found",
    "pull access denied",
    "repository does not exist",
    "requested access to the resource is denied",
    "unauthorized",
)
_TRANSIENT_IMAGE_ERROR_MARKERS = (
    "429",
    "500",
    "502",
    "503",
    "504",
    "connection refused",
    "connection reset",
    "context deadline exceeded",
    "dial tcp",
    "i/o timeout",
    "network is unreachable",
    "service unavailable",
    "temporary",
    "timed out",
    "timeout",
    "tls handshake timeout",
    "too many requests",
)

console = Console()
ui = get_ui()
app = typer.Typer(
    help="MoiraWeave CLI — deploy and operate AI workloads",
    no_args_is_help=True,
)
workload_app = typer.Typer(help="Manage workloads")
run_app = typer.Typer(help="Submit, watch, and cancel runs")
run_dead_letter_app = typer.Typer(help="Inspect failed run dispatch messages")
agent_app = typer.Typer(help="Manage agent sessions")
agent_session_app = typer.Typer(help="Create and message agent sessions")
deploy_app = typer.Typer(help="Generate or apply deployment assets")
deploy_controller_app = typer.Typer(help="Run deployment operation controllers")
demo_app = typer.Typer(help="Create runnable demo workloads")
secrets_app = typer.Typer(help="Inspect required workload secrets")
security_app = typer.Typer(help="Manage users, teams, and API keys")
security_user_app = typer.Typer(help="Manage users")
security_team_app = typer.Typer(help="Manage teams")
security_api_key_app = typer.Typer(help="Manage API keys")
env_app = typer.Typer(help="Inspect deployment environments")
ops_app = typer.Typer(help="Inspect operational alerts")


class DockerImageAvailability:
    def __init__(self, image: str, status: str, message: str) -> None:
        self.image = image
        self.status = status
        self.message = message

    @property
    def available(self) -> bool:
        return self.status == "ok"


# Register 'flow' command
app.add_typer(
    flow_command_module.app,
    name="flow",
    help="Show workload manifests as a visual tree",
)
app.add_typer(workload_app, name="workload")
app.add_typer(run_app, name="run")
app.add_typer(agent_app, name="agent")
app.add_typer(deploy_app, name="deploy")
app.add_typer(demo_app, name="demo")
app.add_typer(secrets_app, name="secrets")
app.add_typer(security_app, name="security")
app.add_typer(env_app, name="env")
app.add_typer(ops_app, name="ops")
agent_app.add_typer(agent_session_app, name="session")
security_app.add_typer(security_user_app, name="user")
security_app.add_typer(security_team_app, name="team")
security_app.add_typer(security_api_key_app, name="api-key")
deploy_app.add_typer(deploy_controller_app, name="controller")
run_app.add_typer(run_dead_letter_app, name="dead-letter")


def _repo_root() -> pathlib.Path:
    """Resolve the current repository root.

    :returns: Nearest initialized MoiraWeave workspace.
    """
    try:
        return find_repo_root()
    except FileNotFoundError as exc:
        console.print(f"[red]{str(exc)}[/red]")
        raise typer.Exit(code=1) from None


def _exit_with_error(message: str, hint: str | None = None, code: int = 1) -> NoReturn:
    """Print an error and terminate.

    :param message: Human-readable error message.
    :param hint: Optional suggestion.
    :param code: Process exit code.
    """
    ui.error(message, hint=hint)
    raise typer.Exit(code=code)


def _run_command(command: list[str], cwd: pathlib.Path | None = None) -> str:
    """Run a shell command and return stdout.

    :param command: Command tokens.
    :param cwd: Optional working directory.
    :returns: Captured stdout text.
    :raises typer.Exit: If command fails.
    """
    proc = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or "unknown error"
        _exit_with_error(f"Command failed: {' '.join(command)}\n{stderr}")
    return proc.stdout.strip()


def _run_controller_command(
    command: list[str], cwd: pathlib.Path | None = None
) -> tuple[int, str]:
    """Run a controller command without raising on failure."""
    try:
        proc = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        return 127, str(exc)
    output = "\n".join(
        part for part in (proc.stdout.strip(), proc.stderr.strip()) if part
    )
    return proc.returncode, output


def _probe_command(
    command: list[str],
    cwd: pathlib.Path | None = None,
    *,
    timeout: float = 5.0,
) -> tuple[bool, str]:
    """Run a command for diagnostics without exiting the process."""
    try:
        proc = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError:
        return False, "command not found"
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout:g}s"
    output = proc.stdout.strip() or proc.stderr.strip()
    return proc.returncode == 0, output


def _load_yaml_file(path: pathlib.Path) -> dict[str, Any]:
    """Load YAML as a dictionary.

    :param path: YAML file path.
    :returns: Parsed dictionary.
    :raises typer.Exit: If parsing fails.
    """
    try:
        return dict(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    except Exception as exc:  # pragma: no cover
        _exit_with_error(f"Invalid YAML in {path}: {exc}")


def _read_json_file(path: pathlib.Path) -> dict[str, Any]:
    """Read JSON file as dictionary.

    :param path: JSON file path.
    :returns: Parsed object.
    """
    try:
        return dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception as exc:  # pragma: no cover
        _exit_with_error(f"Invalid JSON in {path}: {exc}")


def _parse_key_value_options(values: list[str], *, option: str) -> dict[str, str]:
    """Parse repeated KEY=VALUE CLI options."""
    parsed: dict[str, str] = {}
    for raw in values:
        key, separator, value = raw.partition("=")
        key = key.strip()
        if not separator or not key:
            _exit_with_error(f"Invalid {option} value: {raw}", hint="Use KEY=VALUE")
        parsed[key] = value
    return parsed


def _request_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    *,
    retry_local_login: bool = True,
) -> dict[str, Any]:
    """Issue an HTTP request and parse JSON response.

    Reads ``MOIRA_TOKEN`` from the environment and sends it as a Bearer
    Authorization header when present.

    :param method: HTTP method.
    :param url: Request URL.
    :param payload: Optional JSON body.
    :returns: Parsed JSON dictionary.
    :raises typer.Exit: If request fails.
    """
    repo_root = _maybe_repo_root()
    headers = _request_headers(repo_root)
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.request(method, url, json=payload, headers=headers)
            if (
                response.status_code == 401
                and retry_local_login
                and "MOIRA_TOKEN" not in os.environ
                and repo_root is not None
                and _is_local_api_url(url)
            ):
                parsed = urlparse(url)
                api_url = f"{parsed.scheme}://{parsed.netloc}"
                token = _dev_login_token(api_url)
                if token:
                    _store_cli_token(repo_root, api_url, token)
                    response = client.request(
                        method,
                        url,
                        json=payload,
                        headers={"Authorization": f"Bearer {token}"},
                    )
            response.raise_for_status()
            body = response.json()
            return body if isinstance(body, dict) else {"data": body}
    except Exception as exc:
        _exit_with_error(f"HTTP request failed for {url}: {exc}")


def _deployment_operation_url(api_url: str, operation_id: str, suffix: str = "") -> str:
    return f"{api_url.rstrip('/')}/v1/deployment-operations/{operation_id}{suffix}"


def _list_controller_operations(
    api_url: str,
    *,
    target: str,
    env: str,
    limit: int,
) -> list[dict[str, Any]]:
    query = urlencode(
        {
            "scope": "all",
            "status": "queued",
            "target": target,
            "env": env,
            "limit": str(limit),
        }
    )
    response = _request_json(
        "GET", f"{api_url.rstrip('/')}/v1/deployment-operations?{query}"
    )
    data = response.get("data", [])
    return [dict(item) for item in data] if isinstance(data, list) else []


def _claim_deployment_operation(
    api_url: str,
    operation_id: str,
    *,
    controller_id: str,
    lease_seconds: int = 300,
) -> dict[str, Any]:
    return _request_json(
        "POST",
        _deployment_operation_url(api_url, operation_id, "/claim"),
        {
            "controller_id": controller_id,
            "lease_seconds": lease_seconds,
            "metadata": {"client": "moira-cli", "mode": "deployment-controller"},
        },
    )


def _heartbeat_deployment_operation(
    api_url: str,
    operation_id: str,
    *,
    controller_id: str,
    lease_seconds: int = 300,
) -> dict[str, Any]:
    return _request_json(
        "POST",
        _deployment_operation_url(api_url, operation_id, "/heartbeat"),
        {
            "controller_id": controller_id,
            "lease_seconds": lease_seconds,
            "metadata": {"client": "moira-cli", "mode": "deployment-controller"},
        },
    )


def _run_controller_command_with_heartbeat(
    command: list[str],
    *,
    cwd: pathlib.Path,
    api_url: str,
    operation_id: str,
    controller_id: str,
    lease_seconds: int = 300,
    interval_seconds: float = 60.0,
) -> tuple[int, str]:
    stop = Event()

    def beat() -> None:
        try:
            _heartbeat_deployment_operation(
                api_url,
                operation_id,
                controller_id=controller_id,
                lease_seconds=lease_seconds,
            )
        except Exception:
            # The command result remains the source of truth. The API will surface
            # lease expiry if every heartbeat fails.
            return

    def loop() -> None:
        while not stop.wait(interval_seconds):
            beat()

    thread = Thread(target=loop, name="moira-deploy-controller-heartbeat", daemon=True)
    thread.start()
    try:
        return _run_controller_command(command, cwd=cwd)
    finally:
        stop.set()
        thread.join(timeout=1.0)


def _append_deployment_operation_event(
    api_url: str,
    operation_id: str,
    event_type: str,
    message: str,
    *,
    data: dict[str, Any] | None = None,
) -> None:
    _request_json(
        "POST",
        _deployment_operation_url(api_url, operation_id, "/events"),
        {"type": event_type, "message": message, "data": data or {}},
    )


def _complete_deployment_operation(
    api_url: str,
    operation_id: str,
    *,
    status: str,
    message: str,
    stdout_summary: str | None = None,
    stderr_summary: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": status,
        "message": message,
        "metadata": metadata or {},
    }
    if stdout_summary is not None:
        payload["stdout_summary"] = stdout_summary
    if stderr_summary is not None:
        payload["stderr_summary"] = stderr_summary
    return _request_json(
        "POST",
        _deployment_operation_url(api_url, operation_id, "/complete"),
        payload,
    )


def _parse_json_input(input_value: str) -> dict[str, Any]:
    """Parse CLI `--input` payload.

    Supports inline JSON or `@path.json`.

    :param input_value: User-provided input.
    :returns: Parsed JSON object.
    """
    if input_value.startswith("@"):
        source = pathlib.Path(input_value[1:])
        if not source.exists():
            _exit_with_error(f"Input file not found: {source}")
        if source.suffix.lower() == ".json":
            return _read_json_file(source)
        return {"input_path": str(source)}

    try:
        parsed = json.loads(input_value)
        if isinstance(parsed, dict):
            return parsed
        _exit_with_error("Input JSON must be an object.")
    except json.JSONDecodeError:
        return {"raw_input": input_value}


def _workloads_root(repo_root: pathlib.Path) -> pathlib.Path:
    try:
        config = load_moiraweave_config(repo_root)
        return repo_root / config.workloads_dir
    except Exception:
        return repo_root / ".moiraweave" / "workloads"


def _artifacts_root(repo_root: pathlib.Path) -> pathlib.Path:
    try:
        config = load_moiraweave_config(repo_root)
        return repo_root / config.artifacts_dir
    except Exception:
        return repo_root / ".moiraweave" / "artifacts"


def _deploy_root(repo_root: pathlib.Path) -> pathlib.Path:
    try:
        config = load_moiraweave_config(repo_root)
        return repo_root / config.deploy_dir
    except Exception:
        return repo_root / ".moiraweave" / "deploy"


def _environment_namespace(repo_root: pathlib.Path, env: str) -> str:
    try:
        config = load_moiraweave_config(repo_root)
        target = config.environments.get(env)
        return target.namespace if target and target.namespace else "moiraweave"
    except Exception:
        return "moiraweave"


def _auth_token_path(repo_root: pathlib.Path) -> pathlib.Path:
    return repo_root / ".moiraweave" / "auth.json"


def _maybe_repo_root() -> pathlib.Path | None:
    try:
        return find_repo_root()
    except FileNotFoundError:
        return None


def _is_local_api_url(api_url: str) -> bool:
    host = urlparse(api_url).hostname
    return host in {None, "", "localhost", "127.0.0.1", "::1"}


def _stored_cli_token(repo_root: pathlib.Path | None) -> str | None:
    if repo_root is None:
        return None
    path = _auth_token_path(repo_root)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    token = payload.get("access_token") if isinstance(payload, dict) else None
    return str(token) if token else None


def _store_cli_token(repo_root: pathlib.Path, api_url: str, token: str) -> None:
    _ensure_gitignore_entries(repo_root, [".moiraweave/auth.json"])
    path = _auth_token_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "api_url": api_url.rstrip("/"),
                "access_token": token,
                "source": "dev-login",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _ensure_gitignore_entries(repo_root: pathlib.Path, entries: list[str]) -> None:
    path = repo_root / ".gitignore"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    missing = [entry for entry in entries if entry not in lines]
    if missing:
        path.write_text("\n".join([*lines, *missing]).strip() + "\n", encoding="utf-8")


def _request_headers(repo_root: pathlib.Path | None) -> dict[str, str]:
    token = os.environ.get("MOIRA_TOKEN") or _stored_cli_token(repo_root)
    return {"Authorization": f"Bearer {token}"} if token else {}


def _workload_file(repo_root: pathlib.Path, name: str) -> pathlib.Path:
    return _workloads_root(repo_root) / name / "workload.yaml"


def _load_workload_manifests(repo_root: pathlib.Path) -> list[dict[str, Any]]:
    root = _workloads_root(repo_root)
    manifests: list[dict[str, Any]] = []
    for path in sorted(root.glob("*/workload.yaml")):
        manifest = _load_yaml_file(path)
        manifest["_path"] = str(path)
        manifests.append(manifest)
    return manifests


def _workload_name(manifest: dict[str, Any]) -> str:
    metadata = manifest.get("metadata", {})
    if isinstance(metadata, dict):
        return str(metadata.get("name", ""))
    return ""


def _workload_type(manifest: dict[str, Any]) -> str:
    spec = manifest.get("spec", {})
    if isinstance(spec, dict):
        return str(spec.get("type", ""))
    return ""


def _first_agent_workload_name(manifests: list[dict[str, Any]]) -> str:
    for manifest in manifests:
        if _workload_type(manifest) == "agent-service" and _workload_name(manifest):
            return _workload_name(manifest)
    return "demo-agent"


def _write_manifest(path: pathlib.Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")


_DEMO_AGENT_SCRIPT = r"""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def _send(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/health"):
            self._send({"status": "healthy", "ok": True})
            return
        if self.path.startswith("/artifacts"):
            self._send({"artifacts": []})
            return
        self._send({"error": "not found"}, status=404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        payload = json.loads(raw.decode("utf-8") or "{}")
        text = payload.get("message") or payload.get("prompt") or "hello"
        self._send(
            {
                "accepted": True,
                "status": "succeeded",
                "response": f"Demo agent received: {text}",
                "artifacts": [
                    {
                        "id": f"{payload.get('session_id', 'demo')}-reply",
                        "name": "demo-reply.json",
                        "uri": "memory://demo-reply.json",
                        "content_type": "application/json",
                        "metadata": {"source": "demo-agent"},
                    }
                ],
            }
        )


HTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
""".strip()


def _demo_agent_manifest(name: str) -> dict[str, Any]:
    return {
        "apiVersion": "moiraweave.io/v1alpha1",
        "kind": "Workload",
        "metadata": {
            "name": name,
            "labels": {"moiraweave.io/template": "demo-agent"},
        },
        "spec": {
            "type": "agent-service",
            "image": "python:3.13-slim",
            "deployment": {
                "mode": "managed",
                "targets": ["local", "kubernetes"],
                "serviceName": name,
                "localNetwork": "moiraweave-net",
            },
            "execution": {"mode": "session", "timeoutSeconds": 3600},
            "ports": [{"name": "http", "port": 8000}],
            "agent": {
                "adapter": "generic-http",
                "toolOwnership": "runtime",
                "messagePath": "/message",
                "statusPath": "/health",
                "artifactsPath": "/artifacts",
                "exposedChannels": ["ui", "api", "webhook"],
                "capabilities": ["demo", "chat"],
                "runtimeRequirements": {
                    "filesystem": {"persistentWorkspace": False},
                    "network": {"egress": "restricted"},
                    "webSearch": {"enabled": False},
                    "browser": {"mode": "none"},
                    "terminal": {"mode": "none"},
                    "messaging": {"enabled": False},
                },
                "dispatchTimeoutSeconds": 5,
                "pollIntervalSeconds": 1,
            },
            "command": ["python", "-u", "-c"],
            "args": [_DEMO_AGENT_SCRIPT],
        },
    }


def _http_probe(port: str, path: str = "/health") -> dict[str, Any]:
    return {
        "httpGet": {"path": path, "port": port},
        "initialDelaySeconds": 5,
        "periodSeconds": 10,
        "timeoutSeconds": 5,
        "failureThreshold": 6,
    }


def _tcp_probe(port: str) -> dict[str, Any]:
    return {
        "tcpSocket": {"port": port},
        "initialDelaySeconds": 5,
        "periodSeconds": 10,
        "timeoutSeconds": 5,
        "failureThreshold": 6,
    }


def _agent_template_manifest(
    template: str,
    *,
    name: str | None = None,
    image: str | None = None,
    endpoint: str | None = None,
    port: int | None = None,
) -> dict[str, Any]:
    """Return a first-run agent workload manifest."""
    template_id = template.strip().lower()
    if template_id in {"demo", "demo-agent"}:
        return _demo_agent_manifest(name or "demo-agent")

    if template_id == "hermes":
        workload_name = name or "hermes"
        runtime_port = port or 8642
        return {
            "apiVersion": "moiraweave.io/v1alpha1",
            "kind": "Workload",
            "metadata": {
                "name": workload_name,
                "labels": {"moiraweave.io/template": "hermes"},
            },
            "spec": {
                "type": "agent-service",
                "image": image or "ghcr.io/nousresearch/hermes-agent:latest",
                "deployment": {
                    "mode": "managed",
                    "targets": ["local", "kubernetes"],
                    "serviceName": workload_name,
                    "localNetwork": "moiraweave-net",
                },
                "execution": {"mode": "session", "timeoutSeconds": 172800},
                "ports": [{"name": "http", "port": runtime_port}],
                "persistence": {"enabled": True, "mountPath": "/workspace"},
                "livenessProbe": {
                    **_http_probe("http"),
                    "initialDelaySeconds": 15,
                    "periodSeconds": 30,
                    "failureThreshold": 3,
                },
                "readinessProbe": _http_probe("http"),
                "env": {
                    "API_SERVER_ENABLED": "true",
                    "API_SERVER_HOST": "0.0.0.0",
                    "API_SERVER_PORT": str(runtime_port),
                },
                "secrets": ["OPENAI_API_KEY"],
                "agent": {
                    "adapter": "hermes",
                    "toolOwnership": "runtime",
                    "requiredSecrets": ["OPENAI_API_KEY"],
                    "workspaceMount": "/workspace",
                    "authTokenEnv": "HERMES_API_SERVER_KEY",
                    "model": "hermes-agent",
                    "exposedChannels": ["ui", "api"],
                    "capabilities": ["chat", "tools", "long-running"],
                    "runtimeRequirements": {
                        "filesystem": {
                            "persistentWorkspace": True,
                            "workspaceMount": "/workspace",
                        },
                        "network": {"egress": "enabled"},
                        "webSearch": {"enabled": True},
                        "browser": {"mode": "runtime-managed"},
                        "terminal": {
                            "mode": "runtime-managed",
                            "approval": "runtime",
                        },
                        "mcp": {"enabled": True},
                        "messaging": {"enabled": True},
                    },
                    "pollIntervalSeconds": 2,
                },
            },
        }

    if template_id == "openclaw":
        workload_name = name or "openclaw"
        runtime_port = port or 18789
        return {
            "apiVersion": "moiraweave.io/v1alpha1",
            "kind": "Workload",
            "metadata": {
                "name": workload_name,
                "labels": {"moiraweave.io/template": "openclaw"},
            },
            "spec": {
                "type": "agent-service",
                "image": image or "ghcr.io/openclaw/openclaw:latest",
                "deployment": {
                    "mode": "managed",
                    "targets": ["local", "kubernetes"],
                    "serviceName": workload_name,
                    "localNetwork": "moiraweave-net",
                },
                "execution": {"mode": "session", "timeoutSeconds": 172800},
                "ports": [{"name": "gateway", "port": runtime_port}],
                "persistence": {"enabled": True, "mountPath": "/workspace"},
                "livenessProbe": {
                    **_tcp_probe("gateway"),
                    "initialDelaySeconds": 15,
                    "periodSeconds": 30,
                    "failureThreshold": 3,
                },
                "readinessProbe": _tcp_probe("gateway"),
                "agent": {
                    "adapter": "openclaw",
                    "toolOwnership": "runtime",
                    "agentId": "main",
                    "authTokenEnv": "OPENCLAW_GATEWAY_TOKEN",
                    "workspaceMount": "/workspace",
                    "exposedChannels": ["ui", "api"],
                    "capabilities": ["browser", "tools", "long-running"],
                    "runtimeRequirements": {
                        "filesystem": {
                            "persistentWorkspace": True,
                            "workspaceMount": "/workspace",
                        },
                        "network": {"egress": "enabled"},
                        "webSearch": {"enabled": True},
                        "browser": {"mode": "runtime-managed"},
                        "terminal": {
                            "mode": "runtime-managed",
                            "approval": "runtime",
                        },
                        "mcp": {"enabled": True},
                        "messaging": {"enabled": True},
                    },
                    "pollIntervalSeconds": 2,
                },
            },
        }

    if template_id == "generic-http-agent":
        if not image:
            _exit_with_error(
                "--agent-image is required when using --agent generic-http-agent"
            )
        workload_name = name or "generic-agent"
        runtime_port = port or 8000
        return {
            "apiVersion": "moiraweave.io/v1alpha1",
            "kind": "Workload",
            "metadata": {
                "name": workload_name,
                "labels": {"moiraweave.io/template": "generic-http-agent"},
            },
            "spec": {
                "type": "agent-service",
                "image": image,
                "deployment": {
                    "mode": "managed",
                    "targets": ["local", "kubernetes"],
                    "serviceName": workload_name,
                    "localNetwork": "moiraweave-net",
                },
                "execution": {"mode": "session", "timeoutSeconds": 86400},
                "ports": [{"name": "http", "port": runtime_port}],
                "agent": {
                    "adapter": "generic-http",
                    "toolOwnership": "runtime",
                    "messagePath": "/message",
                    "statusPath": "/health",
                    "cancelPath": "/cancel",
                    "artifactsPath": "/artifacts",
                    "exposedChannels": ["ui", "api"],
                    "runtimeRequirements": {
                        "filesystem": {"persistentWorkspace": False},
                        "network": {"egress": "restricted"},
                        "webSearch": {"enabled": False},
                        "browser": {"mode": "none"},
                        "terminal": {"mode": "runtime-managed"},
                    },
                },
            },
        }

    if template_id == "external-agent":
        if not endpoint:
            _exit_with_error(
                "--agent-endpoint is required when using --agent external-agent"
            )
        workload_name = name or "external-agent"
        return {
            "apiVersion": "moiraweave.io/v1alpha1",
            "kind": "Workload",
            "metadata": {
                "name": workload_name,
                "labels": {"moiraweave.io/template": "external-agent"},
            },
            "spec": {
                "type": "agent-service",
                "deployment": {"mode": "external"},
                "endpoint": endpoint,
                "execution": {"mode": "session", "timeoutSeconds": 86400},
                "agent": {
                    "adapter": "generic-http",
                    "toolOwnership": "runtime",
                    "exposedChannels": ["ui", "api"],
                    "runtimeRequirements": {
                        "filesystem": {"persistentWorkspace": False},
                        "network": {"egress": "restricted"},
                        "webSearch": {"enabled": False},
                        "browser": {"mode": "none"},
                        "terminal": {"mode": "runtime-managed"},
                    },
                },
            },
        }

    _exit_with_error(
        f"Unknown agent template: {template}",
        hint="Use demo-agent, hermes, openclaw, generic-http-agent, external-agent, or none.",
    )


def _agent_runtime_requirements(
    adapter: str,
    *,
    persistent_workspace: bool,
    workspace_mount: str | None,
) -> dict[str, Any]:
    if adapter in {"hermes", "openclaw"}:
        return {
            "filesystem": {
                "persistentWorkspace": persistent_workspace,
                "workspaceMount": workspace_mount,
            },
            "network": {"egress": "enabled"},
            "webSearch": {"enabled": True},
            "browser": {"mode": "runtime-managed"},
            "terminal": {"mode": "runtime-managed", "approval": "runtime"},
            "mcp": {"enabled": True},
            "messaging": {"enabled": True},
        }
    return {
        "filesystem": {
            "persistentWorkspace": persistent_workspace,
            "workspaceMount": workspace_mount,
        },
        "network": {"egress": "restricted"},
        "webSearch": {"enabled": False},
        "browser": {"mode": "none"},
        "terminal": {"mode": "runtime-managed"},
    }


def _dotenv_values(repo_root: pathlib.Path) -> dict[str, str]:
    path = repo_root / ".env"
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key.strip() and value.strip():
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _dotenv_keys(repo_root: pathlib.Path) -> set[str]:
    return set(_dotenv_values(repo_root))


def _kubernetes_secret_keys(
    namespace: str,
    secret_name: str,
) -> tuple[set[str], dict[str, Any]]:
    command = [
        "kubectl",
        "get",
        "secret",
        secret_name,
        "-n",
        namespace,
        "-o",
        "json",
    ]
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return set(), {
            "status": "unavailable",
            "namespace": namespace,
            "secret": secret_name,
            "message": "kubectl was not found in PATH.",
        }
    if proc.returncode != 0:
        return set(), {
            "status": "unavailable",
            "namespace": namespace,
            "secret": secret_name,
            "message": proc.stderr.strip() or "kubectl could not read the Secret.",
        }
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return set(), {
            "status": "unavailable",
            "namespace": namespace,
            "secret": secret_name,
            "message": "kubectl returned invalid JSON for the Secret.",
        }
    data = payload.get("data") if isinstance(payload, dict) else None
    keys = set(data) if isinstance(data, dict) else set()
    return keys, {
        "status": "available",
        "namespace": namespace,
        "secret": secret_name,
        "key_count": len(keys),
    }


def _workload_secret_references(manifest: dict[str, Any]) -> list[tuple[str, str]]:
    spec = manifest.get("spec", {})
    if not isinstance(spec, dict):
        return []
    references = [(str(secret), "spec.secrets") for secret in spec.get("secrets") or []]
    agent = spec.get("agent") or {}
    if isinstance(agent, dict):
        references.extend(
            (str(secret), "spec.agent.requiredSecrets")
            for secret in agent.get("requiredSecrets") or []
        )
        auth_token_env = agent.get("authTokenEnv")
        if auth_token_env:
            references.append((str(auth_token_env), "spec.agent.authTokenEnv"))
        for path, value in _runtime_requirement_secret_refs(
            agent.get("runtimeRequirements") or {}
        ):
            references.append((value, f"spec.agent.runtimeRequirements.{path}"))
    return references


def _runtime_requirement_secret_refs(
    value: Any,
    *,
    path: str = "",
) -> list[tuple[str, str]]:
    if isinstance(value, dict):
        refs: list[tuple[str, str]] = []
        for key, item in value.items():
            next_path = f"{path}.{key}" if path else str(key)
            if key == "requiredSecrets" and isinstance(item, list):
                refs.extend((next_path, str(secret)) for secret in item)
            else:
                refs.extend(_runtime_requirement_secret_refs(item, path=next_path))
        return refs
    if isinstance(value, list):
        refs = []
        for index, item in enumerate(value):
            refs.extend(_runtime_requirement_secret_refs(item, path=f"{path}.{index}"))
        return refs
    return []


def _secret_inventory(
    manifests: list[dict[str, Any]],
    repo_root: pathlib.Path,
    *,
    workload: str | None = None,
    target: str = "local",
    namespace: str | None = None,
    kubernetes_secret: str = "moiraweave-secrets",
    kubernetes_keys: set[str] | None = None,
    kubernetes_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_target = "kubernetes" if target == "k8s" else target
    available_env = set(os.environ)
    available_dotenv = _dotenv_keys(repo_root)
    resolved_namespace = namespace or "moiraweave"
    if normalized_target == "kubernetes" and kubernetes_keys is None:
        kubernetes_keys, kubernetes_status = _kubernetes_secret_keys(
            resolved_namespace,
            kubernetes_secret,
        )
    available_kubernetes = kubernetes_keys or set()
    inventory: dict[str, dict[str, Any]] = {}
    for manifest in manifests:
        workload_name = _workload_name(manifest)
        if workload and workload_name != workload:
            continue
        for secret_name, reference in _workload_secret_references(manifest):
            item = inventory.setdefault(
                secret_name,
                {"workloads": set(), "references": set()},
            )
            item["workloads"].add(workload_name)
            item["references"].add(f"{workload_name}:{reference}")

    secrets = []
    for name, data in sorted(inventory.items()):
        local_source = None
        if name in available_env:
            local_source = "environment"
        elif name in available_dotenv:
            local_source = ".env"
        source = "missing"
        if normalized_target == "kubernetes":
            if name in available_kubernetes:
                source = f"kubernetes:{resolved_namespace}/{kubernetes_secret}"
        else:
            source = local_source or "missing"
        secrets.append(
            {
                "name": name,
                "present": source != "missing",
                "source": source,
                "local_source": local_source,
                "workloads": sorted(data["workloads"]),
                "references": sorted(data["references"]),
            }
        )
    missing = sum(1 for item in secrets if not item["present"])
    result: dict[str, Any] = {
        "status": "warning" if missing else "passed",
        "target": normalized_target,
        "total": len(secrets),
        "missing": missing,
        "secrets": secrets,
    }
    if normalized_target == "kubernetes":
        result["kubernetes"] = kubernetes_status or {
            "status": "not_checked",
            "namespace": resolved_namespace,
            "secret": kubernetes_secret,
        }
    return result


def _missing_required_env(
    manifests: list[dict[str, Any]],
    repo_root: pathlib.Path,
) -> list[str]:
    available = set(os.environ) | _dotenv_keys(repo_root)
    required = {
        secret
        for manifest in manifests
        for secret, _reference in _workload_secret_references(manifest)
    }
    return sorted(secret for secret in required if secret not in available)


def _doctor_check(
    name: str,
    status: str,
    message: str,
    recommendation: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "message": message,
        "recommendation": recommendation,
        "metadata": metadata or {},
    }


def _doctor_has_errors(report: dict[str, Any]) -> bool:
    return any(check["status"] == "error" for check in report["checks"])


def _doctor_overall_status(checks: list[dict[str, Any]]) -> str:
    if not checks:
        return "ok"
    return max(
        (str(check["status"]) for check in checks),
        key=lambda status: _DOCTOR_STATUS_ORDER.get(status, 0),
    )


def _doctor_action_guide(
    checks: list[dict[str, Any]],
    *,
    target: str,
    env: str = "local",
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    check_by_name = {str(check["name"]): check for check in checks}
    secret_inventory = (
        check_by_name.get("secrets", {}).get("metadata", {}).get("inventory", {})
    )
    if isinstance(secret_inventory, dict):
        missing_secrets = [
            str(secret.get("name"))
            for secret in secret_inventory.get("secrets", [])
            if isinstance(secret, dict) and not secret.get("present")
        ]
        if missing_secrets:
            local_secret_lines = "\\n".join(f"{name}=..." for name in missing_secrets)
            kubernetes_secret_args = " ".join(
                f"--from-literal={name}=..." for name in missing_secrets
            )
            items.append(
                {
                    "title": "Set Missing Secrets",
                    "state": "missing",
                    "detail": (
                        "Required secret names are missing: "
                        f"{', '.join(sorted(missing_secrets))}. Values stay outside "
                        "the CLI, UI, and API."
                    ),
                    "command": (
                        f"kubectl create secret generic moiraweave-secrets {kubernetes_secret_args}"
                        if target == "kubernetes"
                        else f"printf '{local_secret_lines}\\n' >> .env"
                    ),
                }
            )

    for check in checks:
        if check["status"] == "ok":
            continue
        name = str(check["name"])
        if name == "secrets" and any(
            item["title"] == "Set Missing Secrets" for item in items
        ):
            continue
        if name == "docker-cli":
            items.append(
                _doctor_guide_item(
                    "Install Docker",
                    check,
                    command="docker --version",
                )
            )
        elif name in {"docker-compose", "docker-daemon"}:
            items.append(
                _doctor_guide_item(
                    "Restore Docker Compose",
                    check,
                    command="docker compose version",
                )
            )
        elif name in {"compose-base", "workload-manifests"}:
            items.append(
                _doctor_guide_item(
                    "Regenerate Workspace Files",
                    check,
                    command="moira init --non-interactive",
                )
            )
        elif name == "compose-workloads":
            items.append(
                _doctor_guide_item(
                    "Generate Workload Compose",
                    check,
                    command="moira deploy local",
                )
            )
        elif name == "compose-ports":
            items.append(
                _doctor_guide_item(
                    "Resolve Port Collision",
                    check,
                    command="moira doctor --json",
                )
            )
        elif name == "container-images":
            items.append(
                _doctor_guide_item(
                    "Fix Container Images",
                    check,
                    command="docker login ghcr.io",
                )
            )
        elif name == "api-ready":
            items.append(
                _doctor_guide_item(
                    "Inspect API And Worker",
                    check,
                    command="docker compose logs api-gateway worker",
                )
            )
        elif name == "ui":
            items.append(
                _doctor_guide_item(
                    "Inspect UI",
                    check,
                    command="docker compose logs ui",
                )
            )
        elif name == "local-ports":
            items.append(
                _doctor_guide_item(
                    "Free Local Ports",
                    check,
                    command="moira doctor --json",
                )
            )
        elif name == "demo-agent":
            items.append(
                _doctor_guide_item(
                    "Create Demo Agent",
                    check,
                    command="moira up --agent demo-agent",
                )
            )
        else:
            items.append(_doctor_guide_item(str(check["name"]), check))

    if not items:
        return [
            {
                "title": "Ready",
                "state": "ready",
                "detail": (
                    "No blocking action detected for the selected local workspace."
                ),
                "command": f"moira deploy {target} --register"
                if target != "local"
                else "moira up",
            }
        ]
    if any(item["title"] == "Set Missing Secrets" for item in items) and not any(
        item["title"] == "Sync Deployment Record" for item in items
    ):
        items.append(
            {
                "title": "Sync Deployment Record",
                "state": "not_checked",
                "detail": (
                    f"After the runtime starts, sync a {target}/{env} deployment "
                    "record so MoiraWeave can connect runs, health, and artifacts."
                ),
                "command": "moira deploy local --register"
                if target == "local"
                else f"moira deploy k8s --env {env} --register",
            }
        )
    return items


def _doctor_guide_item(
    title: str,
    check: dict[str, Any],
    *,
    command: str | None = None,
) -> dict[str, str]:
    item = {
        "title": title,
        "state": str(check["status"]),
        "detail": str(check["recommendation"] or check["message"]),
    }
    if command:
        item["command"] = command
    return item


def _safe_load_workload_manifests(
    repo_root: pathlib.Path,
) -> tuple[list[dict[str, Any]], list[str]]:
    root = _workloads_root(repo_root)
    manifests: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in sorted(root.glob("*/workload.yaml")):
        try:
            manifest = dict(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        except Exception as exc:
            errors.append(f"{path.relative_to(repo_root)}: {exc}")
            continue
        manifest["_path"] = str(path)
        manifests.append(manifest)
    return manifests, errors


def _env_int(repo_root: pathlib.Path, name: str, default: int) -> int:
    raw = os.environ.get(name) or _dotenv_values(repo_root).get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _api_ready(api_url: str) -> tuple[bool, str]:
    try:
        with httpx.Client(timeout=2.0) as client:
            response = client.get(f"{api_url.rstrip('/')}/ready")
        return _ready_response_status(response)
    except httpx.HTTPError as exc:
        return False, str(exc)


def _ready_response_status(response: httpx.Response) -> tuple[bool, str]:
    if response.status_code >= 500:
        return False, f"ready endpoint returned HTTP {response.status_code}"
    try:
        body = response.json()
    except ValueError:
        return True, f"ready endpoint returned HTTP {response.status_code}"
    if not isinstance(body, dict):
        return True, f"ready endpoint returned HTTP {response.status_code}"

    status = str(body.get("status") or "")
    if status == "ready":
        return True, "ready endpoint status ready"
    if status:
        return False, f"ready endpoint status {status}{_ready_check_summary(body)}"
    return True, f"ready endpoint returned HTTP {response.status_code}"


def _ready_check_summary(body: dict[str, Any]) -> str:
    checks = body.get("checks")
    if not isinstance(checks, dict):
        return ""
    degraded: list[str] = []
    for name, raw_check in checks.items():
        if not isinstance(raw_check, dict):
            continue
        check_status = raw_check.get("status")
        if check_status and check_status != "ok":
            degraded.append(f"{name}={check_status}")
    return f" ({', '.join(degraded)})" if degraded else ""


def _url_reachable(url: str) -> tuple[bool, str]:
    try:
        with httpx.Client(timeout=2.0, follow_redirects=True) as client:
            response = client.get(url)
        if response.status_code < 500:
            return True, f"HTTP {response.status_code}"
        return False, f"HTTP {response.status_code}"
    except httpx.HTTPError as exc:
        return False, str(exc)


def _is_local_port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


def _resolve_env_expression(value: str, repo_root: pathlib.Path) -> str:
    match = re.fullmatch(r"\$\{([A-Z0-9_]+)(?::-(.+))?\}", value)
    if match is None:
        return value
    env_name, default = match.groups()
    return (
        os.environ.get(env_name)
        or _dotenv_values(repo_root).get(env_name)
        or default
        or value
    )


def _published_host_port(raw_port: Any, repo_root: pathlib.Path) -> int | None:
    if isinstance(raw_port, int):
        return raw_port
    if not isinstance(raw_port, str):
        return None
    if raw_port.startswith("${") and "}" in raw_port:
        host_part = raw_port[: raw_port.index("}") + 1]
    else:
        host_part = raw_port.split(":", maxsplit=1)[0]
    host_part = _resolve_env_expression(host_part, repo_root)
    try:
        return int(host_part)
    except ValueError:
        return None


def _compose_published_ports(path: pathlib.Path, repo_root: pathlib.Path) -> list[int]:
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    services = data.get("services") if isinstance(data, dict) else {}
    if not isinstance(services, dict):
        return []
    ports: list[int] = []
    for service in services.values():
        if not isinstance(service, dict):
            continue
        for raw_port in service.get("ports") or []:
            port = _published_host_port(raw_port, repo_root)
            if port is not None:
                ports.append(port)
    return ports


def _compose_images(path: pathlib.Path, repo_root: pathlib.Path) -> list[str]:
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    services = data.get("services") if isinstance(data, dict) else {}
    if not isinstance(services, dict):
        return []
    images: list[str] = []
    for service in services.values():
        if not isinstance(service, dict):
            continue
        image = service.get("image")
        if isinstance(image, str):
            images.append(_resolve_env_expression(image, repo_root))
    return images


def _docker_image_availability(
    image: str,
    *,
    attempts: int = 4,
    delay_seconds: float = 1.0,
) -> DockerImageAvailability:
    local_ok, local_output = _probe_command(
        ["docker", "image", "inspect", image],
        timeout=3.0,
    )
    if local_ok:
        return DockerImageAvailability(
            image=image,
            status="ok",
            message=f"{image} is present locally.",
        )
    remote_output = ""
    for attempt in range(max(attempts, 1)):
        remote_ok, remote_output = _probe_command(
            ["docker", "manifest", "inspect", image],
            timeout=10.0,
        )
        if remote_ok:
            return DockerImageAvailability(
                image=image,
                status="ok",
                message=f"{image} is available remotely.",
            )
        if _docker_image_failure_status(remote_output) == "error":
            break
        if attempt < attempts - 1:
            time.sleep(delay_seconds)
    message = remote_output or local_output or "image is not available"
    return DockerImageAvailability(
        image=image,
        status=_docker_image_failure_status(message),
        message=message,
    )


def _docker_image_available(image: str, *, attempts: int = 4) -> tuple[bool, str]:
    availability = _docker_image_availability(image, attempts=attempts)
    return availability.available, availability.message


def _docker_image_failure_status(message: str) -> str:
    lowered = message.lower()
    if any(marker in lowered for marker in _FATAL_IMAGE_ERROR_MARKERS):
        return "error"
    if any(marker in lowered for marker in _TRANSIENT_IMAGE_ERROR_MARKERS):
        return "warning"
    return "error"


def _doctor_report(
    *,
    target: str,
    api_url: str,
    repo_root: pathlib.Path | None = None,
) -> dict[str, Any]:
    """Build a local diagnostics report for onboarding and automation."""
    checks: list[dict[str, Any]] = []
    workspace_root = repo_root
    if workspace_root is None:
        try:
            workspace_root = find_repo_root()
        except FileNotFoundError:
            workspace_root = pathlib.Path.cwd().resolve()
            checks.append(
                _doctor_check(
                    "workspace",
                    "error",
                    "No MoiraWeave workspace found.",
                    "Run `moira up` from an empty directory to initialize one.",
                    {"path": str(workspace_root)},
                )
            )
    if workspace_root is not None and not any(
        check["name"] == "workspace" for check in checks
    ):
        checks.append(
            _doctor_check(
                "workspace",
                "ok",
                f"Workspace detected at {workspace_root}.",
                "No action needed.",
                {"path": str(workspace_root)},
            )
        )

    manifests: list[dict[str, Any]] = []
    if workspace_root is not None and (workspace_root / "moiraweave.yaml").exists():
        env_path = workspace_root / ".env"
        checks.append(
            _doctor_check(
                ".env",
                "ok" if env_path.exists() else "error",
                ".env exists." if env_path.exists() else ".env is missing.",
                "No action needed."
                if env_path.exists()
                else "Run `moira init --non-interactive` or `moira up`.",
                {"path": str(env_path)},
            )
        )

        manifests, manifest_errors = _safe_load_workload_manifests(workspace_root)
        if manifest_errors:
            checks.append(
                _doctor_check(
                    "workload-manifests",
                    "error",
                    "One or more workload manifests are invalid.",
                    "Fix the YAML before starting the local stack.",
                    {"errors": manifest_errors},
                )
            )
        elif manifests:
            checks.append(
                _doctor_check(
                    "workload-manifests",
                    "ok",
                    f"Found {len(manifests)} workload manifest(s).",
                    "No action needed.",
                    {"workloads": [_workload_name(manifest) for manifest in manifests]},
                )
            )
        else:
            checks.append(
                _doctor_check(
                    "workload-manifests",
                    "warning",
                    "No workload manifests found.",
                    "Run `moira up --agent demo-agent` for a no-secret first run.",
                )
            )

        demo_present = any(
            _workload_name(manifest) == "demo-agent" for manifest in manifests
        )
        checks.append(
            _doctor_check(
                "demo-agent",
                "ok" if demo_present else "warning",
                "Demo agent manifest is available."
                if demo_present
                else "Demo agent manifest is not present.",
                "No action needed."
                if demo_present
                else "Use `moira up --agent demo-agent` when you want a no-secret smoke test.",
            )
        )

        secret_inventory = _secret_inventory(manifests, workspace_root)
        missing = int(secret_inventory["missing"])
        checks.append(
            _doctor_check(
                "secrets",
                "error" if missing else "ok",
                f"{missing} required secret(s) missing."
                if missing
                else "All required secret names are present.",
                "Run `moira secrets list` and add missing names to .env or your shell."
                if missing
                else "No action needed.",
                {"inventory": secret_inventory},
            )
        )

        base_compose = workspace_root / "docker-compose.yml"
        workload_compose = _deploy_root(workspace_root) / "docker-compose.workloads.yml"
        checks.append(
            _doctor_check(
                "compose-base",
                "ok" if base_compose.exists() else "error",
                "Base Docker Compose file exists."
                if base_compose.exists()
                else "Base Docker Compose file is missing.",
                "No action needed."
                if base_compose.exists()
                else "Run `moira init --non-interactive`.",
                {"path": str(base_compose)},
            )
        )
        checks.append(
            _doctor_check(
                "compose-workloads",
                "ok" if workload_compose.exists() else "warning",
                "Workload Docker Compose file exists."
                if workload_compose.exists()
                else "Workload Docker Compose file has not been generated yet.",
                "No action needed."
                if workload_compose.exists()
                else "`moira up` will generate it before Docker starts.",
                {"path": str(workload_compose)},
            )
        )
        ports = [
            *_compose_published_ports(base_compose, workspace_root),
            *_compose_published_ports(workload_compose, workspace_root),
        ]
        duplicates = sorted(port for port, count in Counter(ports).items() if count > 1)
        checks.append(
            _doctor_check(
                "compose-ports",
                "error" if duplicates else "ok",
                f"Duplicate published host ports: {', '.join(map(str, duplicates))}."
                if duplicates
                else "No duplicate published host ports detected in generated Compose files.",
                "Change workload ports or platform port environment variables."
                if duplicates
                else "No action needed.",
                {"duplicates": duplicates},
            )
        )

    docker_path = shutil.which("docker")
    daemon_ok = False
    checks.append(
        _doctor_check(
            "docker-cli",
            "ok" if docker_path else "error",
            f"Docker CLI found at {docker_path}."
            if docker_path
            else "Docker CLI is not installed or not on PATH.",
            "No action needed."
            if docker_path
            else "Install Docker Desktop or Docker Engine with Compose.",
        )
    )
    if docker_path:
        compose_ok, compose_output = _probe_command(["docker", "compose", "version"])
        checks.append(
            _doctor_check(
                "docker-compose",
                "ok" if compose_ok else "error",
                compose_output or "Docker Compose plugin is available."
                if compose_ok
                else compose_output or "Docker Compose plugin is unavailable.",
                "No action needed."
                if compose_ok
                else "Install or enable the Docker Compose plugin.",
            )
        )
        daemon_ok, daemon_output = _probe_command(
            ["docker", "info", "--format", "{{.ServerVersion}}"]
        )
        checks.append(
            _doctor_check(
                "docker-daemon",
                "ok" if daemon_ok else "error",
                f"Docker daemon is reachable ({daemon_output})."
                if daemon_ok
                else daemon_output or "Docker daemon is not reachable.",
                "No action needed."
                if daemon_ok
                else "Start Docker and retry `moira up`.",
            )
        )
        if daemon_ok and workspace_root is not None:
            base_compose = workspace_root / "docker-compose.yml"
            workload_compose = (
                _deploy_root(workspace_root) / "docker-compose.workloads.yml"
            )
            images = sorted(
                set(
                    [
                        *_compose_images(base_compose, workspace_root),
                        *_compose_images(workload_compose, workspace_root),
                    ]
                )
            )
            unavailable: dict[str, str] = {}
            transient: dict[str, str] = {}
            for image in images:
                availability = _docker_image_availability(image)
                if availability.available:
                    continue
                if availability.status == "warning":
                    transient[image] = availability.message
                else:
                    unavailable[image] = availability.message
            unavailable_images = sorted(unavailable)
            unavailable_summary = ", ".join(unavailable_images[:3])
            if len(unavailable_images) > 3:
                unavailable_summary += f", +{len(unavailable_images) - 3} more"
            transient_images = sorted(transient)
            transient_summary = ", ".join(transient_images[:3])
            if len(transient_images) > 3:
                transient_summary += f", +{len(transient_images) - 3} more"
            image_status = "error" if unavailable else "warning" if transient else "ok"
            if unavailable:
                image_message = (
                    f"{len(unavailable)} container image(s) are not accessible: "
                    f"{unavailable_summary}."
                )
                image_recommendation = (
                    "Publish/login to the registry or override MOIRAWEAVE_*_IMAGE "
                    "in .env."
                )
            elif transient:
                image_message = (
                    f"{len(transient)} container image availability check(s) had "
                    f"transient registry/network failures: {transient_summary}."
                )
                image_recommendation = (
                    "Retry `moira up`; Docker may still pull the images. If this "
                    "persists, run `docker login` or override MOIRAWEAVE_*_IMAGE."
                )
            else:
                image_message = (
                    f"{len(images)} container image(s) are locally present or pullable."
                )
                image_recommendation = "No action needed."
            checks.append(
                _doctor_check(
                    "container-images",
                    image_status,
                    image_message,
                    image_recommendation,
                    {
                        "unavailable": unavailable,
                        "transient": transient,
                        "images": images,
                    },
                )
            )

    ready_ok, ready_message = _api_ready(api_url)
    checks.append(
        _doctor_check(
            "api-ready",
            "ok" if ready_ok else "warning",
            f"API gateway is reachable: {ready_message}."
            if ready_ok
            else f"API gateway is not reachable yet: {ready_message}.",
            "No action needed."
            if ready_ok
            else "`moira up` will start the API, or run `docker compose logs api-gateway`.",
            {"url": f"{api_url.rstrip('/')}/ready"},
        )
    )

    if workspace_root is not None:
        ui_port = _env_int(workspace_root, "MOIRAWEAVE_UI_PORT", 3000)
        ui_ok, ui_message = _url_reachable(f"http://localhost:{ui_port}")
        checks.append(
            _doctor_check(
                "ui",
                "ok" if ui_ok else "warning",
                f"UI is reachable: {ui_message}."
                if ui_ok
                else f"UI is not reachable yet: {ui_message}.",
                "No action needed." if ui_ok else "`moira up` will start the UI.",
                {"url": f"http://localhost:{ui_port}"},
            )
        )

        port_status: dict[str, dict[str, Any]] = {}
        parsed = urlparse(api_url)
        api_port = parsed.port or _env_int(workspace_root, "API_GATEWAY_PORT", 8000)
        for service, (env_name, default_port) in _LOCAL_PLATFORM_PORTS.items():
            port = (
                api_port
                if service == "api-gateway"
                else _env_int(workspace_root, env_name, default_port)
            )
            open_now = _is_local_port_open(port)
            port_status[service] = {
                "env": env_name,
                "port": port,
                "open": open_now,
            }
        occupied = [
            f"{service}:{data['port']}"
            for service, data in port_status.items()
            if data["open"]
        ]
        checks.append(
            _doctor_check(
                "local-ports",
                "ok" if ready_ok or not occupied else "error",
                "Platform ports are free or already serving MoiraWeave."
                if ready_ok or not occupied
                else f"Some local ports are already open: {', '.join(occupied)}.",
                "No action needed."
                if ready_ok or not occupied
                else "Stop the conflicting process or change the matching port in .env.",
                {"ports": port_status},
            )
        )

    action_guide = _doctor_action_guide(checks, target=target, env="local")
    return {
        "target": target,
        "api_url": api_url,
        "workspace": str(workspace_root) if workspace_root is not None else None,
        "status": _doctor_overall_status(checks),
        "checks": checks,
        "action_guide": action_guide,
    }


def _print_doctor_report(report: dict[str, Any]) -> None:
    table = ui.table(
        title=f"MoiraWeave doctor ({report['target']})",
        columns=[
            ("Check", "cyan"),
            ("Status", "bold"),
            ("Message", "white"),
            ("Action", "bright_black"),
        ],
    )
    for check in report["checks"]:
        status_label = str(check["status"]).upper()
        if check["status"] == "ok":
            status_label = f"[green]{status_label}[/green]"
        elif check["status"] == "warning":
            status_label = f"[yellow]{status_label}[/yellow]"
        else:
            status_label = f"[red]{status_label}[/red]"
        table.add_row(
            str(check["name"]),
            status_label,
            str(check["message"]),
            str(check["recommendation"]),
        )
    ui.print_table(table)
    _print_action_guide(report.get("action_guide"))
    if report["status"] == "ok":
        ui.success("MoiraWeave local diagnostics passed.")
    elif report["status"] == "warning":
        ui.warning("MoiraWeave local diagnostics passed with warnings.")
    else:
        ui.error("MoiraWeave local diagnostics found blocking errors.")


def _print_action_guide(action_guide: Any) -> None:
    if not isinstance(action_guide, list) or not action_guide:
        return
    guide_table = ui.table(
        title="Deployment readiness guide",
        columns=[
            ("Action", "cyan"),
            ("State", "bold"),
            ("Detail", "white"),
            ("Command", "bright_black"),
        ],
    )
    for item in action_guide:
        if not isinstance(item, dict):
            continue
        guide_table.add_row(
            str(item.get("title", "-")),
            str(item.get("state", "-")),
            str(item.get("detail", "-")),
            str(item.get("command", "")),
        )
    ui.print_table(guide_table)


def _print_preflight_report(report: dict[str, Any]) -> None:
    table = ui.table(
        title=(
            f"Preflight {report.get('workload_name', '-')}"
            f" ({report.get('target', '-')})"
        ),
        columns=[
            ("Check", "cyan"),
            ("Status", "bold"),
            ("Message", "white"),
            ("Remediation", "bright_black"),
        ],
    )
    for check in report.get("checks", []):
        if not isinstance(check, dict):
            continue
        status_value = str(check.get("status", "-"))
        status_label = status_value.upper()
        if status_value == "passed":
            status_label = f"[green]{status_label}[/green]"
        elif status_value == "warning":
            status_label = f"[yellow]{status_label}[/yellow]"
        elif status_value == "failed":
            status_label = f"[red]{status_label}[/red]"
        table.add_row(
            str(check.get("name", "-")),
            status_label,
            str(check.get("message", "-")),
            str(check.get("remediation", "")),
        )
    ui.print_table(table)
    _print_action_guide(report.get("action_guide"))

    status_value = str(report.get("status", "unknown"))
    if status_value == "passed":
        ui.success("Workload preflight passed.")
    elif status_value == "warning":
        ui.warning("Workload preflight passed with warnings.")
    else:
        ui.error("Workload preflight failed.")


def _print_json(data: Any) -> None:
    console.print(Syntax(json.dumps(data, indent=2), "json"))


def _response_items(response: dict[str, Any]) -> list[dict[str, Any]]:
    data = response.get("data", response)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return [data] if isinstance(data, dict) else []


def _table_value(value: Any) -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) or "-"
    return str(value)


def _print_records_table(
    title: str,
    columns: list[tuple[str, str, str]],
    records: list[dict[str, Any]],
) -> None:
    table = ui.table(
        title=title,
        columns=[(label, style) for _key, label, style in columns],
    )
    for record in records:
        table.add_row(
            *[_table_value(record.get(key)) for key, _label, _style in columns]
        )
    ui.print_table(table)


def _validate_role(role: str) -> str:
    if role not in {"admin", "operator", "viewer"}:
        _exit_with_error("Invalid role. Use admin, operator, or viewer.")
    return role


def _watch_run(run_id: str, api_url: str, timeout: int) -> None:
    with Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("{task.description}", style="dim"),
        transient=True,
    ) as progress:
        task = progress.add_task(f"Watching run {run_id}... (0s)", total=None)
        for elapsed in range(timeout):
            status_payload = _request_json("GET", f"{api_url}/v1/runs/{run_id}")
            state = str(status_payload.get("status", "unknown"))
            progress.update(
                task,
                description=f"Watching run {run_id}... ({elapsed}s) [{state}]",
            )
            if state in _TERMINAL_RUN_STATES:
                progress.stop()
                console.print(Syntax(json.dumps(status_payload, indent=2), "json"))
                return
            time.sleep(1)
        progress.stop()
    _exit_with_error(f"Timed out after {timeout}s watching run {run_id}")


def _render_local_workload_compose(
    manifests: list[dict[str, Any]],
    repo_root: pathlib.Path,
) -> dict[str, Any]:
    services: dict[str, Any] = {}
    networks: set[str] = set()
    artifacts_root = _artifacts_root(repo_root)
    for manifest in manifests:
        name = _workload_name(manifest)
        spec = manifest.get("spec", {})
        if not name or not isinstance(spec, dict):
            continue
        deployment = spec.get("deployment") or {}
        if isinstance(deployment, dict):
            if deployment.get("mode", "managed") == "external":
                continue
            targets = deployment.get("targets") or ["local", "kubernetes"]
            if "local" not in targets:
                continue
            service_name = deployment.get("serviceName") or name
            local_network = deployment.get("localNetwork") or "moiraweave-net"
        else:
            service_name = name
            local_network = "moiraweave-net"
        image = spec.get("image")
        if not image:
            continue

        service: dict[str, Any] = {
            "image": image,
            "restart": "unless-stopped",
            "environment": dict(spec.get("env") or {}),
            "labels": [
                f"moiraweave.io/workload={name}",
                f"moiraweave.io/workload-type={_workload_type(manifest)}",
            ],
            "networks": [local_network],
        }
        networks.add(str(local_network))
        for secret in spec.get("secrets") or []:
            service["environment"][str(secret)] = f"${{{secret}:?set {secret}}}"
        agent = spec.get("agent") or {}
        if isinstance(agent, dict):
            for secret in agent.get("requiredSecrets") or []:
                service["environment"][str(secret)] = f"${{{secret}:?set {secret}}}"
            auth_token_env = agent.get("authTokenEnv")
            if auth_token_env:
                service["environment"][str(auth_token_env)] = (
                    f"${{{auth_token_env}:?set {auth_token_env}}}"
                )

        labels = manifest.get("metadata", {}).get("labels", {})
        is_demo_agent = isinstance(labels, dict) and (
            labels.get("moiraweave.io/template") == "demo-agent"
        )
        if not is_demo_agent:
            ports = []
            for index, port_def in enumerate(spec.get("ports") or []):
                if not isinstance(port_def, dict):
                    continue
                port = port_def.get("port")
                target = port_def.get("targetPort") or port
                if port and target:
                    ports.append(f"{port}:{target}")
            if ports:
                service["ports"] = ports

        persistence = spec.get("persistence") or {}
        persistence_mount_path = None
        if isinstance(persistence, dict) and persistence.get("enabled"):
            mount_path = persistence.get("mountPath")
            if mount_path:
                persistence_mount_path = str(mount_path)
                host_path = artifacts_root / name
                host_path.mkdir(parents=True, exist_ok=True)
                service["volumes"] = [f"{host_path}:{mount_path}"]
        if (
            isinstance(agent, dict)
            and agent.get("workspaceMount")
            and str(agent["workspaceMount"]) != persistence_mount_path
        ):
            host_path = artifacts_root / name / "workspace"
            host_path.mkdir(parents=True, exist_ok=True)
            service.setdefault("volumes", []).append(
                f"{host_path}:{agent['workspaceMount']}"
            )

        if spec.get("command"):
            service["command"] = spec["command"]
        if spec.get("args"):
            service["command"] = [*service.get("command", []), *spec["args"]]

        if not service["environment"]:
            service.pop("environment")
        services[str(service_name)] = service

    compose: dict[str, Any] = {"services": services}
    if networks:
        compose["networks"] = {
            network: {"name": network} for network in sorted(networks)
        }
    return compose


def _render_helm_values(manifests: list[dict[str, Any]]) -> dict[str, Any]:
    workloads: dict[str, Any] = {}
    for manifest in manifests:
        name = _workload_name(manifest)
        spec = manifest.get("spec", {})
        metadata = manifest.get("metadata", {})
        if not name or not isinstance(spec, dict):
            continue
        deployment = spec.get("deployment") or {}
        deployment_mode = (
            deployment.get("mode", "managed")
            if isinstance(deployment, dict)
            else "managed"
        )
        deployment_targets = (
            deployment.get("targets") or ["local", "kubernetes"]
            if isinstance(deployment, dict)
            else ["local", "kubernetes"]
        )
        workloads[name] = {
            "enabled": deployment_mode != "external"
            and "kubernetes" in deployment_targets,
            "metadata": metadata if isinstance(metadata, dict) else {"name": name},
            **spec,
        }
    return {"workloads": workloads}


def _manifest_payload(manifest: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in manifest.items() if key != "_path"}


def _deployment_mode(manifest: dict[str, Any]) -> str:
    spec = manifest.get("spec", {})
    deployment = spec.get("deployment") if isinstance(spec, dict) else {}
    if isinstance(deployment, dict):
        return str(deployment.get("mode", "managed"))
    return "managed"


def _deployment_targets(manifest: dict[str, Any]) -> list[str]:
    spec = manifest.get("spec", {})
    deployment = spec.get("deployment") if isinstance(spec, dict) else {}
    if isinstance(deployment, dict):
        targets = deployment.get("targets") or ["local", "kubernetes"]
        if isinstance(targets, list):
            return [str(target) for target in targets]
    return ["local", "kubernetes"]


def _deployment_service_name(manifest: dict[str, Any]) -> str:
    spec = manifest.get("spec", {})
    deployment = spec.get("deployment") if isinstance(spec, dict) else {}
    if isinstance(deployment, dict) and deployment.get("serviceName"):
        return str(deployment["serviceName"])
    return _workload_name(manifest)


def _deployment_endpoint(manifest: dict[str, Any]) -> str | None:
    spec = manifest.get("spec", {})
    if not isinstance(spec, dict):
        return None
    endpoint = spec.get("endpoint")
    if isinstance(endpoint, str) and endpoint:
        return endpoint.rstrip("/")
    ports = spec.get("ports") or []
    if not ports or not isinstance(ports, list):
        return None
    first_port = ports[0]
    if not isinstance(first_port, dict) or not first_port.get("port"):
        return None
    return f"http://{_deployment_service_name(manifest)}:{first_port['port']}"


def _record_target(manifest: dict[str, Any], target: str) -> str | None:
    if _deployment_mode(manifest) == "external":
        return "external"
    if target in _deployment_targets(manifest):
        return target
    return None


def _register_workload_deployments(
    manifests: list[dict[str, Any]],
    *,
    target: str,
    env: str,
    status: str,
    api_url: str,
) -> None:
    registered = 0
    for manifest in manifests:
        name = _workload_name(manifest)
        record_target = _record_target(manifest, target)
        if not name or record_target is None:
            continue
        _request_json("POST", f"{api_url}/v1/workloads", _manifest_payload(manifest))
        _request_json(
            "POST",
            f"{api_url}/v1/workloads/{name}/deployments",
            {
                "target": record_target,
                "env": env,
                "status": status,
                "endpoint": _deployment_endpoint(manifest),
                "metadata": {
                    "service_name": _deployment_service_name(manifest),
                    "deployment_mode": _deployment_mode(manifest),
                    "environment": env,
                    "source": "moira-cli",
                },
            },
        )
        registered += 1
    ui.success(f"Registered {registered} deployment record(s) for {target} context")


def _wait_for_api_ready(api_url: str, timeout_seconds: int) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with httpx.Client(timeout=2.0) as client:
                response = client.get(f"{api_url.rstrip('/')}/ready")
            ready, _message = _ready_response_status(response)
            if ready:
                return True
        except httpx.HTTPError:
            time.sleep(1)
            continue
        time.sleep(1)
    return False


def _wait_for_url_reachable(url: str, timeout_seconds: int) -> tuple[bool, str]:
    deadline = time.monotonic() + timeout_seconds
    last_message = "not checked"
    while time.monotonic() < deadline:
        reachable, last_message = _url_reachable(url)
        if reachable:
            return True, last_message
        time.sleep(1)
    return False, last_message


def _dev_login_token(api_url: str) -> str | None:
    username = os.environ.get("DEMO_USERNAME", "admin")
    password = os.environ.get("DEMO_PASSWORD", "demo-password")
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.post(
                f"{api_url.rstrip('/')}/auth/token",
                json={"username": username, "password": password},
            )
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPError:
        return None
    token = body.get("access_token") if isinstance(body, dict) else None
    return str(token) if token else None


def _ensure_demo_agent(repo_root: pathlib.Path, *, force: bool = False) -> pathlib.Path:
    target = _workload_file(repo_root, "demo-agent")
    if target.exists() and not force:
        return target
    _write_manifest(target, _demo_agent_manifest("demo-agent"))
    return target


def _ensure_agent_template(
    repo_root: pathlib.Path,
    template: str,
    *,
    name: str | None = None,
    image: str | None = None,
    endpoint: str | None = None,
    port: int | None = None,
    force: bool = False,
) -> pathlib.Path | None:
    template_id = template.strip().lower()
    if template_id in {"", "none", "off", "false"}:
        return None
    manifest = _agent_template_manifest(
        template,
        name=name,
        image=image,
        endpoint=endpoint,
        port=port,
    )
    workload_name = _workload_name(manifest)
    if not workload_name:
        _exit_with_error("Agent template did not include metadata.name")
    target = _workload_file(repo_root, workload_name)
    if target.exists() and not force:
        return target
    _write_manifest(target, manifest)
    return target


@demo_app.command("agent")
def demo_agent(
    name: str = typer.Option("demo-agent", "--name", help="Demo workload name."),
    force: bool = typer.Option(False, "--force", help="Overwrite existing manifest."),
) -> None:
    """Create a runnable mock agent workload without external secrets."""
    repo_root = _repo_root()
    target = _workload_file(repo_root, name)
    if target.exists() and not force:
        _exit_with_error(
            f"Demo agent already exists: {name}",
            hint="Use --force to overwrite it.",
        )
    _write_manifest(target, _demo_agent_manifest(name))
    ui.success(f"Created demo agent workload: {target.relative_to(repo_root)}")


@workload_app.command("new")
def workload_new(
    name: str = typer.Argument(..., help="Workload name."),
    workload_type: str = typer.Option(
        "agent-service",
        "--type",
        help="model-service, pipeline, or agent-service.",
    ),
    image: str | None = typer.Option(None, "--image", help="Container image."),
    endpoint: str | None = typer.Option(
        None,
        "--endpoint",
        help="Runtime base URL. Required for external workloads.",
    ),
    deployment_mode: str = typer.Option(
        "managed",
        "--deployment-mode",
        help="managed or external.",
    ),
    deployment_target: list[str] = typer.Option(
        [],
        "--deployment-target",
        help="Deployment target for managed workloads: local or kubernetes.",
    ),
    service_name: str | None = typer.Option(
        None,
        "--service-name",
        help="Stable service DNS name used by worker/API to reach the workload.",
    ),
    replicas: int = typer.Option(
        1,
        "--replicas",
        min=0,
        help="Managed Kubernetes replica count.",
    ),
    mode: str = typer.Option("session", "--mode", help="sync, async, or session."),
    timeout_seconds: int = typer.Option(3600, "--timeout-seconds", min=1),
    port: list[int] = typer.Option([], "--port", help="Expose TCP port."),
    env_var: list[str] = typer.Option(
        [],
        "--env",
        help="Runtime environment variable as KEY=VALUE.",
    ),
    secret: list[str] = typer.Option([], "--secret", help="Required secret env var."),
    adapter: str = typer.Option(
        "generic-http",
        "--adapter",
        help="Agent adapter: generic-http, hermes, or openclaw.",
    ),
    channel: list[str] = typer.Option(
        ["ui", "api"],
        "--channel",
        help="MoiraWeave-owned agent interaction channel.",
    ),
    external_channel: list[str] = typer.Option(
        [],
        "--external-channel",
        help="Runtime-owned channel, such as telegram or slack.",
    ),
    workspace_mount: str | None = typer.Option(
        None,
        "--workspace-mount",
        help="Agent workspace mount path, for example /workspace.",
    ),
    auth_token_env: str | None = typer.Option(
        None,
        "--auth-token-env",
        help="Environment variable containing the runtime API token.",
    ),
    agent_id: str | None = typer.Option(
        None,
        "--agent-id",
        help="Runtime-specific agent id, for example an OpenClaw agent record.",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help="Runtime model/profile name advertised by the agent server.",
    ),
    instructions: str | None = typer.Option(
        None,
        "--instructions",
        help="Additional per-frontend instructions sent to the agent runtime.",
    ),
    dispatch_timeout_seconds: float = typer.Option(
        30.0,
        "--dispatch-timeout-seconds",
        min=0.1,
        help="Max seconds MoiraWeave waits for an agent dispatch ack.",
    ),
    poll_interval_seconds: float = typer.Option(
        2.0,
        "--poll-interval-seconds",
        min=0.1,
        help="Seconds between runtime status polls for long-running agent turns.",
    ),
    persistence: bool = typer.Option(False, "--persistence"),
    mount_path: str = typer.Option("/data", "--mount-path"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Create a workload.yaml manifest."""
    if workload_type not in {"model-service", "pipeline", "agent-service"}:
        _exit_with_error(
            "Invalid workload type. Use model-service, pipeline, or agent-service."
        )
    if mode not in {"sync", "async", "session"}:
        _exit_with_error("Invalid execution mode. Use sync, async, or session.")
    if deployment_mode not in {"managed", "external"}:
        _exit_with_error("Invalid deployment mode. Use managed or external.")
    deployment_targets = deployment_target or ["local", "kubernetes"]
    invalid_targets = [
        target for target in deployment_targets if target not in {"local", "kubernetes"}
    ]
    if invalid_targets:
        _exit_with_error("Invalid deployment target. Use local or kubernetes.")
    if adapter not in {"generic-http", "hermes", "openclaw"}:
        _exit_with_error("Invalid adapter. Use generic-http, hermes, or openclaw.")
    if workload_type == "agent-service" and adapter in {"hermes", "openclaw"}:
        workspace_mount = workspace_mount or "/workspace"
        if not persistence:
            persistence = True
        if mount_path == "/data":
            mount_path = workspace_mount
    if workload_type != "pipeline" and deployment_mode == "managed" and not image:
        _exit_with_error(
            "--image is required for managed model-service and agent-service workloads"
        )
    if workload_type != "pipeline" and deployment_mode == "external" and not endpoint:
        _exit_with_error("--endpoint is required for external workloads")
    env_values = _parse_key_value_options(env_var, option="--env")

    repo_root = _repo_root()
    target = _workload_file(repo_root, name)
    if target.exists() and not force:
        _exit_with_error(
            f"Workload already exists: {name}", hint="Use --force to overwrite"
        )

    manifest: dict[str, Any] = {
        "apiVersion": "moiraweave.io/v1alpha1",
        "kind": "Workload",
        "metadata": {"name": name},
        "spec": {
            "type": workload_type,
            "deployment": {
                "mode": deployment_mode,
                "targets": deployment_targets,
                "serviceName": service_name,
                "replicas": replicas,
                "localNetwork": "moiraweave-net",
            },
            "execution": {"mode": mode, "timeoutSeconds": timeout_seconds},
            "ports": [
                {"name": "http" if index == 0 else f"port-{value}", "port": value}
                for index, value in enumerate(port)
            ],
            "persistence": {
                "enabled": persistence,
                "mountPath": mount_path if persistence else None,
            },
            "secrets": list(secret),
            "env": env_values,
        },
    }
    if image:
        manifest["spec"]["image"] = image
    if endpoint:
        manifest["spec"]["endpoint"] = endpoint
    if workload_type == "agent-service":
        manifest["spec"]["agent"] = {
            "adapter": adapter,
            "toolOwnership": "runtime",
            "requiredSecrets": list(secret),
            "exposedChannels": list(dict.fromkeys(channel)),
            "externalOwnedChannels": list(dict.fromkeys(external_channel)),
            "workspaceMount": workspace_mount,
            "authTokenEnv": auth_token_env,
            "agentId": agent_id,
            "model": model,
            "instructions": instructions,
            "runtimeRequirements": _agent_runtime_requirements(
                adapter,
                persistent_workspace=persistence,
                workspace_mount=workspace_mount,
            ),
            "dispatchTimeoutSeconds": dispatch_timeout_seconds,
            "pollIntervalSeconds": poll_interval_seconds,
        }

    _write_manifest(target, manifest)
    ui.success(f"Created workload manifest: {target.relative_to(repo_root)}")


@workload_app.command("list")
def workload_list() -> None:
    """List local workload manifests."""
    repo_root = _repo_root()
    items = [
        {
            "name": _workload_name(manifest),
            "type": _workload_type(manifest),
            "path": str(pathlib.Path(str(manifest["_path"])).relative_to(repo_root)),
        }
        for manifest in _load_workload_manifests(repo_root)
    ]
    console.print(Syntax(json.dumps(items, indent=2), "json"))


@workload_app.command("show")
def workload_show(name: str = typer.Argument(..., help="Workload name.")) -> None:
    """Show a local workload manifest."""
    repo_root = _repo_root()
    path = _workload_file(repo_root, name)
    if not path.exists():
        _exit_with_error(f"Workload not found: {name}")
    console.print(Syntax(path.read_text(encoding="utf-8"), "yaml"))


@workload_app.command("deploy")
def workload_deploy(
    name: str = typer.Argument(..., help="Workload name."),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Register one workload manifest with the API gateway."""
    repo_root = _repo_root()
    path = _workload_file(repo_root, name)
    if not path.exists():
        _exit_with_error(f"Workload not found: {name}")
    response = _request_json("POST", f"{api_url}/v1/workloads", _load_yaml_file(path))
    console.print(Syntax(json.dumps(response, indent=2), "json"))


@workload_app.command("status")
def workload_status(
    name: str = typer.Argument(..., help="Workload name."),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Show API-visible workload health, deployments, and recent runs."""
    workload = _request_json("GET", f"{api_url}/v1/workloads/{name}")
    console.print(Syntax(json.dumps(workload, indent=2), "json"))
    health = _request_json("GET", f"{api_url}/v1/workloads/{name}/health")
    console.print(Syntax(json.dumps(health, indent=2), "json"))
    runs = _request_json("GET", f"{api_url}/v1/runs?workload_name={name}&limit=5")
    console.print(Syntax(json.dumps(runs, indent=2), "json"))


@workload_app.command("preflight")
def workload_preflight(
    name: str = typer.Argument(..., help="Workload name."),
    target: str = typer.Option(
        "local",
        "--target",
        help="Deployment target to validate: local, kubernetes/k8s, or external.",
    ),
    env: str = typer.Option("local", "--env", help="Deployment environment."),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print raw preflight response as JSON.",
    ),
) -> None:
    """Run API preflight and show concrete deployment readiness actions."""
    normalized_target = "kubernetes" if target == "k8s" else target
    if normalized_target not in {"local", "kubernetes", "external"}:
        _exit_with_error("Invalid target. Use local, kubernetes/k8s, or external.")
    response = _request_json(
        "POST",
        f"{api_url}/v1/workloads/{name}/preflight",
        {"target": normalized_target, "env": env},
    )
    if json_output:
        console.print(Syntax(json.dumps(response, indent=2), "json"))
    else:
        _print_preflight_report(response)
    if response.get("status") == "failed":
        raise typer.Exit(code=1)


@workload_app.command("logs")
def workload_logs(
    name: str = typer.Argument(..., help="Workload name."),
    follow: bool = typer.Option(False, "--follow", "-f"),
    env: str = typer.Option("local", "--env"),
) -> None:
    """Show logs for a local Compose or Kubernetes workload service."""
    repo_root = _repo_root()
    if env == "local":
        command = ["docker", "compose", "logs", "--tail", "200"]
        if follow:
            command.append("-f")
        command.append(name)
        ui.info(_run_command(command, cwd=repo_root))
        return
    config = load_moiraweave_config(repo_root)
    target = config.environments.get(env)
    namespace = target.namespace if target and target.namespace else "moiraweave"
    command = [
        "kubectl",
        "logs",
        "-n",
        namespace,
        "-l",
        f"moiraweave.io/workload={name}",
        "--tail",
        "200",
    ]
    if follow:
        command.append("-f")
    ui.info(_run_command(command, cwd=repo_root))


@secrets_app.command("list")
def secrets_list(
    workload: str | None = typer.Option(
        None,
        "--workload",
        "-w",
        help="Filter by workload name.",
    ),
    target: str = typer.Option(
        "local",
        "--target",
        help="Secret target to inspect: local or kubernetes.",
    ),
    env: str = typer.Option(
        "dev",
        "--env",
        help="Environment used to resolve Kubernetes namespace.",
    ),
    namespace: str | None = typer.Option(
        None,
        "--namespace",
        help="Kubernetes namespace. Overrides environment namespace.",
    ),
    kubernetes_secret: str = typer.Option(
        "moiraweave-secrets",
        "--kubernetes-secret",
        help="Kubernetes Secret containing workload secret keys.",
    ),
    check: bool = typer.Option(
        False,
        "--check",
        help="Exit with code 2 when required secrets are missing.",
    ),
) -> None:
    """List required secret names without exposing secret values."""
    repo_root = _repo_root()
    manifests = _load_workload_manifests(repo_root)
    if workload and workload not in {
        _workload_name(manifest) for manifest in manifests
    }:
        _exit_with_error(f"Unknown workload: {workload}")
    normalized_target = "kubernetes" if target == "k8s" else target
    if normalized_target not in {"local", "kubernetes"}:
        _exit_with_error("--target must be local or kubernetes")
    resolved_namespace = namespace
    if normalized_target == "kubernetes" and not resolved_namespace:
        resolved_namespace = _environment_namespace(repo_root, env)
    inventory = _secret_inventory(
        manifests,
        repo_root,
        workload=workload,
        target=normalized_target,
        namespace=resolved_namespace,
        kubernetes_secret=kubernetes_secret,
    )
    console.print(Syntax(json.dumps(inventory, indent=2), "json"))
    if check and inventory["missing"]:
        raise typer.Exit(code=2)


@env_app.command("list")
def environment_list(
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
) -> None:
    """List deployment environments visible to the current credential."""
    response = _request_json("GET", f"{api_url}/v1/environments")
    if json_output:
        _print_json(response.get("data", response))
        return
    _print_records_table(
        "MoiraWeave environments",
        [
            ("name", "Environment", "cyan"),
            ("workload_count", "Workloads", "white"),
            ("deployment_count", "Deployments", "white"),
            ("operation_count", "Operations", "white"),
        ],
        _response_items(response),
    )


@security_app.command("me")
def security_me(
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
) -> None:
    """Show the authenticated subject, role, credential, and team scope."""
    response = _request_json("GET", f"{api_url}/auth/me")
    if json_output:
        _print_json(response)
        return
    _print_records_table(
        "Current MoiraWeave identity",
        [
            ("subject", "Subject", "cyan"),
            ("role", "Role", "white"),
            ("credential_type", "Credential", "white"),
            ("team_id", "Key team", "white"),
            ("teams", "Teams", "white"),
        ],
        [response],
    )


@security_app.command("bootstrap-admin")
def security_bootstrap_admin(
    subject: str = typer.Argument(..., help="First persistent admin subject."),
    password: str = typer.Option(
        ...,
        "--password",
        prompt=True,
        hide_input=True,
        confirmation_prompt=True,
        help="Initial admin password, minimum 12 characters.",
    ),
    display_name: str | None = typer.Option(None, "--display-name"),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Create the first admin when demo auth is disabled."""
    response = _request_json(
        "POST",
        f"{api_url}/auth/bootstrap/admin",
        {
            "subject": subject,
            "password": password,
            "display_name": display_name,
        },
        retry_local_login=False,
    )
    ui.success(f"Bootstrapped admin {response.get('subject', subject)}")
    ui.warning("Store this access token or run moira security api-key create next.")
    _print_json(response)


@security_user_app.command("list")
def security_user_list(
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
) -> None:
    """List local MoiraWeave users."""
    response = _request_json("GET", f"{api_url}/auth/users")
    if json_output:
        _print_json(response.get("data", response))
        return
    _print_records_table(
        "MoiraWeave users",
        [
            ("subject", "Subject", "cyan"),
            ("display_name", "Name", "white"),
            ("role", "Role", "white"),
            ("disabled_at", "Disabled", "white"),
            ("updated_at", "Updated", "bright_black"),
        ],
        _response_items(response),
    )


@security_user_app.command("create")
def security_user_create(
    subject: str = typer.Argument(..., help="Login subject."),
    password: str = typer.Option(
        ...,
        "--password",
        prompt=True,
        hide_input=True,
        confirmation_prompt=True,
        help="Password, minimum 8 characters.",
    ),
    role: str = typer.Option("operator", "--role", help="admin, operator, or viewer."),
    display_name: str | None = typer.Option(None, "--display-name"),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Create or update a persistent user."""
    response = _request_json(
        "POST",
        f"{api_url}/auth/users",
        {
            "subject": subject,
            "password": password,
            "role": _validate_role(role),
            "display_name": display_name,
        },
    )
    ui.success(f"Saved user {response.get('subject', subject)}")
    _print_json(response)


@security_user_app.command("update")
def security_user_update(
    subject: str = typer.Argument(..., help="Login subject to update."),
    role: str | None = typer.Option(None, "--role", help="admin, operator, or viewer."),
    display_name: str | None = typer.Option(None, "--display-name"),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Update mutable user metadata without changing credentials."""
    if role is None and display_name is None:
        _exit_with_error(
            "No user changes supplied", hint="Use --role or --display-name"
        )
    payload: dict[str, Any] = {"display_name": display_name}
    if role is not None:
        payload["role"] = _validate_role(role)
    response = _request_json("PATCH", f"{api_url}/auth/users/{subject}", payload)
    ui.success(f"Updated user {response.get('subject', subject)}")
    _print_json(response)


@security_user_app.command("password-change")
def security_user_password_change(
    subject: str = typer.Argument(..., help="Your own login subject."),
    current_password: str = typer.Option(
        ...,
        "--current-password",
        prompt=True,
        hide_input=True,
        help="Current password.",
    ),
    new_password: str = typer.Option(
        ...,
        "--new-password",
        prompt=True,
        hide_input=True,
        confirmation_prompt=True,
        help="New password, minimum 12 characters.",
    ),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Change your own persistent user password."""
    response = _request_json(
        "POST",
        f"{api_url}/auth/users/{subject}/password/change",
        {
            "current_password": current_password,
            "new_password": new_password,
        },
    )
    ui.success(f"Changed password for {response.get('subject', subject)}")


@security_user_app.command("password-reset")
def security_user_password_reset(
    subject: str = typer.Argument(..., help="Login subject to reset."),
    new_password: str = typer.Option(
        ...,
        "--new-password",
        prompt=True,
        hide_input=True,
        confirmation_prompt=True,
        help="New password, minimum 12 characters.",
    ),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Reset a user password as an admin."""
    response = _request_json(
        "POST",
        f"{api_url}/auth/users/{subject}/password/reset",
        {"new_password": new_password},
    )
    ui.success(f"Reset password for {response.get('subject', subject)}")
    _print_json(response)


@security_user_app.command("disable")
def security_user_disable(
    subject: str = typer.Argument(..., help="Login subject to disable."),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Disable a user without deleting audit metadata."""
    response = _request_json("DELETE", f"{api_url}/auth/users/{subject}")
    ui.success(f"Disabled user {response.get('subject', subject)}")
    _print_json(response)


@security_user_app.command("enable")
def security_user_enable(
    subject: str = typer.Argument(..., help="Login subject to enable."),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Enable a disabled user."""
    response = _request_json("POST", f"{api_url}/auth/users/{subject}/enable")
    ui.success(f"Enabled user {response.get('subject', subject)}")
    _print_json(response)


@security_team_app.command("list")
def security_team_list(
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
) -> None:
    """List teams."""
    response = _request_json("GET", f"{api_url}/auth/teams")
    if json_output:
        _print_json(response.get("data", response))
        return
    _print_records_table(
        "MoiraWeave teams",
        [
            ("team_id", "Team", "cyan"),
            ("name", "Name", "white"),
            ("description", "Description", "white"),
            ("updated_at", "Updated", "bright_black"),
        ],
        _response_items(response),
    )


@security_team_app.command("create")
def security_team_create(
    team_id: str = typer.Argument(..., help="Stable team id."),
    name: str = typer.Argument(..., help="Display name."),
    description: str | None = typer.Option(None, "--description"),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Create or update a team."""
    response = _request_json(
        "POST",
        f"{api_url}/auth/teams",
        {"team_id": team_id, "name": name, "description": description},
    )
    ui.success(f"Saved team {response.get('team_id', team_id)}")
    _print_json(response)


@security_team_app.command("update")
def security_team_update(
    team_id: str = typer.Argument(..., help="Stable team id."),
    name: str | None = typer.Option(None, "--name", help="Display name."),
    description: str | None = typer.Option(None, "--description"),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Update team metadata."""
    if name is None and description is None:
        _exit_with_error("No team changes supplied", hint="Use --name or --description")
    response = _request_json(
        "PATCH",
        f"{api_url}/auth/teams/{team_id}",
        {"name": name, "description": description},
    )
    ui.success(f"Updated team {response.get('team_id', team_id)}")
    _print_json(response)


@security_team_app.command("members")
def security_team_members(
    team_id: str = typer.Argument(..., help="Team id."),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
) -> None:
    """List members in a team."""
    response = _request_json("GET", f"{api_url}/auth/teams/{team_id}/members")
    if json_output:
        _print_json(response.get("data", response))
        return
    _print_records_table(
        f"Members of {team_id}",
        [
            ("subject", "Subject", "cyan"),
            ("role", "Role", "white"),
            ("created_by", "Created by", "white"),
            ("created_at", "Created", "bright_black"),
        ],
        _response_items(response),
    )


@security_team_app.command("add-member")
def security_team_add_member(
    team_id: str = typer.Argument(..., help="Team id."),
    subject: str = typer.Argument(..., help="User subject."),
    role: str = typer.Option("operator", "--role", help="admin, operator, or viewer."),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Add or update a team member."""
    response = _request_json(
        "POST",
        f"{api_url}/auth/teams/{team_id}/members",
        {"subject": subject, "role": _validate_role(role)},
    )
    ui.success(f"Saved {response.get('subject', subject)} in team {team_id}")
    _print_json(response)


@security_team_app.command("remove-member")
def security_team_remove_member(
    team_id: str = typer.Argument(..., help="Team id."),
    subject: str = typer.Argument(..., help="User subject."),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Remove a member from a team."""
    response = _request_json(
        "DELETE",
        f"{api_url}/auth/teams/{team_id}/members/{subject}",
    )
    ui.success(f"Removed {response.get('subject', subject)} from team {team_id}")
    _print_json(response)


@security_api_key_app.command("list")
def security_api_key_list(
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
) -> None:
    """List API key metadata without secret values."""
    response = _request_json("GET", f"{api_url}/auth/api-keys")
    if json_output:
        _print_json(response.get("data", response))
        return
    _print_records_table(
        "MoiraWeave API keys",
        [
            ("key_id", "Key", "cyan"),
            ("name", "Name", "white"),
            ("subject", "Subject", "white"),
            ("role", "Role", "white"),
            ("team_id", "Team", "white"),
            ("revoked_at", "Revoked", "white"),
        ],
        _response_items(response),
    )


@security_api_key_app.command("create")
def security_api_key_create(
    name: str = typer.Argument(..., help="Human-readable key name."),
    subject: str = typer.Argument(..., help="Subject represented by the key."),
    role: str = typer.Option("operator", "--role", help="admin, operator, or viewer."),
    team_id: str | None = typer.Option(None, "--team-id", help="Optional team scope."),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Create an API key and print its one-time secret."""
    response = _request_json(
        "POST",
        f"{api_url}/auth/api-keys",
        {
            "name": name,
            "subject": subject,
            "role": _validate_role(role),
            "team_id": team_id,
        },
    )
    ui.success(f"Created API key {response.get('key_id', '-')}")
    ui.warning("Store the secret now. MoiraWeave will not show it again.")
    _print_json(response)


@security_api_key_app.command("rotate")
def security_api_key_rotate(
    key_id: str = typer.Argument(..., help="API key id to rotate."),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Rotate an API key and print the replacement one-time secret."""
    response = _request_json("POST", f"{api_url}/auth/api-keys/{key_id}/rotate")
    ui.success(f"Rotated API key {key_id}")
    ui.warning("Store the new secret now. MoiraWeave will not show it again.")
    _print_json(response)


@security_api_key_app.command("revoke")
def security_api_key_revoke(
    key_id: str = typer.Argument(..., help="API key id to revoke."),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Revoke an API key."""
    response = _request_json("DELETE", f"{api_url}/auth/api-keys/{key_id}")
    ui.success(f"Revoked API key {response.get('key_id', key_id)}")
    _print_json(response)


@run_app.command("submit")
def run_submit(
    workload: str = typer.Argument(..., help="Workload name."),
    input_data: str = typer.Option("{}", "--input", help="Input JSON or @file path."),
    watch: bool = typer.Option(False, "--watch"),
    timeout: int = typer.Option(3600, "--timeout", min=1),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Submit a run to a workload."""
    response = _request_json(
        "POST",
        f"{api_url}/v1/workloads/{workload}/runs",
        {"payload": _parse_json_input(input_data)},
    )
    console.print(Syntax(json.dumps(response, indent=2), "json"))
    run_id = str(response.get("run_id", ""))
    if watch and run_id:
        _watch_run(run_id, api_url, timeout)


@run_app.command("watch")
def run_watch(
    run_id: str = typer.Argument(..., help="Run ID."),
    timeout: int = typer.Option(3600, "--timeout", min=1),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Watch a run until it reaches a terminal state."""
    _watch_run(run_id, api_url, timeout)


@run_app.command("cancel")
def run_cancel(
    run_id: str = typer.Argument(..., help="Run ID."),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Request cooperative cancellation for a run."""
    response = _request_json("POST", f"{api_url}/v1/runs/{run_id}/cancel")
    console.print(Syntax(json.dumps(response, indent=2), "json"))


@run_app.command("events")
def run_events(
    run_id: str = typer.Argument(..., help="Run ID."),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Show stored events for a run."""
    response = _request_json("GET", f"{api_url}/v1/runs/{run_id}/events")
    console.print(Syntax(json.dumps(response.get("data", response), indent=2), "json"))


@run_app.command("artifacts")
def run_artifacts(
    run_id: str = typer.Argument(..., help="Run ID."),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """List artifacts for a run."""
    response = _request_json("GET", f"{api_url}/v1/runs/{run_id}/artifacts")
    console.print(Syntax(json.dumps(response.get("data", response), indent=2), "json"))


@run_dead_letter_app.command("list")
def run_dead_letter_list(
    limit: int = typer.Option(50, "--limit", min=1, max=200),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
) -> None:
    """List failed run dispatch messages from the dead-letter stream."""
    response = _request_json(
        "GET",
        f"{api_url}/v1/runs/dead-letter?{urlencode({'limit': str(limit)})}",
    )
    if json_output:
        _print_json(response.get("data", response))
        return
    _print_records_table(
        "Run dead-letter entries",
        [
            ("message_id", "Message", "cyan"),
            ("reason", "Reason", "yellow"),
            ("source_id", "Source", "white"),
            ("created_at", "Created", "bright_black"),
        ],
        _response_items(response),
    )


@run_dead_letter_app.command("purge")
def run_dead_letter_purge(
    message_id: str = typer.Argument(..., help="Dead-letter stream message ID."),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Delete one dead-letter entry after inspection."""
    response = _request_json("DELETE", f"{api_url}/v1/runs/dead-letter/{message_id}")
    ui.success(f"Purged dead-letter entry {response.get('message_id', message_id)}")
    _print_json(response)


@run_dead_letter_app.command("replay")
def run_dead_letter_replay(
    message_id: str = typer.Argument(..., help="Dead-letter stream message ID."),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Replay one dead-letter entry after fixing the root cause."""
    response = _request_json(
        "POST",
        f"{api_url}/v1/runs/dead-letter/{message_id}/replay",
    )
    ui.success(
        "Replayed dead-letter entry "
        f"{response.get('message_id', message_id)} as "
        f"{response.get('replayed_message_id', '-')}"
    )
    _print_json(response)


@ops_app.command("alerts")
def ops_alerts(
    env: str | None = typer.Option(None, "--env", help="Filter by environment."),
    scope: str = typer.Option(
        "mine", "--scope", help="mine or all. all requires admin."
    ),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
) -> None:
    """Show actionable platform operations alerts."""
    query = urlencode(
        {key: value for key, value in {"env": env, "scope": scope}.items() if value}
    )
    suffix = f"?{query}" if query else ""
    response = _request_json("GET", f"{api_url}/v1/operations/alerts{suffix}")
    if json_output:
        _print_json(response.get("data", response))
        return
    _print_records_table(
        "MoiraWeave operations alerts",
        [
            ("severity", "Severity", "yellow"),
            ("title", "Title", "cyan"),
            ("detail", "Detail", "white"),
            ("action", "Action", "white"),
            ("command", "Command", "bright_black"),
        ],
        _response_items(response),
    )


@app.command()
def doctor(
    target: str = typer.Option(
        "local",
        "--target",
        help="Deployment target to diagnose. Currently supports local.",
    ),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print a machine-readable report.",
    ),
) -> None:
    """Diagnose local onboarding blockers before starting MoiraWeave."""
    if target != "local":
        _exit_with_error("Only --target local is supported by doctor today.")
    report = _doctor_report(target=target, api_url=api_url)
    if json_output:
        console.print(json.dumps(report, indent=2))
    else:
        _print_doctor_report(report)
    if _doctor_has_errors(report):
        raise typer.Exit(code=1)


@agent_session_app.command("create")
def agent_session_create(
    agent: str = typer.Argument(..., help="Agent workload name."),
    metadata: str = typer.Option("{}", "--metadata", help="Metadata JSON."),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Create an agent session."""
    response = _create_agent_session(agent, metadata=metadata, api_url=api_url)
    console.print(Syntax(json.dumps(response, indent=2), "json"))


def _create_agent_session(
    agent: str,
    *,
    metadata: str,
    api_url: str,
) -> dict[str, Any]:
    return _request_json(
        "POST",
        f"{api_url}/v1/agents/{agent}/sessions",
        {"metadata": _parse_json_input(metadata)},
    )


def _send_agent_session_message(
    agent: str,
    session_id: str,
    message: str,
    *,
    context: str,
    api_url: str,
) -> dict[str, Any]:
    return _request_json(
        "POST",
        f"{api_url}/v1/agents/{agent}/sessions/{session_id}/messages",
        {"message": message, "context": _parse_json_input(context)},
    )


@agent_session_app.command("message")
def agent_session_message(
    agent: str = typer.Argument(..., help="Agent workload name."),
    session_id: str = typer.Argument(..., help="Session ID."),
    message: str = typer.Argument(..., help="Message text."),
    context: str = typer.Option("{}", "--context", help="Context JSON."),
    watch: bool = typer.Option(False, "--watch"),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Send a message to an agent session."""
    response = _send_agent_session_message(
        agent,
        session_id,
        message,
        context=context,
        api_url=api_url,
    )
    console.print(Syntax(json.dumps(response, indent=2), "json"))
    run_id = str(response.get("run_id", ""))
    if watch and run_id:
        _watch_run(run_id, api_url, timeout=3600)


@agent_app.command("chat")
def agent_chat(
    agent: str = typer.Argument(..., help="Agent workload name."),
    message: str = typer.Argument(..., help="Message text."),
    session_id: str | None = typer.Option(
        None,
        "--session-id",
        "-s",
        help="Existing session id. A new session is created when omitted.",
    ),
    metadata: str = typer.Option(
        "{}",
        "--metadata",
        help="Metadata JSON for a new session.",
    ),
    context: str = typer.Option("{}", "--context", help="Message context JSON."),
    watch: bool = typer.Option(False, "--watch", help="Watch the associated run."),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Create a session if needed, send one message, and print the response."""
    active_session_id = session_id
    if not active_session_id:
        session = _create_agent_session(agent, metadata=metadata, api_url=api_url)
        raw_session_id = session.get("session_id")
        if not raw_session_id:
            _exit_with_error(
                "Agent session creation did not return a session_id",
                hint="Check the API gateway logs and agent workload name.",
            )
        active_session_id = str(raw_session_id)
        ui.success(f"Created session {active_session_id}")

    response = _send_agent_session_message(
        agent,
        active_session_id,
        message,
        context=context,
        api_url=api_url,
    )
    console.print(Syntax(json.dumps(response, indent=2), "json"))
    run_id = str(response.get("run_id", ""))
    if watch and run_id:
        _watch_run(run_id, api_url, timeout=3600)


@agent_app.command("channel-message")
def agent_channel_message(
    agent: str = typer.Argument(..., help="Agent workload name."),
    channel: str = typer.Argument(..., help="Inbound channel name."),
    external_user_id: str = typer.Argument(..., help="External channel user id."),
    message: str = typer.Argument(..., help="Message text."),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Simulate an inbound Telegram/Slack/Discord/Webhook message."""
    response = _request_json(
        "POST",
        f"{api_url}/v1/channels/{channel}/agents/{agent}/messages",
        {
            "external_user_id": external_user_id,
            "message": message,
            "metadata": {},
        },
    )
    console.print(Syntax(json.dumps(response, indent=2), "json"))


@agent_session_app.command("history")
def agent_session_history(
    agent: str = typer.Argument(..., help="Agent workload name."),
    session_id: str = typer.Argument(..., help="Session ID."),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Show messages for an agent session."""
    response = _request_json(
        "GET",
        f"{api_url}/v1/agents/{agent}/sessions/{session_id}/messages",
    )
    console.print(Syntax(json.dumps(response.get("data", response), indent=2), "json"))


@deploy_app.command("local")
def deploy_local(
    up: bool = typer.Option(False, "--up", help="Run docker compose after generating."),
    register: bool = typer.Option(
        False,
        "--register",
        help="Register workloads and local deployment records in the API.",
    ),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Generate local Docker Compose services from workload manifests."""
    repo_root = _repo_root()
    manifests = _load_workload_manifests(repo_root)
    compose = _render_local_workload_compose(manifests, repo_root)
    deploy_root = _deploy_root(repo_root)
    deploy_root.mkdir(parents=True, exist_ok=True)
    output = deploy_root / "docker-compose.workloads.yml"
    output.write_text(yaml.safe_dump(compose, sort_keys=False), encoding="utf-8")
    ui.success(f"Generated {output.relative_to(repo_root)}")
    if up:
        ui.info(
            _run_command(
                [
                    "docker",
                    "compose",
                    "-f",
                    "docker-compose.yml",
                    "-f",
                    str(output),
                    "up",
                    "-d",
                ],
                cwd=repo_root,
            )
        )
    if register:
        _register_workload_deployments(
            manifests,
            target="local",
            env="local",
            status="running" if up else "generated",
            api_url=api_url,
        )


@deploy_app.command("k8s")
def deploy_k8s(
    apply: bool = typer.Option(
        False, "--apply", help="Run helm upgrade after generating."
    ),
    env: str = typer.Option("dev", "--env"),
    register: bool = typer.Option(
        False,
        "--register",
        help="Register workloads and Kubernetes deployment records in the API.",
    ),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Generate Helm values from workload manifests."""
    repo_root = _repo_root()
    manifests = _load_workload_manifests(repo_root)
    values = _render_helm_values(manifests)
    deploy_root = _deploy_root(repo_root)
    deploy_root.mkdir(parents=True, exist_ok=True)
    output = deploy_root / f"values-workloads-{env}.yaml"
    output.write_text(yaml.safe_dump(values, sort_keys=False), encoding="utf-8")
    ui.success(f"Generated {output.relative_to(repo_root)}")
    if apply:
        namespace = _environment_namespace(repo_root, env)
        ui.info(
            _run_command(
                [
                    "helm",
                    "upgrade",
                    "--install",
                    "moiraweave",
                    "infra/helm/moiraweave",
                    "--namespace",
                    namespace,
                    "--create-namespace",
                    "-f",
                    str(output),
                ],
                cwd=repo_root,
            )
        )
    if register:
        _register_workload_deployments(
            manifests,
            target="kubernetes",
            env=env,
            status="applied" if apply else "generated",
            api_url=api_url,
        )


def _fetch_workload_manifest(api_url: str, workload_name: str) -> dict[str, Any]:
    response = _request_json(
        "GET",
        f"{api_url.rstrip('/')}/v1/workloads/{quote(workload_name, safe='')}",
    )
    manifest = response.get("manifest")
    if not isinstance(manifest, dict):
        _exit_with_error(
            f"Workload {workload_name!r} did not include a manifest response."
        )
    return manifest


def _controller_workload_manifests(
    *,
    api_url: str,
    workload_name: str,
    repo_root: pathlib.Path,
) -> list[dict[str, Any]]:
    local_manifests = _load_workload_manifests(repo_root)
    matched = [
        manifest
        for manifest in local_manifests
        if _workload_name(manifest) == workload_name
    ]
    if matched:
        return matched
    return [_fetch_workload_manifest(api_url, workload_name)]


def _kubernetes_controller_command(
    operation: dict[str, Any],
    *,
    api_url: str,
    repo_root: pathlib.Path,
    chart_ref: str,
    namespace: str | None,
    release: str,
) -> tuple[list[str], pathlib.Path]:
    action = str(operation.get("action") or "")
    workload_name = str(operation.get("workload_name") or "")
    env = str(operation.get("env") or "dev")
    resolved_namespace = namespace or _environment_namespace(repo_root, env)

    if action == "apply":
        manifests = _controller_workload_manifests(
            api_url=api_url,
            workload_name=workload_name,
            repo_root=repo_root,
        )
        values = _render_helm_values(manifests)
        deploy_root = _deploy_root(repo_root)
        deploy_root.mkdir(parents=True, exist_ok=True)
        output = deploy_root / f"values-workloads-{env}.yaml"
        output.write_text(yaml.safe_dump(values, sort_keys=False), encoding="utf-8")
        return (
            [
                "helm",
                "upgrade",
                "--install",
                release,
                chart_ref,
                "--namespace",
                resolved_namespace,
                "--create-namespace",
                "-f",
                str(output),
            ],
            repo_root,
        )

    if action == "logs":
        return (
            [
                "kubectl",
                "logs",
                "-n",
                resolved_namespace,
                "-l",
                f"moiraweave.io/workload={workload_name}",
                "--tail",
                "200",
            ],
            repo_root,
        )

    if action == "undeploy":
        return (
            [
                "kubectl",
                "delete",
                "deployment,service,persistentvolumeclaim",
                "-n",
                resolved_namespace,
                "-l",
                f"moiraweave.io/workload={workload_name}",
                "--ignore-not-found=true",
            ],
            repo_root,
        )

    _exit_with_error(
        f"Unsupported deployment controller action: {action}",
        hint="Supported controller actions are apply, logs, and undeploy.",
    )


def _run_deployment_controller_operation(
    operation: dict[str, Any],
    *,
    api_url: str,
    controller_id: str,
    repo_root: pathlib.Path,
    chart_ref: str,
    namespace: str | None,
    release: str,
) -> bool:
    operation_id = str(operation["operation_id"])
    _heartbeat_deployment_operation(
        api_url,
        operation_id,
        controller_id=controller_id,
    )
    command, cwd = _kubernetes_controller_command(
        operation,
        api_url=api_url,
        repo_root=repo_root,
        chart_ref=chart_ref,
        namespace=namespace,
        release=release,
    )
    _append_deployment_operation_event(
        api_url,
        operation_id,
        "controller.command",
        f"Running: {' '.join(command)}",
        data={"command": command},
    )
    returncode, output = _run_controller_command_with_heartbeat(
        command,
        cwd=cwd,
        api_url=api_url,
        operation_id=operation_id,
        controller_id=controller_id,
    )
    output_tail = output[-4000:]
    if output_tail:
        _append_deployment_operation_event(
            api_url,
            operation_id,
            "controller.output",
            output_tail,
            data={"returncode": returncode},
        )

    if returncode == 0:
        _complete_deployment_operation(
            api_url,
            operation_id,
            status="succeeded",
            message="Deployment controller operation completed successfully.",
            stdout_summary=output_tail,
            metadata={"command": command, "returncode": returncode},
        )
        return True

    _complete_deployment_operation(
        api_url,
        operation_id,
        status="failed",
        message="Deployment controller command failed.",
        stderr_summary=output_tail,
        metadata={"command": command, "returncode": returncode, "output": output_tail},
    )
    return False


def _run_deployment_controller_once(
    *,
    api_url: str,
    target: str,
    env: str,
    controller_id: str,
    limit: int,
    repo_root: pathlib.Path,
    chart_ref: str,
    namespace: str | None,
    release: str,
) -> tuple[int, int]:
    operations = _list_controller_operations(
        api_url, target=target, env=env, limit=limit
    )
    processed = 0
    failed = 0
    for operation in operations:
        operation_id = str(operation["operation_id"])
        ui.info(f"Claiming deployment operation {operation_id}")
        claimed = _claim_deployment_operation(
            api_url, operation_id, controller_id=controller_id
        )
        processed += 1
        if _run_deployment_controller_operation(
            claimed,
            api_url=api_url,
            controller_id=controller_id,
            repo_root=repo_root,
            chart_ref=chart_ref,
            namespace=namespace,
            release=release,
        ):
            ui.success(f"Deployment operation {operation_id} succeeded")
        else:
            failed += 1
            ui.error(f"Deployment operation {operation_id} failed")
    return processed, failed


@deploy_controller_app.command("run")
def deploy_controller_run(
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
    env: str = typer.Option("dev", "--env", help="Deployment environment to watch."),
    target: str = typer.Option(
        "kubernetes",
        "--target",
        help="Deployment target. Currently only kubernetes is executable.",
    ),
    controller_id: str | None = typer.Option(
        None,
        "--controller-id",
        help="Stable controller identity shown in deployment operation events.",
    ),
    limit: int = typer.Option(
        5,
        "--limit",
        min=1,
        max=50,
        help="Maximum queued operations to claim per poll.",
    ),
    watch: bool = typer.Option(
        False,
        "--watch",
        help="Keep polling instead of running one batch.",
    ),
    poll_interval: float = typer.Option(
        5.0,
        "--poll-interval",
        min=0.5,
        help="Seconds between polls when --watch is enabled.",
    ),
    chart_ref: str = typer.Option(
        "infra/helm/moiraweave",
        "--chart-ref",
        envvar="MOIRAWEAVE_HELM_CHART_REF",
        help="Helm chart path or OCI reference used for apply operations.",
    ),
    namespace: str | None = typer.Option(
        None,
        "--namespace",
        envvar="MOIRAWEAVE_K8S_NAMESPACE",
        help="Kubernetes namespace override for apply, logs, and undeploy.",
    ),
    release: str = typer.Option(
        "moiraweave",
        "--release",
        envvar="MOIRAWEAVE_HELM_RELEASE",
        help="Helm release name used for apply operations.",
    ),
    repo_root: pathlib.Path | None = typer.Option(
        None,
        "--repo-root",
        help="Workspace root for local manifests; defaults to current workspace or cwd.",
    ),
) -> None:
    """Claim and execute queued Kubernetes deployment operations."""
    if target != "kubernetes":
        _exit_with_error("Only target=kubernetes is supported by this controller.")
    resolved_repo_root = (
        repo_root or _maybe_repo_root() or pathlib.Path.cwd()
    ).resolve()
    resolved_controller_id = (controller_id or f"{socket.gethostname()}-{os.getpid()}")[
        :128
    ]

    total_processed = 0
    total_failed = 0
    while True:
        processed, failed = _run_deployment_controller_once(
            api_url=api_url,
            target=target,
            env=env,
            controller_id=resolved_controller_id,
            limit=limit,
            repo_root=resolved_repo_root,
            chart_ref=chart_ref,
            namespace=namespace,
            release=release,
        )
        total_processed += processed
        total_failed += failed
        if not watch:
            break
        if processed == 0:
            ui.info("No queued deployment operations found.")
        time.sleep(poll_interval)

    if total_processed == 0:
        ui.info("No queued deployment operations found.")
    if total_failed:
        raise typer.Exit(code=1)


@app.command()
def up(
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
    wait_timeout: int = typer.Option(
        90,
        "--wait-timeout",
        min=1,
        help="Seconds to wait for the API gateway.",
    ),
    ui_wait_timeout: int = typer.Option(
        45,
        "--ui-wait-timeout",
        min=0,
        help="Seconds to wait for the local UI; 0 disables this check.",
    ),
    demo_agent: bool = typer.Option(
        True,
        "--demo-agent/--no-demo-agent",
        help="Create a demo agent if the workspace has no workloads.",
    ),
    agent_template: str = typer.Option(
        "demo-agent",
        "--agent",
        help=(
            "Agent template to create on an empty workspace: demo-agent, hermes, "
            "openclaw, generic-http-agent, external-agent, or none."
        ),
    ),
    agent_name: str | None = typer.Option(
        None,
        "--agent-name",
        help="Name for the first-run agent workload.",
    ),
    agent_image: str | None = typer.Option(
        None,
        "--agent-image",
        help="Container image override for managed agent templates.",
    ),
    agent_endpoint: str | None = typer.Option(
        None,
        "--agent-endpoint",
        help="Base URL for external-agent first-run template.",
    ),
    agent_port: int | None = typer.Option(
        None,
        "--agent-port",
        min=1,
        help="Runtime port override for managed agent templates.",
    ),
    register: bool = typer.Option(
        True,
        "--register/--no-register",
        help="Register workloads and deployment records after startup.",
    ),
    skip_doctor: bool = typer.Option(
        False,
        "--skip-doctor",
        help="Skip local diagnostics before Docker starts.",
    ),
) -> None:
    """Initialize, start, and register a local MoiraWeave stack."""
    try:
        repo_root = find_repo_root()
    except FileNotFoundError:
        ProjectInitCommand(repo_root=pathlib.Path.cwd()).execute(
            action="init",
            non_interactive=True,
            project_name=None,
            registry=None,
        )
        repo_root = pathlib.Path.cwd().resolve()

    manifests = _load_workload_manifests(repo_root)
    selected_agent = agent_template if isinstance(agent_template, str) else "demo-agent"
    template_agent_name = agent_name if isinstance(agent_name, str) else None
    template_agent_image = agent_image if isinstance(agent_image, str) else None
    template_agent_endpoint = (
        agent_endpoint if isinstance(agent_endpoint, str) else None
    )
    template_agent_port = agent_port if isinstance(agent_port, int) else None
    if not demo_agent and selected_agent.strip().lower() in {"demo", "demo-agent"}:
        selected_agent = "none"
    if not manifests:
        agent_path = _ensure_agent_template(
            repo_root,
            selected_agent,
            name=template_agent_name,
            image=template_agent_image,
            endpoint=template_agent_endpoint,
            port=template_agent_port,
        )
        if agent_path is not None:
            ui.success(f"Created agent workload: {agent_path.relative_to(repo_root)}")
        else:
            ui.warning(
                "No workloads found. Starting the platform without managed workloads."
            )
        manifests = _load_workload_manifests(repo_root)

    deploy_root = _deploy_root(repo_root)
    deploy_root.mkdir(parents=True, exist_ok=True)
    output = deploy_root / "docker-compose.workloads.yml"
    output.write_text(
        yaml.safe_dump(
            _render_local_workload_compose(manifests, repo_root),
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    ui.success(f"Generated {output.relative_to(repo_root)}")

    if not skip_doctor:
        report = _doctor_report(target="local", api_url=api_url, repo_root=repo_root)
        _print_doctor_report(report)
        if _doctor_has_errors(report):
            _exit_with_error(
                "Local diagnostics failed; Docker was not started.",
                hint=(
                    "Fix the ERROR checks above, or rerun with --skip-doctor "
                    "if you know the stack is safe."
                ),
            )

    ui.info("Starting local platform, UI, and workload services...")
    compose_output = _run_command(
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
            str(output),
            "up",
            "-d",
        ],
        cwd=repo_root,
    )
    if compose_output:
        ui.info(compose_output)

    if not _wait_for_api_ready(api_url, wait_timeout):
        _exit_with_error(
            f"API gateway did not become ready within {wait_timeout}s",
            hint="Run `docker compose logs api-gateway worker`.",
        )

    ui_port = _env_int(repo_root, "MOIRAWEAVE_UI_PORT", 3000)
    ui_url = f"http://localhost:{ui_port}/agents"
    if ui_wait_timeout > 0:
        ui_ready, ui_message = _wait_for_url_reachable(ui_url, ui_wait_timeout)
        if ui_ready:
            ui.success(f"UI is reachable at {ui_url} ({ui_message})")
        else:
            ui.warning(
                f"UI did not respond within {ui_wait_timeout}s ({ui_message}). "
                "The stack is still running; inspect `docker compose logs ui`."
            )

    if register:
        previous_token = os.environ.get("MOIRA_TOKEN")
        token = previous_token or _dev_login_token(api_url)
        if token:
            _store_cli_token(repo_root, api_url, token)
            os.environ["MOIRA_TOKEN"] = token
            _register_workload_deployments(
                manifests,
                target="local",
                env="local",
                status="running",
                api_url=api_url,
            )
            if previous_token is None:
                os.environ.pop("MOIRA_TOKEN", None)
        else:
            ui.warning(
                "Stack is running, but automatic registration could not log in. "
                "Set MOIRA_TOKEN or run `moira deploy local --register`."
            )

    chat_agent = _first_agent_workload_name(manifests)
    api_suffix = "" if api_url == DEFAULT_API_URL else f" --api-url {api_url}"
    ui.next_steps(
        "MoiraWeave is up",
        [
            (1, f"open http://localhost:{ui_port}/agents", "Open the agent console"),
            (2, "sign in as admin / demo-password", "Use local dev credentials"),
            (
                3,
                f'moira agent chat {chat_agent} "hello from the CLI" --watch{api_suffix}',
                "Run a terminal smoke test",
            ),
            (
                4,
                "docker compose logs api-gateway worker",
                "Inspect platform logs if anything looks unhealthy",
            ),
        ],
    )


@app.command()
def init(
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
        help="Skip prompts and use defaults.",
    ),
    project_name: str = typer.Option(
        None,
        "--name",
        help="Project name (defaults to current directory name).",
    ),
    registry: str = typer.Option(
        None,
        "--registry",
        help="OCI image registry (e.g., ghcr.io/myorg).",
    ),
) -> None:
    """Initialize a new MoiraWeave workspace.

    Creates moiraweave.yaml, .env, and directory structure under .moiraweave/
    to keep your workspace clean and organized.

    Examples:
        moira init
        moira init --name my-project --registry ghcr.io/myorg
        moira init --non-interactive
    """
    cmd = ProjectInitCommand(repo_root=pathlib.Path.cwd())
    cmd.execute(
        action="init",
        non_interactive=non_interactive,
        project_name=project_name,
        registry=registry,
    )


def _version_callback(value: bool) -> None:
    if value:
        version = (
            (pathlib.Path(__file__).parent.parent / "version.txt").read_text().strip()
        )
        console.print(f"MoiraWeave CLI version {version}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """Main entrypoint for the CLI."""
    del ctx, version
