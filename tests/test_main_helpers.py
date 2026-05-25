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
_catalog_raw_url_from_uri = MAIN_MODULE._catalog_raw_url_from_uri
_parse_json_input = MAIN_MODULE._parse_json_input
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
    expected = (
        "https://raw.githubusercontent.com/example/catalog/main/catalog.yaml"
    )
    assert _catalog_raw_url_from_uri(uri) == expected
