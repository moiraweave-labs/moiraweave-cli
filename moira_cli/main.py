"""Typer entrypoint for the MoiraWeave CLI."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import time
from typing import Any, NoReturn
from urllib.parse import urlparse

import httpx
import questionary
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
_PLATFORM_SERVICES = frozenset(
    {"api-gateway", "worker", "postgres", "redis", "qdrant", "ui"}
)
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
task_app = typer.Typer(help="Manage tasks")
step_app = typer.Typer(help="Manage steps")

pipeline_app = typer.Typer(help="Manage pipelines")
models_app = typer.Typer(help="Manage model cache and readiness")
job_app = typer.Typer(help="Inspect detached jobs")


# Register 'flow' command
app.add_typer(
    flow_command_module.app,
    name="flow",
    help="Show workspace as a visual dependency tree",
)
app.add_typer(workload_app, name="workload")
app.add_typer(run_app, name="run")
app.add_typer(agent_app, name="agent")
app.add_typer(deploy_app, name="deploy")
agent_app.add_typer(agent_session_app, name="session")


def _repo_root() -> pathlib.Path:
    """Resolve the current repository root.

    :returns: Nearest parent directory containing `tasks/` and `steps/`.
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


def _default_dirs(
    repo_root: pathlib.Path,
) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    """Return tasks/steps/pipelines directories.

    :param repo_root: Repository root.
    :returns: Tuple of `(tasks_root, steps_root, pipelines_root)`.
    """
    try:
        config = load_moiraweave_config(repo_root)
        return (
            repo_root / config.tasks_dir,
            repo_root / config.steps_dir,
            repo_root / config.pipelines_dir,
        )
    except Exception:
        return (repo_root / "tasks", repo_root / "steps", repo_root / "pipelines")


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


def _required_inputs_for_task(tasks_root: pathlib.Path, task_name: str) -> set[str]:
    """Get required input tensor names for a task.

    :param tasks_root: Task root directory.
    :param task_name: Task identifier.
    :returns: Set of required input tensor names.
    """
    schema_path = tasks_root / task_name / "schema.json"
    if not schema_path.exists():
        return set()

    raw = _read_json_file(schema_path)
    inputs = raw.get("inputs", [])
    return {str(item["name"]) for item in inputs if item.get("required", False)}


def _outputs_for_task(tasks_root: pathlib.Path, task_name: str) -> set[str]:
    """Get output tensor names for a task.

    :param tasks_root: Task root directory.
    :param task_name: Task identifier.
    :returns: Set of output tensor names.
    """
    schema_path = tasks_root / task_name / "schema.json"
    if not schema_path.exists():
        return set()

    raw = _read_json_file(schema_path)
    outputs = raw.get("outputs", [])
    return {str(item["name"]) for item in outputs}


def _infer_step_endpoint(step_name: str) -> str:
    """Infer a default local endpoint for a step.

    :param step_name: Step name.
    :returns: URL base.
    """
    return f"http://{step_name}:8000"


def _pipeline_file(repo_root: pathlib.Path, name: str) -> pathlib.Path:
    """Return pipeline.yaml path for a pipeline name.

    :param repo_root: Repository root.
    :param name: Pipeline directory name.
    :returns: Absolute path to pipeline definition.
    """
    _, _, pipelines_root = _default_dirs(repo_root)
    return pipelines_root / name / "pipeline.yaml"


def _pipeline_step_defs(repo_root: pathlib.Path, name: str) -> list[dict[str, Any]]:
    """Load pipeline step definitions.

    :param repo_root: Repository root.
    :param name: Pipeline directory name.
    :returns: List of step dictionaries.
    """
    pipeline_path = _pipeline_file(repo_root, name)
    if not pipeline_path.exists():
        _exit_with_error(f"Pipeline not found: {name}")
    raw = _load_yaml_file(pipeline_path)
    return list(raw.get("steps", []))


def _write_compose_override(
    repo_root: pathlib.Path,
    step_defs: list[dict[str, Any]],
) -> None:
    """Write docker-compose.override.yml for user step services in a pipeline.

    Skips platform services (api-gateway, worker, redis, qdrant).
    Resolves each step image from step.yaml ``image_uri`` or VERSION + registry.

    :param repo_root: Workspace root.
    :param step_defs: Step definitions loaded from pipeline.yaml.
    """
    _, steps_root, _ = _default_dirs(repo_root)
    try:
        config = load_moiraweave_config(repo_root)
        registry = config.registry.rstrip("/")
    except Exception:
        registry = "ghcr.io/myorg"

    services: dict[str, dict[str, Any]] = {}
    for step in step_defs:
        parsed = urlparse(str(step.get("url", "")))
        hostname = parsed.hostname
        if not hostname or hostname in _PLATFORM_SERVICES or hostname in services:
            continue

        step_dir = steps_root / hostname
        image_uri: str | None = None

        step_yaml_path = step_dir / "step.yaml"
        if step_yaml_path.exists():
            step_meta = _load_yaml_file(step_yaml_path)
            image_uri = step_meta.get("image_uri") or step_meta.get("image")

        if not image_uri:
            version_file = step_dir / "VERSION"
            if version_file.exists():
                version = version_file.read_text(encoding="utf-8").strip()
                image_uri = f"{registry}/{hostname}:v{version}"
            else:
                ui.warning(
                    f"Cannot resolve image for step '{hostname}' — "
                    "skipping from override. Run 'moira step build {hostname}' first."
                )
                continue

        services[hostname] = {"image": image_uri}

    override_path = repo_root / "docker-compose.override.yml"
    if services:
        header = (
            "# Generated by `moira pipeline dev` — do not edit manually.\n"
            "# Recreated each time you run `moira pipeline dev <name>`.\n"
        )
        override_path.write_text(
            header + yaml.dump({"services": services}, default_flow_style=False),
            encoding="utf-8",
        )
    elif override_path.exists():
        override_path.unlink()


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
        for secret in spec.get("secrets") or []:
            service["environment"][str(secret)] = f"${{{secret}:?set {secret}}}"
        agent = spec.get("agent") or {}
        if isinstance(agent, dict):
            for secret in agent.get("requiredSecrets") or []:
                service["environment"][str(secret)] = f"${{{secret}:?set {secret}}}"

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

    return {"services": services}


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
        help="Exposed agent interaction channel.",
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


def _bump_semver(version: str, kind: str) -> str:
    """Bump semantic version string.

    :param version: Current version (`MAJOR.MINOR.PATCH`).
    :param kind: One of `patch`, `minor`, `major`.
    :returns: Bumped version.
    """
    parts = version.strip().split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        _exit_with_error(f"Invalid semver version: {version}")
    major, minor, patch = map(int, parts)
    if kind == "patch":
        patch += 1
    elif kind == "minor":
        minor += 1
        patch = 0
    else:
        major += 1
        minor = 0
        patch = 0
    return f"{major}.{minor}.{patch}"


def _catalog_raw_url_from_uri(uri: str) -> str | None:
    """Resolve a catalog URI to a raw catalog URL when possible.

    :param uri: Catalog source URI from config.
    :returns: HTTP URL for catalog content or ``None`` if unsupported.
    """
    parsed = urlparse(uri)
    if parsed.scheme in {"http", "https"} and parsed.path.endswith(
        (".yaml", ".yml", ".json")
    ):
        return uri

    if parsed.scheme in {"http", "https"} and parsed.netloc == "github.com":
        parts = [segment for segment in parsed.path.strip("/").split("/") if segment]
        if len(parts) >= 2:
            owner, repo = parts[0], parts[1].replace(".git", "")
            return f"https://raw.githubusercontent.com/{owner}/{repo}/main/catalog.yaml"

    return None


def _load_catalog_document(repo_root: pathlib.Path) -> tuple[str, dict[str, Any]]:
    """Load the first enabled catalog from local path or remote URI.

    :param repo_root: Repository root.
    :returns: Tuple of catalog name and parsed catalog payload.
    :raises typer.Exit: If no enabled catalog can be loaded.
    """
    config = load_moiraweave_config(repo_root)
    enabled_catalogs = [
        (name, catalog) for name, catalog in config.catalogs.items() if catalog.enabled
    ]
    if not enabled_catalogs:
        _exit_with_error("No enabled catalogs found in moiraweave.yaml")

    catalog_name, source = enabled_catalogs[0]
    local_catalog = repo_root / "catalog.yaml"
    if local_catalog.exists():
        return catalog_name, _load_yaml_file(local_catalog)

    source_uri = source.uri
    parsed = urlparse(source_uri)
    if parsed.scheme in {"", "file"}:
        local_path = pathlib.Path(parsed.path or source_uri)
        if not local_path.is_absolute():
            local_path = (repo_root / local_path).resolve()
        if local_path.is_file():
            if local_path.suffix.lower() == ".json":
                return catalog_name, _read_json_file(local_path)
            return catalog_name, _load_yaml_file(local_path)

    raw_url = _catalog_raw_url_from_uri(source_uri)
    if raw_url is None:
        _exit_with_error(
            f"Unsupported catalog URI: {source_uri}. Use file path or GitHub URL."
        )
    assert raw_url is not None

    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.get(raw_url)
            response.raise_for_status()
            if raw_url.endswith(".json"):
                data = response.json()
            else:
                data = yaml.safe_load(response.text)
            return catalog_name, dict(data or {})
    except Exception as exc:  # pragma: no cover - network failures
        _exit_with_error(f"Failed to load catalog from {raw_url}: {exc}")


def _semver_key(version: str) -> tuple[int, int, int]:
    """Return a sortable key for ``MAJOR.MINOR.PATCH`` versions.

    :param version: Version string.
    :returns: Numeric tuple for sorting.
    """
    parts = version.strip().split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return (0, 0, 0)
    return tuple(int(part) for part in parts)  # type: ignore[return-value]


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


@task_app.command("list")
def task_list() -> None:
    """List all registered tasks from tasks/*/schema.json."""
    from moira_cli.commands.task import TaskCommand
    from moira_cli.presenters.task import TaskPresenter

    repo_root = _repo_root()
    cmd = TaskCommand(repo_root)
    result = cmd.execute(action="list")

    if result.get("status") == "success":
        presenter = TaskPresenter()
        presenter.present_list(result.get("tasks", []))
    else:
        ui.error(result.get("message", "Failed to list tasks"))


@task_app.command("show")
def task_show(name: str = typer.Argument(..., help="Task name.")) -> None:
    """Show full schema and compatible steps for a task.

    Examples:
        moira task show text-embed
    """
    from moira_cli.commands.task import TaskCommand
    from moira_cli.presenters.task import TaskPresenter

    repo_root = _repo_root()
    cmd = TaskCommand(repo_root)
    result = cmd.execute(action="show", task_name=name)

    if result.get("status") == "success":
        presenter = TaskPresenter()
        presenter.present_show(
            name,
            result.get("schema", {}),
            result.get("inputs", []),
            result.get("outputs", []),
        )
    else:
        ui.error(
            result.get("message", "Failed to show task"),
            hint="Run 'moira task list' to see available tasks",
        )


@task_app.command("new")
def task_new(
    name: str = typer.Argument(..., help="New task name."),
    non_interactive: bool = typer.Option(False, help="Use defaults without prompts."),
) -> None:
    """Create a new task schema under tasks/<name>/schema.json.

    :param name: New task name.
    :param non_interactive: Disable prompts and use defaults.
    """
    from moira_cli.commands.task import TaskCommand
    from moira_cli.presenters.task import TaskPresenter

    repo_root = _repo_root()
    description = f"Task contract for {name}"
    input_name = "input"
    output_name = "output"

    if not non_interactive:
        description = (
            questionary.text("Task description", default=description).ask()
            or description
        )
        input_name = (
            questionary.text("Primary input tensor name", default=input_name).ask()
            or input_name
        )
        output_name = (
            questionary.text("Primary output tensor name", default=output_name).ask()
            or output_name
        )

    cmd = TaskCommand(repo_root)
    result = cmd.execute(
        action="new",
        task_name=name,
        description=description,
    )

    if result.get("status") == "success":
        presenter = TaskPresenter()
        presenter.present_new(name, result.get("created", {}))
    else:
        ui.error(result.get("message", "Failed to create task"))


@step_app.command("list")
def step_list() -> None:
    """List all steps discovered from steps/*/step.yaml."""
    from moira_cli.commands.step import StepCommand
    from moira_cli.presenters.step import StepPresenter

    repo_root = _repo_root()
    cmd = StepCommand(repo_root)
    result = cmd.execute(action="list")

    if result.get("status") == "success":
        presenter = StepPresenter()
        presenter.present_list(result.get("steps", []))
    else:
        ui.error(result.get("message", "Failed to list steps"))


@step_app.command("new")
def step_new(
    task: str = typer.Argument(..., help="Task name."),
    implementation: str = typer.Argument(..., help="Implementation suffix."),
) -> None:
    """Scaffold a new step package from task schema.

    Examples:
        moira step new text-embed fastembed
        moira step new image-search clip
    """
    repo_root = _repo_root()
    tasks_root, steps_root, _ = _default_dirs(repo_root)
    schema_path = tasks_root / task / "schema.json"
    if not schema_path.exists():
        _exit_with_error(
            f"Task schema not found: {schema_path}",
            hint=f"Run 'moira task new {task}' first",
        )

    schema = _read_json_file(schema_path)
    step_name = f"{task}-{implementation}"
    step_root = steps_root / step_name
    app_root = step_root / "app"
    tests_root = step_root / "tests"

    if step_root.exists():
        confirmed = questionary.confirm(
            f"Step '{step_name}' already exists. Overwrite?",
            default=False,
        ).ask()
        if not confirmed:
            ui.info("Operation cancelled.")
            return
        # Safe removal of existing directory
        import shutil

        shutil.rmtree(step_root)

    app_root.mkdir(parents=True, exist_ok=True)
    tests_root.mkdir(parents=True, exist_ok=True)

    input_name = str(schema.get("inputs", [{}])[0].get("name", "input"))
    output_name = str(schema.get("outputs", [{}])[0].get("name", "output"))

    (app_root / "__init__.py").write_text("", encoding="utf-8")
    (app_root / "config.py").write_text(
        "from pydantic_settings import BaseSettings, SettingsConfigDict\n\n\n"
        "class Settings(BaseSettings):\n"
        '    """Runtime settings for the scaffolded step.\n\n'
        "    :param model_config: Prefix for environment variables.\n"
        '    """\n\n'
        f'    model_config = SettingsConfigDict(env_prefix="{task.upper().replace("-", "_")}_STEP_")\n',
        encoding="utf-8",
    )
    (app_root / "step.py").write_text(
        "from __future__ import annotations\n\n"
        "from typing import TYPE_CHECKING\n\n"
        "from moiraweave_step_sdk.base import BaseStep\n"
        "from moiraweave_step_sdk.models import InferRequest, InferResponse, MetadataTensor, Tensor\n\n"
        "if TYPE_CHECKING:\n"
        "    from app.config import Settings\n\n\n"
        f"class {task.title().replace('-', '').replace('_', '')}{implementation.title().replace('-', '').replace('_', '')}Step(BaseStep):\n"
        '    """Scaffolded step implementation."""\n\n'
        "    def __init__(self, settings: Settings) -> None:\n"
        "        self._settings = settings\n\n"
        "    @property\n"
        "    def name(self) -> str:\n"
        f'        return "{step_name}"\n\n'
        "    @property\n"
        "    def version(self) -> str:\n"
        '        return "1"\n\n'
        "    @property\n"
        "    def task(self) -> str:\n"
        f'        return "{task}"\n\n'
        "    @property\n"
        "    def implementation(self) -> str:\n"
        f'        return "{implementation}"\n\n'
        "    @property\n"
        "    def inputs(self) -> list[MetadataTensor]:\n"
        f'        return [MetadataTensor(name="{input_name}", datatype="BYTES", shape=[1])]\n\n'
        "    @property\n"
        "    def outputs(self) -> list[MetadataTensor]:\n"
        f'        return [MetadataTensor(name="{output_name}", datatype="BYTES", shape=[1])]\n\n'
        "    async def predict(self, request: InferRequest) -> InferResponse:\n"
        '        """Implement model inference."""\n'
        '        raise NotImplementedError("Implement predict() for this step")\n',
        encoding="utf-8",
    )
    (app_root / "main.py").write_text(
        "import uvicorn\n"
        "from fastapi import FastAPI\n\n"
        "from app.config import Settings\n"
        "from app.step import "
        f"{task.title().replace('-', '').replace('_', '')}{implementation.title().replace('-', '').replace('_', '')}Step\n\n\n"
        "def create_app() -> FastAPI:\n"
        '    """Create FastAPI app for this step.\n\n'
        "    :returns: FastAPI instance exposing KServe V2 endpoints.\n"
        '    """\n'
        "    settings = Settings()\n"
        "    step = "
        f"{task.title().replace('-', '').replace('_', '')}{implementation.title().replace('-', '').replace('_', '')}Step(settings)\n"
        "    return step.build_app()\n\n\n"
        "app = create_app()\n\n"
        'if __name__ == "__main__":\n'
        '    uvicorn.run("app.main:app", host="0.0.0.0", port=8080, log_level="info")\n',
        encoding="utf-8",
    )
    class_name = (
        f"{task.title().replace('-', '').replace('_', '')}"
        f"{implementation.title().replace('-', '').replace('_', '')}Step"
    )
    (tests_root / "__init__.py").write_text("", encoding="utf-8")
    (tests_root / "conftest.py").write_text(
        '"""Shared fixtures for the scaffolded step tests."""\n\n'
        "from __future__ import annotations\n\n"
        "import pathlib\n"
        "import sys\n"
        "from unittest.mock import MagicMock\n\n"
        "import pytest\n\n"
        "_STEP_ROOT = str(pathlib.Path(__file__).resolve().parents[1])\n"
        "for _k in list(sys.modules):\n"
        '    if _k == "app" or _k.startswith("app."):\n'
        "        del sys.modules[_k]\n"
        "if _STEP_ROOT not in sys.path:\n"
        "    sys.path.insert(0, _STEP_ROOT)\n\n\n"
        "@pytest.fixture(autouse=True)\n"
        "def _restore_step_app() -> None:\n"
        '    """Reload app modules before each test to avoid cross-test pollution."""\n'
        "    if not sys.path or sys.path[0] != _STEP_ROOT:\n"
        "        sys.path.insert(0, _STEP_ROOT)\n"
        "    for _k in list(sys.modules):\n"
        '        if _k == "app" or _k.startswith("app."):\n'
        "            del sys.modules[_k]\n\n\n"
        "@pytest.fixture()\n"
        "def mock_model() -> MagicMock:\n"
        '    """Return a generic mock model ready to be patched into the step."""\n'
        "    return MagicMock()\n\n\n"
        "@pytest.fixture()\n"
        f"def step(mock_model: MagicMock):  # type: ignore[no-untyped-def]\n"
        f'    """Return a {class_name} with a mocked model dependency."""\n'
        "    from app.config import Settings\n"
        f"    from app.step import {class_name}\n\n"
        f"    return {class_name}(Settings())\n",
        encoding="utf-8",
    )
    (tests_root / "test_step.py").write_text(
        """"\"\"\"Tests for the scaffolded step.\"\"\"

import pytest


def test_scaffold_placeholder() -> None:
    # Replace with real assertions against the step fixture once predict() is implemented.
    assert True
""",
        encoding="utf-8",
    )
    (step_root / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    (step_root / "step.yaml").write_text(
        yaml.safe_dump(
            {
                "name": step_name,
                "version": "1",
                "task": task,
                "description": f"Scaffolded step for task {task}",
                "port": 8080,
                "inputs": schema.get("inputs", []),
                "outputs": schema.get("outputs", []),
                "env": {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (step_root / "pyproject.toml").write_text(
        "[project]\n"
        f'name = "step-{step_name}"\n'
        'version = "0.1.0"\n'
        f'description = "MoiraWeave step: {task} via {implementation}"\n'
        'requires-python = ">=3.13"\n'
        "dependencies = [\n"
        '  "moiraweave-step-sdk>=0.1.0",\n'
        '  "pydantic-settings>=2.0",\n'
        '  "uvicorn[standard]>=0.30",\n'
        "]\n\n"
        "[tool.uv]\npackage = false\n",
        encoding="utf-8",
    )
    (step_root / "Dockerfile").write_text(
        "FROM python:3.13-slim\n\n"
        "WORKDIR /app\n"
        "COPY --from=ghcr.io/astral-sh/uv:0.4.30 /uv /usr/local/bin/uv\n"
        "ENV UV_SYSTEM_PYTHON=1\n"
        "COPY pyproject.toml ./\n"
        "RUN uv pip install --no-cache -r pyproject.toml\n"
        "COPY app/ ./app/\n"
        "EXPOSE 8080\n"
        'CMD ["python", "-m", "app.main"]\n',
        encoding="utf-8",
    )

    ui.success(f"Step scaffolded: {step_name}")
    ui.path("Location", str(step_root))
    _, steps_root_display, _ = _default_dirs(repo_root)
    ui.next_steps(
        "Next steps",
        [
            (1, f"cd {steps_root_display / step_name}", "Enter the step directory"),
            (2, "implement predict() in app/step.py", "Add your logic"),
            (3, "moira step test " + step_name, "Run tests"),
        ],
    )


@step_app.command("test")
def step_test(name: str = typer.Argument(..., help="Step directory name.")) -> None:
    """Run pytest for one step.

    :param name: Step directory name.
    """
    from moira_cli.commands.step import StepCommand
    from moira_cli.presenters.step import StepPresenter

    repo_root = _repo_root()
    cmd = StepCommand(repo_root)
    result = cmd.execute(action="test", step_name=name)

    if result.get("status") == "success":
        presenter = StepPresenter()
        presenter.present_test_result(name, result.get("test_result", {}))
    else:
        ui.error(result.get("message", "Failed to test step"))


@step_app.command("build")
def step_build(name: str = typer.Argument(..., help="Step directory name.")) -> None:
    """Build step container image locally.

    Examples:
        moira step build text-embed-fastembed
    """
    repo_root = _repo_root()
    _, steps_root, _ = _default_dirs(repo_root)
    step_root = steps_root / name
    version_file = step_root / "VERSION"
    if not version_file.exists():
        _exit_with_error(f"VERSION not found for step: {name}")
    version = version_file.read_text(encoding="utf-8").strip()

    config = load_moiraweave_config(repo_root)
    image = f"{config.registry.rstrip('/')}/{name}:v{version}"

    with Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("{task.description}", style="dim"),
        transient=True,
    ) as progress:
        progress.add_task(f"Building {image}...", total=None)
        try:
            _run_command(
                [
                    "docker",
                    "buildx",
                    "build",
                    "--load",
                    "-t",
                    image,
                    "-f",
                    str(step_root / "Dockerfile"),
                    str(step_root),
                ],
                cwd=repo_root,
            )
            progress.stop()
        except typer.Exit:
            progress.stop()
            raise
    ui.success(f"Built image: {image}")


@step_app.command("push")
def step_push(
    name: str = typer.Argument(..., help="Step directory name."),
    bump: str | None = typer.Option(
        None,
        "--bump",
        help="Optional semver bump before push (patch|minor|major).",
    ),
) -> None:
    """Push step image to registry and optionally bump VERSION.

    Examples:
        moira step push text-embed-fastembed
        moira step push text-embed-fastembed --bump patch
    """
    from moira_cli.commands.step import StepCommand
    from moira_cli.presenters.step import StepPresenter

    repo_root = _repo_root()
    with Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("{task.description}", style="dim"),
        transient=True,
    ) as progress:
        progress.add_task(f"Pushing {name}...", total=None)
        try:
            cmd = StepCommand(repo_root)
            result = cmd.execute(action="push", step_name=name, bump=bump)
            progress.stop()
        except typer.Exit:
            progress.stop()
            raise
    if result.get("status") == "success":
        presenter = StepPresenter()
        push_result = result.get("push_result", {})
        presenter.present_push_result(name, push_result)
    else:
        ui.error(result.get("message", "Failed to push step"))


@step_app.command("show")
def step_show(
    name: str = typer.Argument(..., help="Step name."),
    url: str | None = typer.Option(
        None, help="Step URL base (default: inferred host)."
    ),
) -> None:
    """Fetch live metadata from a running step endpoint.

    :param name: Step name.
    :param url: Optional base URL.
    """
    base = url or _infer_step_endpoint(name)
    data = _request_json("GET", f"{base}/v2/models/{name}")
    ui.info("Step metadata:")
    console.print(Syntax(json.dumps(data, indent=2), "json"))


@step_app.command("add")
def step_add(
    step_ref: str = typer.Option(
        ..., "--from-catalog", help="Step reference (format: step-name[@version])."
    ),
) -> None:
    """Add an official step from the catalog to your workspace.

    Materializes a reference to an official step as a local entry.

    Examples:
        moira step add --from-catalog text-embed-fastembed
        moira step add --from-catalog text-embed-fastembed@1.0.0
    """
    repo_root = _repo_root()
    config = load_moiraweave_config(repo_root)

    # Parse step reference
    if "@" in step_ref:
        step_name, step_version = step_ref.rsplit("@", 1)
    else:
        step_name = step_ref
        step_version = "latest"

    ui.header(f"Add Official Step: {step_name}")

    catalog_name, catalog = _load_catalog_document(repo_root)
    catalog_steps = list(catalog.get("steps", []))
    candidates = [
        dict(step) for step in catalog_steps if str(step.get("name", "")) == step_name
    ]
    if not candidates:
        _exit_with_error(
            f"Step not found in catalog {catalog_name}: {step_name}",
            hint="Check available steps with 'moira step list'",
        )

    selected: dict[str, Any]
    if step_version == "latest":
        selected = sorted(
            candidates,
            key=lambda item: _semver_key(str(item.get("version", "0.0.0"))),
            reverse=True,
        )[0]
    else:
        selected = next(
            (
                item
                for item in candidates
                if str(item.get("version", "")) == step_version
            ),
            {},
        )
        if not selected:
            _exit_with_error(
                f"Version {step_version} not found for step {step_name}",
                hint="Check catalog for available versions",
            )

    selected_version = str(selected.get("version", "0.1.0"))
    step_task = str(selected.get("task", ""))
    image_uri = str(selected.get("image_uri", ""))
    if not image_uri:
        _exit_with_error(f"Catalog entry for {step_name} has no image_uri")

    materialized_path = repo_root / config.steps_dir / f"{step_name}-catalog"

    if materialized_path.exists():
        confirmed = questionary.confirm(
            f"Catalog step '{materialized_path.name}' already exists. Overwrite?",
            default=False,
        ).ask()
        if not confirmed:
            ui.info("Operation cancelled.")
            return
        import shutil

        shutil.rmtree(materialized_path)
    materialized_path.mkdir(parents=True, exist_ok=False)

    task_contract = dict(selected.get("task_contract", {}))
    step_yaml = {
        "name": step_name,
        "version": selected_version,
        "task": step_task,
        "description": f"Catalog reference to {step_name}@{selected_version}",
        "image": image_uri,
        "source_catalog": catalog_name,
        "source_uri": config.catalogs[catalog_name].uri,
        "inputs": list(task_contract.get("inputs", [])),
        "outputs": list(task_contract.get("outputs", [])),
        "env": {},
    }
    (materialized_path / "step.yaml").write_text(
        yaml.safe_dump(step_yaml, sort_keys=False),
        encoding="utf-8",
    )

    schema_payload = {
        "task": step_task,
        "version": selected_version,
        "inputs": list(task_contract.get("inputs", [])),
        "outputs": list(task_contract.get("outputs", [])),
    }
    (materialized_path / "schema.json").write_text(
        json.dumps(schema_payload, indent=2) + "\n",
        encoding="utf-8",
    )

    ui.success(f"Added official step: {step_name}@{selected_version}")
    ui.path("Catalog", catalog_name)
    ui.path("Image", image_uri)
    ui.path("Location", str(materialized_path))


@pipeline_app.command("list")
def pipeline_list() -> None:
    """List all pipeline definitions from pipelines/*/pipeline.yaml."""
    from moira_cli.commands.pipeline import PipelineCommand
    from moira_cli.presenters.pipeline import PipelinePresenter

    repo_root = _repo_root()
    cmd = PipelineCommand(repo_root)
    result = cmd.execute(action="list")

    if result.get("status") == "success":
        presenter = PipelinePresenter()
        presenter.present_list(result.get("pipelines", []))
    else:
        ui.error(result.get("message", "Failed to list pipelines"))


@pipeline_app.command("new")
def pipeline_new(name: str = typer.Argument(..., help="Pipeline name.")) -> None:
    """Create a new pipeline scaffold.

    Examples:
        moira pipeline new hello-world
        moira pipeline new text-search-rag
    """

    from moira_cli.commands.pipeline import PipelineCommand
    from moira_cli.presenters.pipeline import PipelinePresenter

    repo_root = _repo_root()
    _, _, pipelines_root = _default_dirs(repo_root)
    pipeline_path = pipelines_root / name / "pipeline.yaml"
    if pipeline_path.exists():
        confirmed = questionary.confirm(
            f"Pipeline '{name}' already exists. Overwrite?",
            default=False,
        ).ask()
        if not confirmed:
            ui.info("Operation cancelled.")
            return
        import shutil

        shutil.rmtree(pipelines_root / name)

    cmd = PipelineCommand(repo_root)
    result = cmd.execute(action="new", pipeline_name=name)

    if result.get("status") == "success":
        presenter = PipelinePresenter()
        presenter.present_new(name, result.get("created", {}))
    else:
        ui.error(result.get("message", "Failed to create pipeline"))


@pipeline_app.command("validate")
def pipeline_validate(
    name: str = typer.Argument(..., help="Pipeline directory name."),
) -> None:
    """Validate task compatibility across sequential pipeline steps."""
    from moira_cli.commands.pipeline import PipelineCommand
    from moira_cli.presenters.pipeline import PipelinePresenter

    repo_root = _repo_root()
    cmd = PipelineCommand(repo_root)
    result = cmd.execute(action="validate", pipeline_name=name)

    if result.get("status") == "success":
        presenter = PipelinePresenter()
        presenter.present_validation(name, result.get("validation", {}))
    else:
        ui.error(result.get("message", "Failed to validate pipeline"))


@pipeline_app.command("dev")
def pipeline_dev(name: str = typer.Argument(..., help="Pipeline name.")) -> None:
    """Start local compose services required by one pipeline.

    :param name: Pipeline name.
    """
    repo_root = _repo_root()

    compose_path = repo_root / "docker-compose.yml"
    if not compose_path.exists():
        _exit_with_error(
            "docker-compose.yml not found in workspace.",
            hint="Run 'moira init' to generate it automatically.",
        )

    step_defs = _pipeline_step_defs(repo_root, name)
    _write_compose_override(repo_root, step_defs)

    services = list(_PLATFORM_SERVICES)
    for step in step_defs:
        parsed = urlparse(str(step.get("url", "")))
        host = parsed.hostname
        if host and host not in _PLATFORM_SERVICES and host not in services:
            services.append(host)

    command = ["docker", "compose", "up", "-d", *services]
    with Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("{task.description}", style="dim"),
        transient=True,
    ) as progress:
        progress.add_task(f"Starting services: {', '.join(services)}", total=None)
        output = _run_command(command, cwd=repo_root)
        progress.stop()
    if output:
        ui.info(output)
    else:
        ui.success(f"Started services: {', '.join(services)}")


@pipeline_app.command("run")
def pipeline_run(
    name: str = typer.Argument(..., help="Pipeline name."),
    input_data: str = typer.Option(..., "--input", help="Input JSON or @file path."),
    detach: bool = typer.Option(False, help="Return job id without waiting."),
    timeout: int = typer.Option(120, help="Seconds to wait for job completion."),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Run a pipeline through runtime API.

    :param name: Pipeline name.
    :param input_data: Inline JSON or file path.
    :param detach: Return immediately with job id.
    :param timeout: Seconds to wait for job completion.
    :param api_url: API base URL.
    """
    payload = _parse_json_input(input_data)
    run_payload = {"input": payload}

    run_urls = [
        f"{api_url}/v1/pipelines/{name}/run",
        f"{api_url}/v1/pipelines/{name}/jobs",
    ]
    response: dict[str, Any] | None = None

    for run_url in run_urls:
        try:
            response = _request_json("POST", run_url, run_payload)
            break
        except typer.Exit:
            response = None
            continue

    if response is None:
        _exit_with_error("Unable to start pipeline run on available endpoints")

    job_id = str(response.get("job_id") or response.get("id") or "")
    if not job_id:
        console.print(Syntax(json.dumps(response, indent=2), "json"))
        return

    ui.success(f"Started job {job_id}")
    if detach:
        return

    with Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("{task.description}", style="dim"),
        transient=True,
    ) as progress:
        task = progress.add_task(f"Waiting for job {job_id}... (0s)", total=None)
        for elapsed in range(timeout):
            status = _request_json("GET", f"{api_url}/v1/pipelines/jobs/{job_id}")
            state = str(status.get("status", "unknown"))
            progress.update(
                task, description=f"Waiting for job {job_id}... ({elapsed}s) [{state}]"
            )
            if state.lower() in {"completed", "failed", "error"}:
                progress.stop()
                ui.info("Job result:")
                console.print(Syntax(json.dumps(status, indent=2), "json"))
                return
            time.sleep(1)
        progress.stop()
    _exit_with_error(
        f"Timed out after {timeout}s waiting for job {job_id}.\n"
        f"Hint: check later with: moira job result {job_id}"
    )


@pipeline_app.command("deploy")
def pipeline_deploy(
    name: str = typer.Argument(..., help="Pipeline name."),
    env: str = typer.Option("dev", help="Target environment key from moiraweave.yaml."),
) -> None:
    """Deploy pipeline using environment strategy.

    :param name: Pipeline name.
    :param env: Environment key.
    """
    del name
    repo_root = _repo_root()
    config = load_moiraweave_config(repo_root)
    target = config.environments.get(env)
    if target is None:
        _exit_with_error(f"Environment not found in moiraweave.yaml: {env}")

    namespace = target.namespace or "moiraweave"
    with Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("{task.description}", style="dim"),
        transient=True,
    ) as progress:
        progress.add_task(f"Deploying pipeline ({target.deploy})...", total=None)
        try:
            if target.deploy == "helm":
                values = target.helm_values or "infra/helm/moiraweave/values.yaml"
                output = _run_command(
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
                        values,
                    ],
                    cwd=repo_root,
                )
                progress.stop()
                ui.info(output)
                return
            if target.deploy == "argocd":
                if not target.argocd_app:
                    _exit_with_error("argocd_app is required for deploy: argocd")
                output = _run_command(
                    ["argocd", "app", "sync", target.argocd_app], cwd=repo_root
                )
                progress.stop()
                ui.info(output)
                return
            progress.stop()
            _exit_with_error(f"Unsupported deploy strategy: {target.deploy}")
        except typer.Exit:
            progress.stop()
            raise


@pipeline_app.command("status")
def pipeline_status(
    name: str = typer.Argument(..., help="Pipeline name."),
    env: str = typer.Option("dev", help="Target environment key."),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Show pipeline status from runtime API or Kubernetes.

    :param name: Pipeline name.
    :param env: Environment key.
    :param api_url: API base URL.
    """
    repo_root = _repo_root()
    try:
        data = _request_json("GET", f"{api_url}/v1/pipelines/{name}/status")
        ui.success("Pipeline status:")
        console.print(Syntax(json.dumps(data, indent=2), "json"))
        return
    except typer.Exit:
        pass

    config = load_moiraweave_config(repo_root)
    target = config.environments.get(env)
    namespace = target.namespace if target and target.namespace else "moiraweave"

    output = _run_command(
        [
            "kubectl",
            "get",
            "deploy",
            "-n",
            namespace,
            "-l",
            f"moiraweave.io/pipeline={name}",
            "-o",
            "wide",
        ],
        cwd=repo_root,
    )
    ui.info(output)


@pipeline_app.command("logs")
def pipeline_logs(
    name: str = typer.Argument(..., help="Pipeline name."),
    step: str = typer.Option(..., "--step", help="Step ID label."),
    env: str = typer.Option("dev", help="Target environment key."),
    follow: bool = typer.Option(False, help="Follow logs."),
) -> None:
    """Stream logs for one pipeline step.

    :param name: Pipeline name.
    :param step: Step ID label.
    :param env: Environment key.
    :param follow: Whether to follow logs.
    """
    repo_root = _repo_root()
    config = load_moiraweave_config(repo_root)
    target = config.environments.get(env)
    namespace = target.namespace if target and target.namespace else "moiraweave"

    command = [
        "kubectl",
        "logs",
        "-n",
        namespace,
        "-l",
        f"moiraweave.io/pipeline={name},moiraweave.io/step={step}",
        "--tail",
        "200",
    ]
    if follow:
        command.append("-f")
    output = _run_command(command, cwd=repo_root)
    ui.info(output)


@pipeline_app.command("scale")
def pipeline_scale(
    name: str = typer.Argument(..., help="Pipeline name."),
    step: str = typer.Option(..., "--step", help="Step ID label."),
    replicas: int = typer.Option(..., "--replicas", min=1, help="Replica count."),
    env: str = typer.Option("dev", help="Target environment key."),
) -> None:
    """Scale one pipeline step deployment.

    :param name: Pipeline name.
    :param step: Step ID label.
    :param replicas: Replica count.
    :param env: Environment key.
    """
    repo_root = _repo_root()
    config = load_moiraweave_config(repo_root)
    target = config.environments.get(env)
    namespace = target.namespace if target and target.namespace else "moiraweave"

    output = _run_command(
        [
            "kubectl",
            "scale",
            "deploy",
            "-n",
            namespace,
            "-l",
            f"moiraweave.io/pipeline={name},moiraweave.io/step={step}",
            f"--replicas={replicas}",
        ],
        cwd=repo_root,
    )
    ui.info(output)


@pipeline_app.command("rollback")
def pipeline_rollback(
    name: str = typer.Argument(..., help="Pipeline name (informational)."),
    env: str = typer.Option("dev", help="Target environment key."),
    revision: int = typer.Option(
        0, help="Helm revision to roll back to (0 = previous)."
    ),
) -> None:
    """Rollback Helm release for runtime chart.

    :param name: Pipeline name.
    :param env: Environment key.
    :param revision: Target Helm revision.
    """
    del name
    repo_root = _repo_root()
    config = load_moiraweave_config(repo_root)
    target = config.environments.get(env)
    namespace = target.namespace if target and target.namespace else "moiraweave"

    if revision > 0:
        command = ["helm", "rollback", "moiraweave", str(revision), "-n", namespace]
    else:
        command = ["helm", "rollback", "moiraweave", "-n", namespace]

    output = _run_command(command, cwd=repo_root)
    console.print(output)
    ui.info(output)


@pipeline_app.command("metrics")
def pipeline_metrics(
    name: str = typer.Argument(..., help="Pipeline name."),
    env: str = typer.Option("dev", help="Target environment key."),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Show runtime metrics payload for one pipeline.

    :param name: Pipeline name.
    :param env: Environment key.
    :param api_url: API base URL.
    """
    del env
    data = _request_json("GET", f"{api_url}/v1/pipelines/{name}/metrics")
    ui.info("Pipeline metrics:")
    console.print(Syntax(json.dumps(data, indent=2), "json"))


@models_app.command("prefetch")
def models_prefetch(name: str = typer.Argument(..., help="Pipeline name.")) -> None:
    """Probe step readiness to warm model caches.

    :param name: Pipeline name.
    """
    from moira_cli.commands.models import ModelsCommand
    from moira_cli.presenters.models import ModelsPresenter

    repo_root = _repo_root()
    cmd = ModelsCommand(repo_root, api_url=DEFAULT_API_URL)
    result = cmd.execute(action="prefetch", pipeline_name=name)

    if result.get("status") == "success":
        presenter = ModelsPresenter()
        presenter.present_prefetch(name, result.get("prefetch", {}))
    else:
        ui.error(result.get("message", "Failed to prefetch models"))


@models_app.command("status")
def models_status(name: str = typer.Argument(..., help="Pipeline name.")) -> None:
    """Show per-step model metadata status.

    :param name: Pipeline name.
    """
    from moira_cli.commands.models import ModelsCommand
    from moira_cli.presenters.models import ModelsPresenter

    repo_root = _repo_root()
    cmd = ModelsCommand(repo_root, api_url=DEFAULT_API_URL)
    result = cmd.execute(action="status", pipeline_name=name)

    if result.get("status") == "success":
        presenter = ModelsPresenter()
        presenter.present_status(name, result.get("model_status", {}))
    else:
        ui.error(result.get("message", "Failed to get model status"))


@models_app.command("clear")
def models_clear(name: str = typer.Argument(..., help="Pipeline name.")) -> None:
    """Clear local model cache path for a pipeline.

    :param name: Pipeline name.
    """
    from moira_cli.commands.models import ModelsCommand
    from moira_cli.presenters.models import ModelsPresenter

    repo_root = _repo_root()
    confirmed = questionary.confirm(
        f"Delete local cache directory for {name}?",
        default=False,
    ).ask()
    if not confirmed:
        ui.info("Aborted.")
        return

    cmd = ModelsCommand(repo_root, api_url=DEFAULT_API_URL)
    result = cmd.execute(action="clear", pipeline_name=name)

    if result.get("status") == "success":
        presenter = ModelsPresenter()
        presenter.present_clear(name, result.get("clear_result", {}))
    else:
        ui.error(result.get("message", "Failed to clear cache"))


@job_app.command("list")
def job_list(
    pipeline: str | None = typer.Option(
        None, "--pipeline", "-p", help="Filter by pipeline name."
    ),
    limit: int = typer.Option(20, help="Maximum number of jobs to show."),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """List recent jobs for the authenticated user.

    :param pipeline: Optional pipeline name filter.
    :param limit: Maximum number of jobs to display.
    :param api_url: API base URL.
    """
    from moira_cli.commands.job import JobCommand
    from moira_cli.presenters.job import JobPresenter

    cmd = JobCommand(api_url=api_url)
    result = cmd.execute(action="list", pipeline_id=pipeline, limit=limit)

    if result.get("status") == "success":
        presenter = JobPresenter()
        presenter.present_list(result.get("jobs", []))
    else:
        ui.error(result.get("message", "Failed to list jobs"))


@job_app.command("status")
def job_status(
    job_id: str = typer.Argument(..., help="Job identifier."),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Show status payload for one job.

    :param job_id: Job identifier.
    :param api_url: API base URL.
    """
    from moira_cli.commands.job import JobCommand
    from moira_cli.presenters.job import JobPresenter

    cmd = JobCommand(api_url=api_url)
    result = cmd.execute(action="status", job_id=job_id)

    if result.get("status") == "success":
        presenter = JobPresenter()
        presenter.present_status(job_id, result.get("job_status", {}))
    else:
        ui.error(result.get("message", "Failed to get job status"))


@job_app.command("result")
def job_result(
    job_id: str = typer.Argument(..., help="Job identifier."),
    api_url: str = typer.Option(DEFAULT_API_URL, help="Gateway API base URL."),
) -> None:
    """Show result payload for one job.

    :param job_id: Job identifier.
    :param api_url: API base URL.
    """
    from moira_cli.commands.job import JobCommand
    from moira_cli.presenters.job import JobPresenter

    cmd = JobCommand(api_url=api_url)
    result = cmd.execute(action="result", job_id=job_id)

    if result.get("status") == "success":
        presenter = JobPresenter()
        presenter.present_result(job_id, result.get("result", {}))
    else:
        ui.error(result.get("message", "Failed to get job result"))


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
