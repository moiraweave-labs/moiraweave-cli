# MoiraWeave CLI

Developer CLI for the MoiraWeave platform. Entry point for creating and managing MoiraWeave projects.

## Install

```bash
uv tool install moiraweave-cli
```

## Quick Start: Create Your First Project

```bash
# Initialize a new MoiraWeave workspace
moira project init

# Scaffold your first custom step
moira step new my-task my-impl

# Create a pipeline
moira pipeline new my-pipeline

# Run locally
moira pipeline dev my-pipeline
```

## Usage

```bash
moira --help
```

The CLI covers:
- **Project initialization**: `moira project init` to bootstrap your workspace
- **Step management**: create custom steps and integrate official steps from catalog
- **Pipeline authoring**: define, validate, and execute pipelines
- **Deployment**: local Docker Compose or Kubernetes via Helm
- **Job inspection**: monitor running jobs and results

## Where Your Code Lives

You own and manage your project code in your own repository, not in MoiraWeave upstream repos:

```
your-company-moira/
  moiraweave.yaml          # Your project config
  .env                     # Your environment secrets
  pipelines/               # Your pipeline definitions
  steps/                   # Your custom steps
  tasks/                   # Your task contracts (optional)
  deploy/                  # Your deployment overlays
```

The CLI scaffolds this structure and manages it for you.

## Companion Repositories (For Reference Only)

- [moiraweave-core](https://github.com/moiraweave-labs/moiraweave-core): Runtime services and infrastructure templates. You do not need to clone this for normal usage.
- [moiraweave-steps](https://github.com/moiraweave-labs/moiraweave-steps): Official step catalog (optional). You consume steps by reference and version, not by cloning.
- [moiraweave-docs](https://github.com/moiraweave-labs/moiraweave-docs): Documentation.
- [.github](https://github.com/moiraweave-labs/.github): Org-wide templates and policies.
