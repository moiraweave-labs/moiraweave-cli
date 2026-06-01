"""Optional local Docker onboarding E2E tests.

These tests are intentionally opt-in because they start Docker Compose services.
Run with ``MOIRAWEAVE_LOCAL_E2E=1 uv run pytest tests/test_local_e2e.py``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


def _image_available(image: str, env: dict[str, str]) -> bool:
    local = subprocess.run(
        ["docker", "image", "inspect", image],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if local.returncode == 0:
        return True
    remote = subprocess.run(
        ["docker", "manifest", "inspect", image],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return remote.returncode == 0


@pytest.mark.integration
def test_moira_up_demo_agent_chat_fresh_workspace(tmp_path: Path) -> None:
    """A fresh workspace can start and complete the first demo-agent chat."""
    if os.getenv("MOIRAWEAVE_LOCAL_E2E") != "1":
        pytest.skip("set MOIRAWEAVE_LOCAL_E2E=1 to run the Docker onboarding E2E")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env = {
        **os.environ,
        "MOIRAWEAVE_UI_PORT": "3100",
        "API_GATEWAY_PORT": "8100",
        "POSTGRES_PORT": "55432",
        "REDIS_PORT": "56379",
        "QDRANT_PORT": "56333",
    }
    required_images = [
        env.get(
            "MOIRAWEAVE_API_GATEWAY_IMAGE",
            "ghcr.io/moiraweave-labs/moiraweave/api-gateway:latest",
        ),
        env.get(
            "MOIRAWEAVE_WORKER_IMAGE",
            "ghcr.io/moiraweave-labs/moiraweave/worker:latest",
        ),
        env.get("MOIRAWEAVE_UI_IMAGE", "ghcr.io/moiraweave-labs/moiraweave-ui:latest"),
        "postgres:16-alpine",
        "redis:7-alpine",
        "qdrant/qdrant:v1.9.2",
        "python:3.13-slim",
    ]
    missing_images = [image for image in required_images if not _image_available(image, env)]
    if missing_images:
        pytest.skip(
            "required onboarding images are not locally available or pullable: "
            + ", ".join(missing_images)
        )

    try:
        up = subprocess.run(
            ["uv", "run", "moira", "up", "--api-url", "http://localhost:8100"],
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert up.returncode == 0, up.stdout + up.stderr

        chat = subprocess.run(
            [
                "uv",
                "run",
                "moira",
                "agent",
                "chat",
                "demo-agent",
                "hello from e2e",
                "--watch",
                "--api-url",
                "http://localhost:8100",
            ],
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert chat.returncode == 0, chat.stdout + chat.stderr
        assert "Demo agent received" in chat.stdout
        assert "demo-reply.json" in chat.stdout
    finally:
        subprocess.run(
            ["docker", "compose", "down", "--volumes"],
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
