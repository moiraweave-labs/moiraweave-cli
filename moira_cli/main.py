"""Typer entrypoint for the MoiraWeave CLI."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import time
from typing import Any, NoReturn

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

console = Console()
ui = get_ui()
app = typer.Typer(
    help="MoiraWeave CLI — deploy and operate AI workloads",
    no_args_is_help=True,
)
workload_app = typer.Typer(help="Manage workloads")
run_app = typer.Typer(help="Submit, watch, and cancel runs")
agent_app = typer.Typer(help="Manage agent sessions")
agent_session_app = typer.Typer(help="Create and message agent sessions")
deploy_app = typer.Typer(help="Generate or apply deployment assets")
demo_app = typer.Typer(help="Create runnable demo workloads")


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
agent_app.add_typer(agent_session_app, name="session")


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
    method: str, url: str, payload: dict[str, Any] | None = None
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
    token = os.environ.get("MOIRA_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.request(method, url, json=payload, headers=headers)
            response.raise_for_status()
            body = response.json()
            return body if isinstance(body, dict) else {"data": body}
    except Exception as exc:
        _exit_with_error(f"HTTP request failed for {url}: {exc}")


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
                "messagePath": "/message",
                "statusPath": "/health",
                "artifactsPath": "/artifacts",
                "exposedChannels": ["ui", "api", "webhook"],
                "capabilities": ["demo", "chat"],
                "dispatchTimeoutSeconds": 5,
                "pollIntervalSeconds": 1,
            },
            "command": ["python", "-u", "-c"],
            "args": [_DEMO_AGENT_SCRIPT],
        },
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
                "env": {
                    "API_SERVER_ENABLED": "true",
                    "API_SERVER_HOST": "0.0.0.0",
                    "API_SERVER_PORT": str(runtime_port),
                },
                "secrets": ["OPENAI_API_KEY", "HERMES_API_SERVER_KEY"],
                "agent": {
                    "adapter": "hermes",
                    "requiredSecrets": ["OPENAI_API_KEY"],
                    "workspaceMount": "/workspace",
                    "authTokenEnv": "HERMES_API_SERVER_KEY",
                    "model": "hermes-agent",
                    "exposedChannels": ["ui", "api"],
                    "capabilities": ["chat", "tools", "long-running"],
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
                "secrets": ["OPENCLAW_GATEWAY_TOKEN"],
                "agent": {
                    "adapter": "openclaw",
                    "agentId": "main",
                    "authTokenEnv": "OPENCLAW_GATEWAY_TOKEN",
                    "workspaceMount": "/workspace",
                    "exposedChannels": ["ui", "api"],
                    "capabilities": ["browser", "tools", "long-running"],
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
                    "messagePath": "/message",
                    "statusPath": "/health",
                    "cancelPath": "/cancel",
                    "artifactsPath": "/artifacts",
                    "exposedChannels": ["ui", "api"],
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
                    "exposedChannels": ["ui", "api"],
                },
            },
        }

    _exit_with_error(
        f"Unknown agent template: {template}",
        hint="Use demo-agent, hermes, openclaw, generic-http-agent, external-agent, or none.",
    )


def _dotenv_keys(repo_root: pathlib.Path) -> set[str]:
    path = repo_root / ".env"
    if not path.exists():
        return set()
    keys: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key.strip() and value.strip():
            keys.add(key.strip())
    return keys


def _missing_required_env(
    manifests: list[dict[str, Any]],
    repo_root: pathlib.Path,
) -> list[str]:
    available = set(os.environ) | _dotenv_keys(repo_root)
    required: set[str] = set()
    for manifest in manifests:
        spec = manifest.get("spec", {})
        if not isinstance(spec, dict):
            continue
        required.update(str(secret) for secret in spec.get("secrets") or [])
        agent = spec.get("agent") or {}
        if isinstance(agent, dict):
            required.update(
                str(secret) for secret in agent.get("requiredSecrets") or []
            )
            auth_token_env = agent.get("authTokenEnv")
            if auth_token_env:
                required.add(str(auth_token_env))
    return sorted(secret for secret in required if secret not in available)


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
        if isinstance(persistence, dict) and persistence.get("enabled"):
            mount_path = persistence.get("mountPath")
            if mount_path:
                host_path = artifacts_root / name
                host_path.mkdir(parents=True, exist_ok=True)
                service["volumes"] = [f"{host_path}:{mount_path}"]
        if isinstance(agent, dict) and agent.get("workspaceMount"):
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
                "status": status,
                "endpoint": _deployment_endpoint(manifest),
                "metadata": {
                    "service_name": _deployment_service_name(manifest),
                    "deployment_mode": _deployment_mode(manifest),
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
            if response.status_code < 500:
                return True
        except httpx.HTTPError:
            time.sleep(1)
            continue
        time.sleep(1)
    return False


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
            "requiredSecrets": list(secret),
            "exposedChannels": list(dict.fromkeys(channel)),
            "externalOwnedChannels": list(dict.fromkeys(external_channel)),
            "workspaceMount": workspace_mount,
            "authTokenEnv": auth_token_env,
            "agentId": agent_id,
            "model": model,
            "instructions": instructions,
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


@agent_session_app.command("create")
def agent_session_create(
    agent: str = typer.Argument(..., help="Agent workload name."),
    metadata: str = typer.Option("{}", "--metadata", help="Metadata JSON."),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Create an agent session."""
    response = _request_json(
        "POST",
        f"{api_url}/v1/agents/{agent}/sessions",
        {"metadata": _parse_json_input(metadata)},
    )
    console.print(Syntax(json.dumps(response, indent=2), "json"))


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
    response = _request_json(
        "POST",
        f"{api_url}/v1/agents/{agent}/sessions/{session_id}/messages",
        {"message": message, "context": _parse_json_input(context)},
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
        config = load_moiraweave_config(repo_root)
        target = config.environments.get(env)
        namespace = target.namespace if target and target.namespace else "moiraweave"
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
            status="applied" if apply else "generated",
            api_url=api_url,
        )


@app.command()
def up(
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
    wait_timeout: int = typer.Option(
        90,
        "--wait-timeout",
        min=1,
        help="Seconds to wait for the API gateway.",
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

    missing_env = _missing_required_env(manifests, repo_root)
    if missing_env:
        _exit_with_error(
            "Missing required environment variables: " + ", ".join(missing_env),
            hint=(
                "Add them to .env or export them before running `moira up`. "
                "Use `moira up --agent demo-agent` for a no-secret first run."
            ),
        )

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

    if register:
        previous_token = os.environ.get("MOIRA_TOKEN")
        token = previous_token or _dev_login_token(api_url)
        if token:
            os.environ["MOIRA_TOKEN"] = token
            _register_workload_deployments(
                manifests,
                target="local",
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

    ui.next_steps(
        "MoiraWeave is up",
        [
            (1, "open http://localhost:3000", "Open the Ops dashboard"),
            (2, "sign in as admin / demo-password", "Use local dev credentials"),
            (3, "Agents -> New Session", "Chat with the demo agent"),
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
