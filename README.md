# MoiraWeave CLI

[![CI](https://github.com/moiraweave-labs/moiraweave-cli/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/moiraweave-labs/moiraweave-cli/actions/workflows/ci.yml)
[![Release Please](https://github.com/moiraweave-labs/moiraweave-cli/actions/workflows/release.yml/badge.svg?branch=main)](https://github.com/moiraweave-labs/moiraweave-cli/actions/workflows/release.yml)
[![Publish to PyPI](https://github.com/moiraweave-labs/moiraweave-cli/actions/workflows/publish.yml/badge.svg?branch=main)](https://github.com/moiraweave-labs/moiraweave-cli/actions/workflows/publish.yml)
[![PyPI](https://img.shields.io/pypi/v/moiraweave-cli)](https://pypi.org/project/moiraweave-cli/)
[![Python](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Developer CLI for creating, running, and operating MoiraWeave workspaces.

## Why this repository exists

`moiraweave-cli` is the entry point for platform users. It provides a single command surface for:

- workspace initialization
- step scaffolding and catalog integration
- pipeline creation and validation
- local runtime orchestration
- deployment commands and job inspection

## Installation

```bash
uv tool install moiraweave-cli
moira --help
```

## Quickstart

```bash
# 1) Initialize a workspace
moira project init
cd my-project-moira

# 2) Create a custom step
moira step new my-task my-impl

# 3) Create and validate a pipeline
moira pipeline new my-pipeline
moira pipeline validate my-pipeline

# 4) Run locally
moira pipeline dev my-pipeline
```

## Workspace ownership model

Your product code lives in your own workspace repository, not in upstream MoiraWeave repos:

```text
your-company-moira/
  moiraweave.yaml
  .env
  pipelines/
  steps/
  tasks/
  deploy/
```

## Development

```bash
uv sync --frozen
uv run ruff check moira_cli tests
uv run mypy moira_cli
uv run pytest
```

## Releases

- `release.yml` manages automated versioning/changelog updates via Release Please.
- `publish.yml` publishes release artifacts to PyPI.

## Related repositories

- [moiraweave-core](https://github.com/moiraweave-labs/moiraweave-core): runtime services and infrastructure
- [moiraweave-steps](https://github.com/moiraweave-labs/moiraweave-steps): official step catalog
- [moiraweave-docs](https://github.com/moiraweave-labs/moiraweave-docs): documentation site
- [.github](https://github.com/moiraweave-labs/.github): org-wide policies and templates
