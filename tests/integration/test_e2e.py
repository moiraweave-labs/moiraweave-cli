"""Integration tests for full moira CLI workflows.

These tests exercise complete DX journeys: init → step/pipeline scaffolding →
flow tree display.  They require the ``moira`` CLI to be installed (``uv run
moira``) and a writable temp directory, but do *not* require a running stack.

Run selectively:
    uv run pytest tests/integration/ -m integration -v
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(
    args: list[str], cwd: Path, *, expect_rc: int = 0
) -> subprocess.CompletedProcess[str]:
    """Run a moira CLI command and assert the exit code."""
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


def _seed_task_schema(workspace: Path, task: str) -> None:
    """Write a minimal task schema so that ``step new`` can find it.

    ``moira step new`` reads the schema from ``<tasks_dir>/<task>/schema.json``.
    In a fresh init workspace the tasks dir is empty, so tests must seed it.
    """
    config = yaml.safe_load((workspace / "moiraweave.yaml").read_text())
    schema_dir = workspace / config["tasks_dir"] / task
    schema_dir.mkdir(parents=True, exist_ok=True)
    schema = {
        "task": task,
        "version": "1.0",
        "description": f"Minimal schema for {task} (test fixture)",
        "inputs": [
            {"name": "input", "datatype": "BYTES", "shape": [1], "required": True}
        ],
        "outputs": [{"name": "output", "datatype": "BYTES", "shape": [1]}],
    }
    (schema_dir / "schema.json").write_text(
        json.dumps(schema, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def workspace(tmp_path: Path, repo_root: Path) -> Path:
    """Initialise a fresh MoiraWeave workspace in a temp directory."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _run(
        ["init", "--non-interactive", "--name", "integ", "--registry", "ghcr.io/integ"],
        cwd=ws,
    )
    return ws


# ---------------------------------------------------------------------------
# Tests — workspace initialisation
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestInitWorkflow:
    """init command creates expected workspace structure."""

    def test_moiraweave_yaml_created(self, workspace: Path) -> None:
        config_file = workspace / "moiraweave.yaml"
        assert config_file.exists(), "moiraweave.yaml must be created by init"

    def test_moiraweave_yaml_has_required_keys(self, workspace: Path) -> None:
        config = yaml.safe_load((workspace / "moiraweave.yaml").read_text())
        for key in ("name", "registry", "pipelines_dir", "steps_dir", "tasks_dir"):
            assert key in config, f"moiraweave.yaml missing key: {key}"

    def test_default_dirs_created(self, workspace: Path) -> None:
        config = yaml.safe_load((workspace / "moiraweave.yaml").read_text())
        for dir_key in ("pipelines_dir", "steps_dir", "tasks_dir"):
            expected = workspace / config[dir_key]
            assert expected.exists(), f"Directory {config[dir_key]} was not created"


# ---------------------------------------------------------------------------
# Tests — step scaffolding
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStepScaffolding:
    """step new command creates expected step structure.

    ``moira step new <task> <implementation>`` — both arguments required.
    The resulting directory is ``<steps_dir>/<task>-<implementation>``.
    """

    def test_step_new_creates_directory(self, workspace: Path) -> None:
        _seed_task_schema(workspace, "text-embed")
        _run(["step", "new", "text-embed", "fastembed"], cwd=workspace)
        config = yaml.safe_load((workspace / "moiraweave.yaml").read_text())
        step_dir = workspace / config["steps_dir"] / "text-embed-fastembed"
        assert step_dir.is_dir(), "step directory must be created"

    def test_step_new_creates_dockerfile(self, workspace: Path) -> None:
        _seed_task_schema(workspace, "vector-index")
        _run(["step", "new", "vector-index", "qdrant"], cwd=workspace)
        config = yaml.safe_load((workspace / "moiraweave.yaml").read_text())
        dockerfile = (
            workspace / config["steps_dir"] / "vector-index-qdrant" / "Dockerfile"
        )
        assert dockerfile.exists(), "Dockerfile must be scaffolded"

    def test_step_new_creates_version_file(self, workspace: Path) -> None:
        _seed_task_schema(workspace, "vector-search")
        _run(["step", "new", "vector-search", "qdrant"], cwd=workspace)
        config = yaml.safe_load((workspace / "moiraweave.yaml").read_text())
        version_file = (
            workspace / config["steps_dir"] / "vector-search-qdrant" / "VERSION"
        )
        assert version_file.exists(), "VERSION must be scaffolded"


# ---------------------------------------------------------------------------
# Tests — pipeline scaffolding
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPipelineScaffolding:
    """pipeline new command creates expected pipeline structure."""

    def test_pipeline_new_creates_directory(self, workspace: Path) -> None:
        _run(["pipeline", "new", "my-pipeline"], cwd=workspace)
        config = yaml.safe_load((workspace / "moiraweave.yaml").read_text())
        pipeline_dir = workspace / config["pipelines_dir"] / "my-pipeline"
        assert pipeline_dir.is_dir()

    def test_pipeline_new_creates_pipeline_yaml(self, workspace: Path) -> None:
        _run(["pipeline", "new", "text-search"], cwd=workspace)
        config = yaml.safe_load((workspace / "moiraweave.yaml").read_text())
        pipeline_yaml = (
            workspace / config["pipelines_dir"] / "text-search" / "pipeline.yaml"
        )
        assert pipeline_yaml.exists(), "pipeline.yaml must be scaffolded"

    def test_pipeline_yaml_is_valid_yaml(self, workspace: Path) -> None:
        _run(["pipeline", "new", "audio-rag"], cwd=workspace)
        config = yaml.safe_load((workspace / "moiraweave.yaml").read_text())
        pipeline_yaml = (
            workspace / config["pipelines_dir"] / "audio-rag" / "pipeline.yaml"
        )
        parsed = yaml.safe_load(pipeline_yaml.read_text())
        assert isinstance(parsed, dict), "pipeline.yaml must be valid YAML mapping"

    def test_pipeline_validate_scaffolded(self, workspace: Path) -> None:
        _run(["pipeline", "new", "validate-me"], cwd=workspace)
        result = _run(["pipeline", "validate", "validate-me"], cwd=workspace)
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# Tests — flow tree
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFlowCommand:
    """flow flow-command shows workspace dependency tree."""

    def test_flow_runs_in_empty_workspace(self, workspace: Path) -> None:
        result = _run(["flow", "flow-command"], cwd=workspace)
        assert result.returncode == 0

    def test_flow_shows_pipeline_after_creation(self, workspace: Path) -> None:
        _run(["pipeline", "new", "flow-test-pipeline"], cwd=workspace)
        result = _run(["flow", "flow-command"], cwd=workspace)
        assert "flow-test-pipeline" in result.stdout

    def test_flow_shows_step_after_creation(self, workspace: Path) -> None:
        # Create a pipeline that references a step — flow shows step ids from pipeline.yaml
        _run(["pipeline", "new", "clip-pipeline"], cwd=workspace)
        config = yaml.safe_load((workspace / "moiraweave.yaml").read_text())
        pipeline_yaml = (
            workspace / config["pipelines_dir"] / "clip-pipeline" / "pipeline.yaml"
        )
        # Inject a step id into the scaffolded pipeline
        parsed = yaml.safe_load(pipeline_yaml.read_text())
        parsed["steps"] = [
            {
                "id": "vision-step",
                "task": "vision-clip",
                "url": "http://vision-clip-v2:8000",
            }
        ]
        pipeline_yaml.write_text(yaml.dump(parsed), encoding="utf-8")

        result = _run(["flow", "flow-command"], cwd=workspace)
        assert "clip-pipeline" in result.stdout
        assert "vision-step" in result.stdout
