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
moira init

moira workload new hermes \
  --type agent-service \
  --image ghcr.io/nousresearch/hermes-agent:latest \
  --mode session \
  --timeout-seconds 172800 \
  --adapter hermes \
  --port 8000 \
  --secret OPENAI_API_KEY \
  --persistence \
  --mount-path /data \
  --workspace-mount /workspace

moira deploy local
moira workload deploy hermes
moira workload status hermes
moira agent session create hermes
moira agent channel-message hermes telegram user-123 "hello"
```

## Command Surface

- `moira init`: create a MoiraWeave workspace.
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

- [moiraweave-core](https://github.com/moiraweave-labs/moiraweave-core): runtime services and infrastructure
- [moiraweave-ui](https://github.com/moiraweave-labs/moiraweave-ui): optional Ops dashboard
- [moiraweave-docs](https://github.com/moiraweave-labs/moiraweave-docs): documentation site
