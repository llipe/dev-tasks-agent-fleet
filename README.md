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
  log tail via Supabase Realtime) and provides the schema-driven invocation form. Not yet
  in the repository.

## Repository layout

```
.
├── Makefile                 # Repo-root aggregate — delegates to the active package
├── TESTING.md               # Canonical testing contract (layers, commands, coverage)
├── DESIGN.md                # Nocturne design system for the Phase 2 panel
├── docs/                    # Product context, technical guidelines, PRDs, specs, ADRs
│   ├── product-context.md
│   ├── technical-guidelines.md
│   ├── reference/           # Schema DDL, seed, agent_reporter.py, credentials.ts
│   └── requirements/        # PRDs
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
- **`make`** — the canonical command surface.
- For local agent runs and deployment (see the agent README): the
  [AgentCore CLI](agents/dependency-update/README.md), Docker (ARM64), and the `gh` CLI.

## Getting started

Install the active package and its dev tooling (pytest, ruff, mypy, pip-audit):

```bash
make install
```

This delegates to the agent package and runs `pip install -e '.[dev]'`. Working inside a
virtualenv is recommended:

```bash
python -m venv agents/dependency-update/app/dependencyUpdate/.venv
source agents/dependency-update/app/dependencyUpdate/.venv/bin/activate
make install
```

## Key commands

Run these from the repository root. Each target delegates to the active package's
`Makefile`, so you get the same behavior locally and in CI.

| Command             | What it does                                                        |
| ------------------- | ------------------------------------------------------------------- |
| `make install`      | Install the package with dev dependencies (`pip install -e '.[dev]'`) |
| `make lint`         | Static analysis — `ruff check .`                                    |
| `make format`       | Auto-format — `ruff format .`                                       |
| `make format-check` | Verify formatting without writing — `ruff format --check .`         |
| `make typecheck`    | Type analysis — `mypy .`                                            |
| `make test`         | Run the full test suite — `python -m pytest`                        |
| `make test-cov`     | Tests with coverage — `python -m pytest --cov --cov-report=term-missing` |
| `make audit`        | Dependency vulnerability scan — `pip-audit . --strict`              |
| `make validate`     | **Aggregate quality gate** — lint + format-check + typecheck + test-cov + audit (fail-fast) |

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

CI runs the Python quality gate as explicit steps — lint → format-check → typecheck →
test+coverage → audit — on a **Python 3.13 + 3.14** matrix. There is currently no
deploy-time gate; deployment is via the AgentCore CLI / CDK (Phase 1) and Fly.io (Phase 2).

## Documentation map

| Document | Purpose |
| --- | --- |
| [`docs/product-context.md`](docs/product-context.md) | Problem statement, users, goals, roadmap, constraints |
| [`docs/technical-guidelines.md`](docs/technical-guidelines.md) | Stack, architecture patterns, data model, security, deployment |
| [`docs/adr/`](docs/adr/) | Architecture decision records — ADR-001 (LLM fix-agent escape hatch), ADR-002 (`open_pr` step + PR artifact), ADR-003 (run-metric fix), ADR-004 (`pg_cron` reaper schedule) |
| [`docs/runbooks/`](docs/runbooks/) | Operator procedures requiring live AWS/Supabase access — deployment + E2E (#77), `pg_cron` reaper scheduling + stale-run verification (#94) |
| [`agents/dependency-update/README.md`](agents/dependency-update/README.md) | Agent pipeline, deployment, environment variables, timeouts |
| [`TESTING.md`](TESTING.md) | Testing contract — layers, commands, coverage, gaps |
| [`DESIGN.md`](DESIGN.md) | Nocturne design system for the Phase 2 panel |
