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

## Install and Update (uv-style)

### Install from PyPI

```bash
uv tool install moiraweave-cli
moira --version
moira --help
```

### Upgrade to latest

```bash
uv tool upgrade moiraweave-cli
```

### Pin to a specific version

```bash
uv tool install moiraweave-cli==0.1.1
```

### Reinstall cleanly

```bash
uv tool uninstall moiraweave-cli
uv tool install moiraweave-cli
```

### Install from GitHub (main branch)

```bash
uv tool install "git+https://github.com/moiraweave-labs/moiraweave-cli"
```

### Install from local source (for contributors)

```bash
uv tool install --editable .
```

### Verify resolution and tool path

```bash
uv tool list
which moira
```

### Fallback (if you do not use uv)

```bash
pipx install moiraweave-cli
pipx upgrade moiraweave-cli
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
  src/                 # your product code
  notebooks/           # optional user assets
  .moiraweave/
    pipelines/
    steps/
    tasks/
    deploy/
```

MoiraWeave keeps generated runtime scaffolding under `.moiraweave/` to avoid mixing
platform artifacts with user application code, following the same hidden-workspace
pattern used by modern developer tooling.

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
