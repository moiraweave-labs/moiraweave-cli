"""Filesystem helpers for MoiraWeave CLI."""

from __future__ import annotations

import json
import secrets
import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

import yaml
from dotenv import dotenv_values
from pydantic import ValidationError

from moira_cli.models import MoiraWeaveConfig


@dataclass(frozen=True)
class TaskInfo:
    """Task metadata loaded from tasks/<task>/schema.json."""

    name: str
    description: str
    path: Path


@dataclass(frozen=True)
class StepInfo:
    """Step metadata loaded from steps/<step>/step.yaml."""

    name: str
    task: str
    version: str
    path: Path


@dataclass(frozen=True)
class PipelineInfo:
    """Pipeline metadata loaded from pipelines/<pipeline>/pipeline.yaml."""

    name: str
    description: str
    steps: list[dict[str, str]]
    path: Path


def load_moiraweave_config(repo_root: Path) -> MoiraWeaveConfig:
    """Load and validate moiraweave.yaml from repository root.

    :param repo_root: Repository root path.
    :returns: Parsed project configuration.
    :raises FileNotFoundError: If moiraweave.yaml does not exist.
    :raises ValueError: If the file is invalid.
    """
    config_path = repo_root / "moiraweave.yaml"
    if not config_path.exists():
        raise FileNotFoundError("moiraweave.yaml not found")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    try:
        return MoiraWeaveConfig.model_validate(raw)
    except ValidationError as exc:  # pragma: no cover - formatting branch
        raise ValueError(f"Invalid moiraweave.yaml: {exc}") from exc


def write_default_moiraweave_config(repo_root: Path, name: str, registry: str) -> None:
    """Write a default moiraweave.yaml file.

    :param repo_root: Repository root path.
    :param name: Project name.
    :param registry: Image registry URL.
    """
    config = {
        "name": name,
        "registry": registry,
        "runtime_version": "0.1.0",
        "catalogs": {
            "moiraweave-official": {
                "name": "moiraweave-official",
                "uri": "https://github.com/moiraweave-labs/moiraweave-steps",
                "enabled": True,
            }
        },
        "environments": {
            "local": {"context": "docker-compose", "values": ".env"},
            "dev": {
                "context": "kubernetes",
                "kubeconfig": "~/.kube/config",
                "namespace": "moiraweave-dev",
                "helm_values": ".moiraweave/deploy/values-dev.yaml",
                "deploy": "helm",
            },
            "prod": {
                "context": "kubernetes",
                "namespace": "moiraweave-prod",
                "helm_values": ".moiraweave/deploy/values-prod.yaml",
                "deploy": "helm",
            },
        },
        "pipelines_dir": ".moiraweave/pipelines",
        "steps_dir": ".moiraweave/steps",
        "tasks_dir": ".moiraweave/tasks",
    }
    target = repo_root / "moiraweave.yaml"
    target.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def scaffold_workspace_structure(repo_root: Path) -> None:
    """Create complete workspace directory structure.

    Creates:
    - .moiraweave/pipelines/ (pipeline definitions)
    - .moiraweave/steps/ (custom step implementations)
    - .moiraweave/tasks/ (custom task schemas)
    - .moiraweave/deploy/ (deployment configuration)
    - .gitignore (sensible defaults)

    :param repo_root: Repository root path.
    """
    dirs = [
        repo_root / ".moiraweave" / "pipelines",
        repo_root / ".moiraweave" / "steps",
        repo_root / ".moiraweave" / "tasks",
        repo_root / ".moiraweave" / "deploy",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        (d / ".gitkeep").touch()

    # Create .gitignore if it doesn't exist
    gitignore_path = repo_root / ".gitignore"
    if not gitignore_path.exists():
        gitignore_content = """.env
.venv/
__pycache__/
*.pyc
*.pyo
*.pyd
.DS_Store
.idea/
.vscode/
*.egg-info/
dist/
build/
.pytest_cache/
.mypy_cache/
"""
        gitignore_path.write_text(gitignore_content, encoding="utf-8")

    # Create deploy values files
    for env in ["local", "dev", "prod"]:
        values_file = repo_root / ".moiraweave" / "deploy" / f"values-{env}.yaml"
        if not values_file.exists():
            values_file.write_text(
                f"# Deployment values for {env} environment\n"
                f"# Override or extend defaults from moiraweave-core\n"
                f"environment: {env}\n",
                encoding="utf-8",
            )


def ensure_local_env(repo_root: Path) -> None:
    """Create `.env` with safe defaults if it does not exist.

    :param repo_root: Repository root path.
    """
    env_path = repo_root / ".env"
    if env_path.exists():
        return

    secret = secrets.token_urlsafe(32)
    content = (
        f"JWT_SECRET_KEY={secret}\n"
        "JWT_ALGORITHM=HS256\n"
        "JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30\n"
    )
    env_path.write_text(content, encoding="utf-8")


def read_env(repo_root: Path) -> dict[str, str]:
    """Read `.env` values from repository root.

    :param repo_root: Repository root path.
    :returns: Env key/value mapping.
    """
    values = dotenv_values(repo_root / ".env")
    return {k: v for k, v in values.items() if v is not None}


def discover_tasks(repo_root: Path, tasks_dir: str = "tasks") -> list[TaskInfo]:
    """Discover all task schema files.

    :param repo_root: Repository root path.
    :param tasks_dir: Relative tasks directory.
    :returns: Sorted task metadata.
    """
    root = repo_root / tasks_dir
    results: list[TaskInfo] = []
    for schema in sorted(root.glob("*/schema.json")):
        raw = json.loads(schema.read_text(encoding="utf-8"))
        results.append(
            TaskInfo(
                name=str(raw.get("task", schema.parent.name)),
                description=str(raw.get("description", "")),
                path=schema,
            )
        )
    return results


def discover_steps(repo_root: Path, steps_dir: str = "steps") -> list[StepInfo]:
    """Discover all step.yaml files.

    :param repo_root: Repository root path.
    :param steps_dir: Relative steps directory.
    :returns: Sorted step metadata.
    """
    root = repo_root / steps_dir
    results: list[StepInfo] = []
    for step_yaml in sorted(root.glob("*/step.yaml")):
        raw = yaml.safe_load(step_yaml.read_text(encoding="utf-8"))
        results.append(
            StepInfo(
                name=str(raw.get("name", step_yaml.parent.name)),
                task=str(raw.get("task", "")),
                version=str(raw.get("version", "")),
                path=step_yaml,
            )
        )
    return results


def discover_pipelines(
    repo_root: Path,
    pipelines_dir: str = "pipelines",
) -> list[PipelineInfo]:
    """Discover all pipeline definition files.

    :param repo_root: Repository root path.
    :param pipelines_dir: Relative pipelines directory.
    :returns: Sorted pipeline metadata.
    """
    root = repo_root / pipelines_dir
    results: list[PipelineInfo] = []
    for pipeline_yaml in sorted(root.glob("*/pipeline.yaml")):
        raw = yaml.safe_load(pipeline_yaml.read_text(encoding="utf-8"))
        results.append(
            PipelineInfo(
                name=str(raw.get("name", pipeline_yaml.parent.name)),
                description=str(raw.get("description", "")),
                steps=list(raw.get("steps", [])),
                path=pipeline_yaml,
            )
        )
    return results


def check_prereqs() -> dict[str, bool]:
    """Check local command prerequisites.

    :returns: Mapping with command availability.
    """
    return {
        "docker": shutil.which("docker") is not None,
        "kubectl": shutil.which("kubectl") is not None,
        "helm": shutil.which("helm") is not None,
    }
