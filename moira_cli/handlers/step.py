"""Step management handler."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

import httpx
import yaml

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

    def get_live_step_metadata(self, name: str, url: str | None = None) -> dict[str, Any]:
        """Fetch live metadata from a running step endpoint.

        :param name: Step name.
        :param url: Optional base URL.
        :returns: Live metadata payload.
        """
        base_url = url or f"http://{name}:8080"
        response = httpx.get(f"{base_url.rstrip('/')}/v2/models/{name}", timeout=10.0)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            return payload
        return {"data": payload}

    def add_official_step(self, step_ref: str) -> dict[str, Any]:
        """Materialize an official step from the catalog.

        :param step_ref: Step reference in the form ``name[@version]``.
        :returns: Result payload with created step metadata.
        :raises FileExistsError: If the step already exists locally.
        :raises FileNotFoundError: If the catalog entry is missing.
        """
        config = self.config
        catalog_name, catalog = self._load_catalog_document()

        if "@" in step_ref:
            step_name, step_version = step_ref.rsplit("@", 1)
        else:
            step_name = step_ref
            step_version = "latest"

        candidates = [
            dict(step)
            for step in list(catalog.get("steps", []))
            if str(step.get("name", "")) == step_name
        ]
        if not candidates:
            raise FileNotFoundError(f"Step not found in catalog {catalog_name}: {step_name}")

        if step_version == "latest":
            selected = sorted(
                candidates,
                key=lambda item: self._semver_key(str(item.get("version", "0.0.0"))),
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
                raise FileNotFoundError(
                    f"Version {step_version} not found for step {step_name}"
                )

        selected_version = str(selected.get("version", "0.1.0"))
        step_task = str(selected.get("task", ""))
        image_uri = str(selected.get("image_uri", ""))
        if not image_uri:
            raise ValueError(f"Catalog entry for {step_name} has no image_uri")

        materialized_path = self.repo_root / config.steps_dir / f"{step_name}-catalog"
        if materialized_path.exists():
            raise FileExistsError(f"Step already exists locally: {materialized_path.name}")
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

        return {
            "catalog": catalog_name,
            "name": step_name,
            "version": selected_version,
            "image_uri": image_uri,
            "path": str(materialized_path),
        }

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
        return {
            "status": "success" if proc.returncode == 0 else "failed",
            "image": image,
            "version": version,
            "bumped": bump is not None,
            "output": proc.stdout or proc.stderr,
            "returncode": proc.returncode,
        }

    def _get_dirs(self) -> tuple[Path, Path, Path]:
        """Get tasks/steps/pipelines directories."""
        return (
            self.repo_root / self.config.tasks_dir,
            self.repo_root / self.config.steps_dir,
            self.repo_root / self.config.pipelines_dir,
        )

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

    def _semver_key(self, version: str) -> tuple[int, int, int]:
        """Return a sortable key for MAJOR.MINOR.PATCH versions."""
        parts = version.strip().split(".")
        if len(parts) != 3 or not all(part.isdigit() for part in parts):
            return (0, 0, 0)
        return cast(tuple[int, int, int], tuple(int(part) for part in parts))

    def _load_catalog_document(self) -> tuple[str, dict[str, Any]]:
        """Load the first enabled catalog from local path or remote URI."""
        config = self.config
        enabled_catalogs = [
            (name, catalog) for name, catalog in config.catalogs.items() if catalog.enabled
        ]
        if not enabled_catalogs:
            raise FileNotFoundError("No enabled catalogs found in moiraweave.yaml")

        catalog_name, source = enabled_catalogs[0]
        local_catalog = self.repo_root / "catalog.yaml"
        if local_catalog.exists():
            return catalog_name, yaml.safe_load(local_catalog.read_text(encoding="utf-8")) or {}

        source_uri = source.uri
        parsed = urlparse(source_uri)
        if parsed.scheme in {"", "file"}:
            local_path = Path(parsed.path or source_uri)
            if not local_path.is_absolute():
                local_path = (self.repo_root / local_path).resolve()
            if local_path.is_file():
                if local_path.suffix.lower() == ".json":
                    return catalog_name, json.loads(local_path.read_text(encoding="utf-8"))
                return catalog_name, yaml.safe_load(local_path.read_text(encoding="utf-8")) or {}

        raw_url = self._catalog_raw_url_from_uri(source_uri)
        if raw_url is None:
            raise ValueError(f"Unsupported catalog URI: {source_uri}")

        response = httpx.get(raw_url, timeout=20.0)
        response.raise_for_status()
        if raw_url.endswith(".json"):
            data = response.json()
        else:
            data = yaml.safe_load(response.text)
        return catalog_name, dict(data or {})

    def _catalog_raw_url_from_uri(self, source_uri: str) -> str | None:
        """Convert a catalog URI to a raw fetch URL when possible."""
        if source_uri.startswith("https://github.com/"):
            path = source_uri.removeprefix("https://github.com/")
            if path.endswith(".git"):
                path = path[:-4]
            return f"https://raw.githubusercontent.com/{path}/main/catalog.yaml"
        return None
