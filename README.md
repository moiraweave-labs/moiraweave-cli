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
mkdir my-moiraweave-workspace
cd my-moiraweave-workspace
moira up
moira agent chat demo-agent "hello from the CLI" --watch
```

`moira up` initializes the workspace if needed, creates a no-secret demo agent
when there are no workloads, writes a local `docker-compose.yml` with the Ops
dashboard enabled, generates workload Compose services, runs `moira doctor`,
starts API, worker, storage, UI, and workloads, waits for readiness, and
registers local deployment records. The dashboard is available at
`http://localhost:3000`.
Open `http://localhost:3000/agents` after sign-in to land directly in the
agent console; the first agent and any existing session are selected
automatically.

Use `moira doctor` whenever the local stack does not start cleanly:

```bash
moira doctor
moira doctor --json
```

For development or private registries, override platform images in `.env`:
`MOIRAWEAVE_API_GATEWAY_IMAGE`, `MOIRAWEAVE_WORKER_IMAGE`, and
`MOIRAWEAVE_UI_IMAGE`.

Official platform images are built and pushed by GitHub Actions. For a clean
first run without `docker login ghcr.io`, the GHCR packages must also be public:
`moiraweave/api-gateway`, `moiraweave/worker`, and `moiraweave-ui`.

Start from another agent template when you want the first run to be a real
runtime instead of the demo:

```bash
moira up --agent hermes
moira up --agent openclaw
moira up --agent external-agent --agent-endpoint https://agent.example.com
```

Hermes/OpenClaw templates validate required secrets before Docker starts. Add
them to `.env` or export them in the shell. Use `moira up --agent demo-agent`
for a no-secret first run.

## Command Surface

- `moira init`: create a MoiraWeave workspace.
- `moira up --agent demo-agent|hermes|openclaw|generic-http-agent|external-agent`: initialize if needed, start the local stack, and register workloads.
- `moira doctor`: diagnose local onboarding blockers before Docker starts.
- `moira demo agent`: create a no-secret mock agent workload.
- `moira workload new|list|show|deploy|status|logs`: manage workload manifests.
- `moira run submit|watch|cancel|events|artifacts`: operate workload runs.
- `moira agent chat`: create a session if needed and send one message.
- `moira agent session create|message|history`: interact with agent sessions.
- `moira agent channel-message`: simulate Telegram, Slack, Discord, or webhook ingress. The channel must be listed in the agent workload's `spec.agent.exposedChannels`.
- `moira deploy local|k8s`: generate Compose or Helm values from workload manifests.

Use `--channel` for channels MoiraWeave owns through its API gateway. Use
`--external-channel telegram` when the agent runtime owns Telegram directly and
MoiraWeave should only supervise the workload.

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
