# MoiraWeave CLI

Developer CLI for creating and operating MoiraWeave workspaces.

MoiraWeave is a self-hosted operations platform for AI workloads: model
services, pipelines, and agent runtimes. The CLI owns the local user workflow:
workspace init, workload manifests, runs, agent sessions, and deployment asset
generation.

## Install

```bash
uv tool install moiraweave-cli
moira --help
```

## Quickstart

```bash
moira up
```

`moira up` initializes the workspace if needed, creates a no-secret demo agent
when there are no workloads, writes a local `docker-compose.yml` with the Ops
dashboard enabled, generates workload Compose services, starts API, worker,
storage, UI, and workloads, waits for readiness, and registers local deployment
records. The dashboard is available at `http://localhost:3000`.

Use `--deployment-mode external --endpoint <url>` for an agent runtime that is
already deployed outside MoiraWeave.

## Command Surface

- `moira init`: create a MoiraWeave workspace.
- `moira up`: initialize if needed, start the local stack, and register workloads.
- `moira demo agent`: create a no-secret mock agent workload.
- `moira workload new|list|show|deploy|status|logs`: manage workload manifests.
- `moira run submit|watch|cancel|events|artifacts`: operate workload runs.
- `moira agent session create|message|history`: interact with agent sessions.
- `moira agent channel-message`: simulate Telegram, Slack, Discord, or webhook ingress.
- `moira deploy local|k8s`: generate Compose or Helm values from workload manifests.

## Workspace Model

```text
your-workspace/
  moiraweave.yaml
  .env
  .moiraweave/
    workloads/
    artifacts/
    deploy/
```

Workloads are ordinary YAML manifests. MoiraWeave deploys and observes the
runtime, but model and agent internals stay inside the workload image.

## Development

```bash
uv sync --frozen
uv run ruff check moira_cli tests
uv run mypy moira_cli
uv run pytest
```

## Related Repositories

- [moiraweave](https://github.com/moiraweave-labs/moiraweave): runtime services and infrastructure
- [moiraweave-ui](https://github.com/moiraweave-labs/moiraweave-ui): integrated Ops dashboard
- [moiraweave-docs](https://github.com/moiraweave-labs/moiraweave-docs): documentation site
