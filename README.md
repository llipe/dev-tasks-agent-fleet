# Agent Fleet Control Plane

A personal, single-tenant control plane for operating autonomous agents that run on
**AWS Bedrock AgentCore** against the repositories of a GitHub organization. It replaces
the AWS console and manual CloudWatch Logs Insights queries with a structured execution
registry backed by **Supabase** as the system of record, with manual invocation and live
log tailing.

See [`docs/product-context.md`](docs/product-context.md) for the full problem statement and
[`docs/technical-guidelines.md`](docs/technical-guidelines.md) for the architecture and stack.

## Delivery phases

The project is delivered in two phases:

- **Phase 1 — Backend + Agent (current):** the Supabase schema, and the
  `dependency-update` agent that runs on AgentCore, authenticates to GitHub via a GitHub
  App, and reports its lifecycle/events back to Supabase (falling back to CloudWatch/stderr
  when the API is unreachable).
- **Phase 2 — Panel UI:** a Next.js app on Fly.io that visualizes runs (list, detail, live
  log tail via Supabase Realtime) and provides the schema-driven invocation form. The `panel`
  package is **scaffolded in the repo** (Next.js 15 App Router, React 19, TypeScript strict —
  issue #114 / S-101); routes, the invocation form, live tail, and Fly deployment land in later
  Phase 2 stories.

## Repository layout

```
.
├── Makefile                 # Repo-root aggregate — runs a Python branch AND a JS/TS branch (both must pass)
├── package.json             # Workspace root — canonical scripts delegate to `panel` via pnpm --filter
├── pnpm-workspace.yaml       # Workspace members: panel, agents/dependency-update/agentcore/cdk
├── TESTING.md               # Canonical testing contract (layers, commands, coverage)
├── DESIGN.md                # Nocturne design system for the Phase 2 panel
├── docs/                    # Product context, technical guidelines, PRDs, specs, ADRs
│   ├── product-context.md
│   ├── technical-guidelines.md
│   ├── reference/           # Schema DDL, seed, agent_reporter.py, credentials.ts
│   └── requirements/        # PRDs
├── panel/                   # Phase 2 Next.js (App Router) front-end — scaffolded in S-101
│   ├── app/                 # layout.tsx + page.tsx placeholders (DESIGN §1.2 Inter link)
│   ├── tests/               # Vitest unit/component/integration projects
│   └── README.md            # Panel-specific docs (scripts, conventions, SD2)
├── agents/
│   └── dependency-update/   # The active Phase 1 agent (Python, AgentCore Container)
│       ├── agentcore/       # Runtime config + CDK infra
│       ├── app/dependencyUpdate/   # Agent source, tests, Makefile, pyproject.toml
│       └── README.md        # Agent-specific docs (deployment, pipeline, env vars)
└── workstream/              # Task lists, specs, test plans, fidelity reports
```

The **active codebase** is the `dependency-update` Python agent under
`agents/dependency-update/app/dependencyUpdate/`. Agent-specific details (pipeline,
deployment, environment variables, runtime timeouts) live in
[`agents/dependency-update/README.md`](agents/dependency-update/README.md).

## Prerequisites

- **Python `>=3.13`** — the agent's dev/local runtime. CI runs a **3.13 + 3.14** matrix
  (3.14 is the AgentCore production runtime).
- **Node.js `>=22` and pnpm `10.11.0`** — for the Phase 2 `panel` package (workspace member).
- **`make`** — the canonical command surface.
- For local agent runs and deployment (see the agent README): the
  [AgentCore CLI](agents/dependency-update/README.md), Docker (ARM64), and the `gh` CLI.

## Getting started

Install both workspace branches — the Python agent package and the JS/TS `panel` package:

```bash
make install
```

`make install` runs both branches: the Python branch (`pip install -e '.[dev]'` in the agent
package — pytest, ruff, mypy, pip-audit) and the JS/TS branch (`pnpm install --frozen-lockfile`
for the workspace). Working inside a virtualenv is recommended for the Python side:

```bash
python -m venv agents/dependency-update/app/dependencyUpdate/.venv
source agents/dependency-update/app/dependencyUpdate/.venv/bin/activate
make install
```

## Key commands

Run these from the repository root. The aggregate targets now run **two branches** — the
Python agent package and the JS/TS `panel` package — and fail if either branch fails, so you
get the same behavior locally and in CI. Each branch is also runnable on its own with the
`-py` / `-js` suffix (e.g. `make validate-py`, `make validate-js`).

| Command             | What it does                                                        |
| ------------------- | ------------------------------------------------------------------- |
| `make install`      | Install both branches — `pip install -e '.[dev]'` (agent) + `pnpm install --frozen-lockfile` (workspace) |
| `make lint`         | Static analysis — `ruff check .` (Python) + `eslint` (panel)        |
| `make format-check` | Verify formatting — `ruff format --check .` (Python) + `prettier --check` (panel) |
| `make typecheck`    | Type analysis — `mypy .` (Python) + `tsc --noEmit` (panel)          |
| `make test`         | Run the full test suite — `python -m pytest` (Python) + `vitest run` (panel) |
| `make audit`        | Dependency vulnerability scan — `pip-audit . --strict` (Python) + `pnpm audit` (panel) |
| `make validate`     | **Aggregate quality gate** — Python branch + JS/TS branch, both must pass (fail-fast) |

`make validate` is the gate to run before opening or updating a PR — it mirrors exactly
what CI enforces.

### Running a subset of tests

Layer markers are applied automatically by directory (`tests/unit/` → `unit`,
`tests/component/` → `component`), so you can select layers from the agent package
directory:

```bash
cd agents/dependency-update/app/dependencyUpdate
make test-unit        # python -m pytest -m unit
make test-component   # python -m pytest -m component
```

See [`TESTING.md`](TESTING.md) for the full layer taxonomy, per-package commands, coverage
policy, and current structural gaps.

## Development workflow

- **Branches:** `issue/<number>-<short-description>` for single issues, `story/<id>-<short-description>`
  for user stories.
- **Commits:** [Conventional Commits](https://www.conventionalcommits.org/) (e.g.
  `feat(agent): ...`, `docs: ...`, `test(agent): ...`).
- **Pull requests:** open against `main`. **No agent or contributor pushes or merges
  directly to `main`** — changes land through a reviewed PR. Human PR review is the merge gate.
- **Quality gate:** run `make validate` before marking a PR ready. CI
  ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) re-runs the same gate on every
  push to `main` and every PR targeting `main`, across the 3.13 + 3.14 Python matrix.

## Continuous integration

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs two jobs on every push to
`main` and every PR targeting `main`, with no `paths:` filter:

- **`python-quality`** — the Python gate as explicit steps (lint → format-check → typecheck →
  test+coverage → audit) on a **Python 3.13 + 3.14** matrix.
- **`panel-quality`** — the JS/TS gate for the `panel` package (Node 22 + pnpm): lint →
  format:check → typecheck → test:coverage → audit.

There is currently no deploy-time gate; deployment is via the AgentCore CLI / CDK (Phase 1) and
Fly.io (Phase 2).

## Documentation map

| Document | Purpose |
| --- | --- |
| [`docs/product-context.md`](docs/product-context.md) | Problem statement, users, goals, roadmap, constraints |
| [`docs/technical-guidelines.md`](docs/technical-guidelines.md) | Stack, architecture patterns, data model, security, deployment |
| [`docs/adr/`](docs/adr/) | Architecture decision records — ADR-001 (LLM fix-agent escape hatch), ADR-002 (`open_pr` step + PR artifact), ADR-003 (run-metric fix), ADR-004 (`pg_cron` reaper schedule), ADR-005 (repeated `prompt`-unwrap + diagnostic), ADR-006 (long-step keep-alive + clock invariant) |
| [`docs/runbooks/`](docs/runbooks/) | Operator procedures requiring live AWS/Supabase access — deployment + E2E (#77), `pg_cron` reaper scheduling + stale-run verification (#94) |
| [`agents/dependency-update/README.md`](agents/dependency-update/README.md) | Agent pipeline, deployment, environment variables, timeouts |
| [`TESTING.md`](TESTING.md) | Testing contract — layers, commands, coverage, gaps |
| [`DESIGN.md`](DESIGN.md) | Nocturne design system for the Phase 2 panel |
