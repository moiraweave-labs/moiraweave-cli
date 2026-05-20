"""Step management handler."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from moira_cli.handlers import BaseHandler
from moira_cli.io import discover_steps


def _read_json_file(path: Path) -> dict[str, Any]:
    """Read JSON file as dictionary."""
    try:
        return dict(__import__("json").loads(path.read_text(encoding="utf-8")))
    except Exception as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


class StepHandler(BaseHandler):
    """Handle step operations."""

    def list_steps(self) -> list[dict[str, Any]]:
        """List all discovered steps.

        :returns: List of step dictionaries with metadata.
        """
        _, steps_root, _ = self._get_dirs()
        steps = discover_steps(self.repo_root)
        return [
            {
                "name": step.name,
                "task": step.task,
                "version": step.version,
                "has_dockerfile": (step.path.parent / "Dockerfile").exists(),
                "path": str(step.path),
            }
            for step in steps
        ]

    def get_step_info(self, name: str) -> dict[str, Any]:
        """Get detailed step information.

        :param name: Step name.
        :returns: Step metadata.
        :raises FileNotFoundError: If step not found.
        """
        _, steps_root, _ = self._get_dirs()
        step_path = steps_root / name / "step.yaml"
        if not step_path.exists():
            raise FileNotFoundError(f"Step not found: {name}")

        import yaml

        step_yaml = yaml.safe_load(step_path.read_text(encoding="utf-8"))
        return dict(step_yaml or {})

    def test_step(self, name: str) -> dict[str, Any]:
        """Run tests for a step.

        :param name: Step directory name.
        :returns: Test result dict with status and output.
        """
        import subprocess

        _, steps_root, _ = self._get_dirs()
        tests_root = steps_root / name / "tests"

        if not tests_root.exists():
            return {"status": "not_found", "path": str(tests_root)}

        proc = subprocess.run(
            ["uv", "run", "pytest", str(tests_root), "-q"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        return {
            "status": "passed" if proc.returncode == 0 else "failed",
            "output": proc.stdout or proc.stderr,
            "returncode": proc.returncode,
        }

    # If a destructive method is added here, add confirmation in the Typer command, not here.

    def build_step(self, name: str) -> dict[str, Any]:
        """Build step container image.

        :param name: Step directory name.
        :returns: Build result dict.
        """
        import subprocess

        config = self.config
        _, steps_root, _ = self._get_dirs()
        step_root = steps_root / name
        version_file = step_root / "VERSION"

        if not version_file.exists():
            return {"status": "error", "message": f"VERSION not found for step: {name}"}

        version = version_file.read_text(encoding="utf-8").strip()
        image = f"{config.registry.rstrip('/')}/{name}:v{version}"

        proc = subprocess.run(
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
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        return {
            "status": "success" if proc.returncode == 0 else "failed",
            "image": image,
            "output": proc.stdout or proc.stderr,
            "returncode": proc.returncode,
        }

    def push_step(self, name: str, bump: str | None = None) -> dict[str, Any]:
        """Push step image to registry.

        :param name: Step directory name.
        :param bump: Optional semver bump (patch|minor|major).
        :returns: Push result dict.
        """
        import subprocess

        config = self.config
        _, steps_root, _ = self._get_dirs()
        step_root = steps_root / name
        version_file = step_root / "VERSION"

        if not version_file.exists():
            return {"status": "error", "message": f"VERSION not found for step: {name}"}

        version = version_file.read_text(encoding="utf-8").strip()

        # Bump version if requested
        if bump:
            if bump not in {"patch", "minor", "major"}:
                return {"status": "error", "message": f"Invalid bump: {bump}"}
            version = self._bump_semver(version, bump)
            version_file.write_text(version + "\n", encoding="utf-8")

        image = f"{config.registry.rstrip('/')}/{name}:v{version}"

        proc = subprocess.run(
            ["docker", "push", image],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        output = (proc.stdout + proc.stderr).strip()
        auth_keywords = (
            "unauthorized",
            "denied",
            "authentication required",
            "login required",
            "credential",
            "not logged in",
        )
        auth_error = proc.returncode != 0 and any(
            kw in output.lower() for kw in auth_keywords
        )
        return {
            "status": "success" if proc.returncode == 0 else "failed",
            "image": image,
            "version": version,
            "bumped": bump is not None,
            "output": output,
            "returncode": proc.returncode,
            "auth_error": auth_error,
        }

    def _bump_semver(self, version: str, kind: str) -> str:
        """Bump semantic version."""
        parts = version.strip().split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            raise ValueError(f"Invalid semver version: {version}")
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
