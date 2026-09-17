# Agent Fleet Control Plane

A personal, single-tenant control plane for operating autonomous agents that run on
**AWS Bedrock AgentCore** against the repositories of a GitHub organization. It replaces
the AWS console and manual CloudWatch Logs Insights queries with a structured execution
registry backed by **Supabase** as the system of record, with manual invocation and live
log tailing.

See [`docs/product-context.md`](docs/product-context.md) for the full problem statement and
[`docs/technical-guidelines.md`](docs/technical-guidelines.md) for the architecture and stack.

## Delivery phases

The project is delivered in three phases:

- **Phase 1 — Backend + Agent (done):** the Supabase schema (applied via Supabase CLI
  migrations), and the `dependency-update` agent that runs on AgentCore, authenticates to
  GitHub via a GitHub App, and reports its lifecycle/events back to Supabase (falling back
  to CloudWatch/stderr when the API is unreachable).
- **Phase 2 — Panel UI (deployed):** a Next.js app on Fly.io that visualizes runs (agents
  dashboard, run history, run detail with live log tail via Supabase Realtime/SSE) and
  provides the schema-driven invocation form. The panel requires a **Supabase password
  login** (`/login`, fail-closed middleware gate) and is **deployed and internet-reachable**
  at `https://dt-agent-fleet-panel.fly.dev`, with login — not network privacy — as the
  security boundary, mechanically asserted by the auth release gate on every deploy. See
  [ADR-007](docs/adr/ADR-007-auth-release-gate-replaces-privacy-gate.md) and
  [`docs/runbooks/panel-deployment.md`](docs/runbooks/panel-deployment.md).
- **Phase 3 — Security Analyst Agent (done, verified live):** the fleet's second agent,
  `agents/security-analyst/`, modeled on `dependency-update`. All 17 stories (S-125–S-141)
  are complete: the five-scanner pipeline (Semgrep, Gitleaks, Trivy, Checkov, CodeQL),
  cross-tool dedup, finding classification, and both `mode=audit_only` and `mode=fix`
  (deterministic fixers + a bounded LLM escape hatch, gated by a re-scan before any PR
  opens) are fully wired end-to-end. The agent is deployed, registered in
  `supabase/seed.sql`, and has been **verified live** with a real `audit_only` run and a
  real `fix` run that opened a PR, per
  [`docs/requirements/prd-security-analyst-agent.md`](docs/requirements/prd-security-analyst-agent.md)
  and [`agents/security-analyst/README.md`](agents/security-analyst/README.md).

## Repository layout

```
.
├── Makefile                 # Repo-root aggregate — runs a Python branch AND a JS/TS branch (both must pass)
├── package.json             # Workspace root — canonical scripts delegate to `panel` via pnpm --filter
├── pnpm-workspace.yaml       # Workspace members: panel, agents/dependency-update/agentcore/cdk
├── Dockerfile.panel          # Panel production image (Next.js `standalone`, built from repo root)
├── TESTING.md               # Canonical testing contract (layers, commands, coverage)
├── DESIGN.md                # Nocturne design system for the Phase 2 panel
├── docs/                    # Product context, technical guidelines, PRDs, specs, ADRs, runbooks
│   ├── product-context.md
│   ├── technical-guidelines.md
│   ├── adr/                 # Architecture decision records (ADR-001…ADR-007)
│   ├── runbooks/             # Operator procedures requiring live AWS/Supabase/Fly access
│   ├── requirements/         # PRDs
│   ├── prototype/            # High-fidelity Nocturne prototype (source for DESIGN.md)
│   └── reference/            # Non-canonical pointer stubs — schema/seed/reporter/credentials moved elsewhere; do not edit
├── supabase/                 # Canonical schema/seed — Supabase CLI migrations + seed.sql + config.toml
├── panel/                   # Phase 2 Next.js (App Router) front-end — deployed to Fly.io
│   ├── app/                 # Routes: `(panel)/` (authenticated, AppShell) + `login/` (public) + `api/`
│   ├── lib/                 # supabase/ (server data + auth clients), aws/ (credentials/invoke), auth/, domain/, sse/
│   ├── middleware.ts         # Fail-closed authorization chokepoint (getClaims(), never getSession())
│   ├── fly.toml              # Public HTTPS service — login is the boundary, see ADR-007
│   ├── scripts/              # panel-auth-check.mjs — the pure auth-gate parser
│   ├── tests/                # Vitest unit/component/integration projects + Playwright E2E
│   └── README.md            # Panel-specific docs (scripts, conventions, SD2, env vars)
├── scripts/                  # Repo-root operator scripts — verify-panel-auth.sh (release gate), cleanup-duplicates.sh
├── infra/                    # IAM policy documents (trust policy, invoke policy) for the Fly OIDC → AWS role
├── agents/
│   ├── dependency-update/   # The active Phase 1 agent (Python, AgentCore Container)
│   │   ├── agentcore/       # Runtime config + CDK infra
│   │   ├── app/dependencyUpdate/   # Agent source, tests, Makefile, pyproject.toml
│   │   └── README.md        # Agent-specific docs (deployment, pipeline, env vars)
│   └── security-analyst/   # Phase 3 agent (Python, AgentCore Container) — done, verified live
│       ├── agentcore/       # Runtime config + CDK infra
│       ├── app/securityAnalyst/   # Agent source, tests, Makefile, pyproject.toml
│       └── README.md        # Agent-specific docs (status, layout, deployment, env vars)
└── workstream/              # Task lists, specs, test plans, fidelity reports; archive/ holds completed work
```

The **active codebase** is the `dependency-update` Python agent under
`agents/dependency-update/app/dependencyUpdate/` (Phase 1), the `panel/` Next.js app
(Phase 2, deployed), and the `security-analyst` Python agent under
`agents/security-analyst/app/securityAnalyst/` (Phase 3, done and verified live, see
Delivery phases above). Agent-specific details (pipeline, deployment,
environment variables, runtime timeouts) live in
[`agents/dependency-update/README.md`](agents/dependency-update/README.md) and
[`agents/security-analyst/README.md`](agents/security-analyst/README.md).
Panel-specific details (scripts, conventions, env vars) live in [`panel/README.md`](panel/README.md).

## Prerequisites

- **Python `>=3.13`** — the agent's dev/local runtime. CI runs a **3.13 + 3.14** matrix
  (3.14 is the AgentCore production runtime).
- **Node.js `>=22` and pnpm `10.11.0`** — for the Phase 2 `panel` package (workspace member).
- **`make`** — the canonical command surface.
- For local agent runs and deployment (see the agent README): the
  [AgentCore CLI](agents/dependency-update/README.md), Docker (ARM64), and the `gh` CLI.
- For local panel dev, integration tests, and E2E (see [`panel/README.md`](panel/README.md)):
  the [Supabase CLI](https://supabase.com/docs/guides/local-development) (`supabase start` /
  `db reset` applies `supabase/migrations/` + `supabase/seed.sql`) and Docker.
- For panel deploys and the auth release gate (see
  [`docs/runbooks/panel-deployment.md`](docs/runbooks/panel-deployment.md)): the
  [`flyctl` CLI](https://fly.io/docs/flyctl/) and `curl`.

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
  format:check → typecheck → test:coverage → audit, plus a unit test of the auth release-gate
  parser (`panel-auth-check.mjs`) and a `shellcheck` of `scripts/verify-panel-auth.sh`.

CI does not deploy or run the live release gate against the deployed app — that is an
**operator-executed, deploy-time gate**: `scripts/verify-panel-auth.sh` runs after every panel
deploy and mechanically fails the release (exit non-zero) unless the deployed app enforces the
login boundary and rejects a test signup. See
[`docs/runbooks/panel-deployment.md`](docs/runbooks/panel-deployment.md) and
[ADR-007](docs/adr/ADR-007-auth-release-gate-replaces-privacy-gate.md). The
`dependency-update` agent deploys via the AgentCore CLI / CDK (Phase 1), also operator-executed.

## Documentation map

| Document | Purpose |
| --- | --- |
| [`docs/product-context.md`](docs/product-context.md) | Problem statement, users, goals, roadmap, constraints |
| [`docs/technical-guidelines.md`](docs/technical-guidelines.md) | Stack, architecture patterns, data model, security, deployment (canonical current-state doc — see its changelog for the full delivery history) |
| [`docs/adr/`](docs/adr/) | Architecture decision records — ADR-001 (LLM fix-agent escape hatch), ADR-002 (`open_pr` step + PR artifact), ADR-003 (run-metric fix), ADR-004 (`pg_cron` reaper schedule), ADR-005 (repeated `prompt`-unwrap + diagnostic), ADR-006 (long-step keep-alive + clock invariant), ADR-007 (auth release gate replaces the privacy gate — login is now the panel's security boundary) |
| [`docs/runbooks/`](docs/runbooks/) | Operator procedures requiring live AWS/Supabase/Fly access — [`panel-deployment.md`](docs/runbooks/panel-deployment.md) (Fly deploy, OIDC probe, auth release gate, go-public, **publishable-key credential cutover**), [`issue-77-deployment-e2e.md`](docs/runbooks/issue-77-deployment-e2e.md) (agent deploy + E2E, historical), [`issue-94-reaper-verification.md`](docs/runbooks/issue-94-reaper-verification.md) (`pg_cron` reaper scheduling + stale-run verification), [`issue-89-live-verification.md`](docs/runbooks/issue-89-live-verification.md) (invocation payload shape), [`issue-115-baseline-adoption.md`](docs/runbooks/issue-115-baseline-adoption.md) (Supabase CLI migration adoption), [`issue-116-english-sql-surface.md`](docs/runbooks/issue-116-english-sql-surface.md), [`issue-121-ac10-reaper-paused.md`](docs/runbooks/issue-121-ac10-reaper-paused.md) |
| [`docs/requirements/`](docs/requirements/) | PRDs — [`prd-dependency-update-agent.md`](docs/requirements/prd-dependency-update-agent.md) (Phase 1), [`prd-agent-fleet-panel-v2.md`](docs/requirements/prd-agent-fleet-panel-v2.md) (Phase 2), [`prd-panel-password-auth.md`](docs/requirements/prd-panel-password-auth.md) (the shipped auth wave), [`prd-panel-auth-and-rls.md`](docs/requirements/prd-panel-auth-and-rls.md) (deferred RLS hardening), [`prd-agent-fleet-panel-v3-ui-depth.md`](docs/requirements/prd-agent-fleet-panel-v3-ui-depth.md), [`prd-security-analyst-agent.md`](docs/requirements/prd-security-analyst-agent.md) (Phase 3, done) |
| [`docs/prototype/`](docs/prototype/) | High-fidelity Nocturne HTML prototype — the source `/DESIGN.md` was extracted from |
| [`docs/reference/`](docs/reference/) | Non-canonical pointer stubs (schema/seed moved to `supabase/`, `credentials.ts` moved to `panel/lib/aws/`) — kept only so historical links resolve; `agent_reporter.py` here is still the canonical copy source |
| [`agents/dependency-update/README.md`](agents/dependency-update/README.md) | Agent pipeline, deployment, environment variables, timeouts |
| [`agents/security-analyst/README.md`](agents/security-analyst/README.md) | Agent status (done, verified live as of S-141), pipeline, layout, deployment, environment variables |
| [`panel/README.md`](panel/README.md) | Panel scripts, conventions, env vars (incl. the publishable/anon auth-key pair), SD2 server-only boundary |
| [`TESTING.md`](TESTING.md) | Testing contract — layers, commands, coverage, gaps |
| [`DESIGN.md`](DESIGN.md) | Nocturne design system for the Phase 2 panel |
| [`workstream/`](workstream/) | Active specs, PRDs-in-progress, test plans, and traceability matrices still cited by the docs above; `workstream/archive/` holds completed task lists, fidelity reports, and other execution artifacts for merged work |
