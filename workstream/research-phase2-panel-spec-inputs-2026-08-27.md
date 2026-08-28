# Research — Phase 2 Panel Spec Inputs

## Changelog

| Version | Date       | Summary                                                                 | Author     |
| ------- | ---------- | ----------------------------------------------------------------------- | ---------- |
| 1.0     | 2026-08-27 | Initial research. Scoped to what the Phase 2 Next.js panel specification must build on: existing reference artifacts, the agent's live invocation contract, RLS/Realtime reachability, and the test-harness starting point. | researcher |

## Provenance

| Field | Value |
|---|---|
| Repository | `llipe/dev-tasks-agent-fleet` |
| Base branch | `phase2-work-preparation` |
| Commit SHA | `411b027ca259aa9493e2396c103aedb47feaf1dc` |
| Invoking agent | `product-engineer` |
| Research question | "What existing implementation and contracts must the Phase 2 Next.js panel specification build on, and where do those contracts disagree with the PRD?" |
| Date | 2026-08-27 |
| Multi-repo source | direct scanning (fallback) — no `component.json` in root; `dt` is on PATH but the repo is not catalog-registered |

## Answer first

The panel is greenfield — no `package.json`, no `app/`, no Next.js anywhere in the repo — but it is **not** unconstrained. It must build on four existing artifacts (`001_schema.sql`, `002_seed.sql`, `credentials.ts`, and the deployed agent's payload contract), and three of those disagree with the PRD in ways that will produce a wrong implementation if the spec copies the PRD verbatim:

1. **The agent expects `repository_org` + `repository_name` as flat top-level strings** (`main.py:64`), not a `repository_id` uuid and not `params.repository.full_name`. The PRD FR14 and the manual-config runbook both describe payloads the agent would reject as `INVALID_PARAMS`.
2. **RLS is deny-all with zero policies** (`001_schema.sql:332-338`, `grep -c "create policy"` → 0). A browser-side Supabase anon client reads nothing and receives no Realtime events. FR12 (live tail) has no working transport as specified.
3. **`002_seed.sql`'s `params_schema` is Spanish-language and omits `max_fix_attempts`**, which the agent accepts and clamps to 0..5 (`main.py:98-121`). Since the form renders *from* that schema, the panel would show Spanish labels and hide a real parameter.

## Relevance-ranked file map

| # | Path | Lines | Role | Why it matters |
|---|---|---|---|---|
| 1 | `agents/dependency-update/app/dependencyUpdate/main.py` | 64-121, 382-420 | Agent entrypoint, payload contract | Defines the exact invocation payload the panel must produce. `_REQUIRED_FIELDS = ("run_id", "repository_org", "repository_name")` |
| 2 | `docs/reference/001_schema.sql` | 234-251, 332-338 | `v_runs` view + RLS | `effective_status` logic the panel must read (FR11a); deny-all RLS that blocks browser reads |
| 3 | `docs/reference/credentials.ts` | 1-138 | AWS credential provider | The only front-end TypeScript that exists. Compiles standalone; the spec inherits it |
| 4 | `docs/reference/002_seed.sql` | 53-99 | `dependency-update` agent row | The `params_schema` that drives the invoke form. Spanish labels, missing `max_fix_attempts` |
| 5 | `docs/reference/001_schema.sql` | 212-213 | Realtime publication | `run_events` and `runs` are added to `supabase_realtime`. `v_runs` is **not** — Realtime cannot subscribe to a view |
| 6 | `docs/reference/001_schema.sql` | 11-23 | Enums | `run_status`, `run_outcome`, `log_level`, `artifact_type` — the panel's TypeScript types must mirror these exactly |
| 7 | `docs/reference/001_schema.sql` | 81-99 | `agents` table | Fields the dashboard lists; `params_schema`, `requires_repository`, timeout defaults (900/60/300) |
| 8 | `docs/reference/001_schema.sql` | 256-274 | `reap_stale_runs()` | Layer-1 reaper. Uses `for update skip locked`; the view is layer 2 |
| 9 | `docs/reference/agent_reporter.py` | 27-31, 175-186 | SDK env contract | `from_env()` requires `SUPABASE_SERVICE_ROLE_KEY` *in the environment* — reconciles the D15 confusion |
| 10 | `agents/dependency-update/app/dependencyUpdate/config.py` | 9-14 | Secret pointer | `SUPABASE_KEY_SECRET_ID` defaults to `agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY` |
| 11 | `agents/dependency-update/app/dependencyUpdate/main.py` | 411-415 | Startup secret fetch | Fetches key from Secrets Manager, then injects into `os.environ` — the pointer/value distinction |
| 12 | `TESTING.md` | 27-34, 63-65 | Test layer taxonomy | Records "no JS/TS application test package exists yet"; Playwright not configured |
| 13 | `docs/prototype/*.dc.html` | — | 6 prototype screens | Visual source of truth already codified into `/DESIGN.md` |
| 14 | `agents/dependency-update/agentcore/cdk/` | — | Existing TS package | The only `pnpm`/jest precedent in the repo (single CDK synth smoke test) |
| 15 | `Makefile` | 8-32 | Aggregate gate | `validate` = lint + format-check + typecheck + test-cov + audit. Python-only today |
| 16 | `workstream/pending-manual-config-dependency-update-agent.md` | §9 | E2E runbook | Contains the mismatched payload examples (see S2) |

## Slice findings

### S1 — Components / modules

The panel does not exist. Repo root has no `package.json`, no `app/`, no `lib/`, no `next.config.*`. Root contains only `DESIGN.md`, `Makefile`, `README.md`, `TESTING.md`, `agents/`, `docs/`, `scripts/`, `workstream/`.

Existing modules the panel will interact with, none of which it can import (Python, different runtime):

- `agents/dependency-update/app/dependencyUpdate/` — the agent. Boundary is the AgentCore HTTP invocation and the shared Supabase tables, not code.
- `agents/dependency-update/agentcore/cdk/` — TypeScript CDK app. The only existing JS/TS package; establishes `pnpm` + jest 29 (ts-jest) as in-repo precedent.
- `docs/reference/credentials.ts` — orphan module, no importer. Written for a `lib/aws/credentials.ts` destination per its header comment.

**Folder convention is undecided.** `technical-guidelines.md` §9 explicitly defers it ("defined when Phase 2 implementation begins... v1 does not impose a monorepo structure yet"). Since `agents/` occupies a top-level slot, the spec must choose whether the panel is `panel/`, `web/`, or root-level — and whether the repo becomes a pnpm workspace.

### S2 — APIs and contracts

**The agent's invocation contract (authoritative, from code):**

```
main.py:64   _REQUIRED_FIELDS = ("run_id", "repository_org", "repository_name")
```

All three must be present, of type `str`, and non-empty, or `validate_payload` returns `None` → `failed` / `not_applicable` / `INVALID_PARAMS` before any clone.

Optional: `params` (dict) and `base_branch` (`main.py:649`, defaults to `"main"`).

`params` accepts three keys, all defaulted by `apply_defaults` (`main.py:98-121`):

| Key | Default | Constraint |
|---|---|---|
| `fix_mode` | `audit_only` | — |
| `fail_on_findings` | `true` | — |
| `max_fix_attempts` | `3` | clamped to 0..5 |

**Three-way disagreement on payload shape:**

| Source | Repository is expressed as |
|---|---|
| `main.py:64` (authoritative) | `repository_org` + `repository_name`, flat top-level strings |
| PRD §12 params table | `repository_id` uuid, "first-class field, outside `params_schema`" |
| `pending-manual-config...md` §9 | `params.repository.full_name` — nested |

The runbook's E2E commands would fail validation as written. The PRD's `repository_id` is correct for the `runs` row (FK) but wrong for the invocation payload. The spec must define the panel's translation step: resolve `repository_id` → `repositories.full_name` → split on `/` → emit `repository_org`/`repository_name`.

**AgentCore `prompt` wrapper.** `unwrap_payload` (`main.py:67-82`) tolerates the payload nested as a JSON string under `prompt`, which is how the AgentCore CLI/SDK wraps it. The spec must determine whether `InvokeAgentRuntime` from `@aws-sdk` wraps or not — the agent handles both, so this is a low-risk unknown, but it affects the panel's serialization.

**No HTTP API contract exists for the panel.** No OpenAPI, no route handlers. `POST /api/agents/{slug}/invoke` (PRD §4) is entirely to be built. D16 (v2.1) means no auth middleware in front of it.

### S3 — UI surfaces

No implemented UI. Six prototype screens at `docs/prototype/*.dc.html` with a `_ds/` design-system directory and a `support.js`. These were already analyzed into `/DESIGN.md` v1.0 (see `workstream/research-ui-prototype-analysis-2025-01-27.md` — a prior research artifact covering the same prototype).

`/DESIGN.md` is complete enough to implement from without re-reading the HTML: tokens (§2), component inventory (§3, twelve components with props in §11.2), layout grids including exact `grid-template-columns` for both tables (§4.3, §4.4), and status→visual mapping (§8.1).

Token-consumption gap: `/DESIGN.md` §2.4 flags the four status colors (`--st-ok`, `--st-fail`, `--st-timeout`, plus accent/muted) as **not** in the Nocturne stylesheet — they are prototype-page-local and must be added to the app's global CSS. Easy to miss.

### S4 — Tests

`TESTING.md` is explicit that the front-end test surface is empty: E2E row reads "not configured — no frontend in repo (Next.js is Phase 2). No Playwright config" (line 32), and line 65 states "no JS/TS application test package exists yet."

The starting point the spec inherits:

- **Layer taxonomy already defined** (`TESTING.md` §Test Layers) with enforced boundaries — Layer 1 no I/O, Layer 2 mocked externals, Layer 2.5 real database, E2E Playwright. The panel's layers must slot into this existing taxonomy rather than invent a parallel one.
- **Canonical script names already mandated** (`TESTING.md` lines 96-97 reference `test:unit`, `test:integration`).
- **Aggregate gate is `make validate`** (Makefile:32), currently Python-only. Adding a JS/TS package requires wiring it into that target and into `.github/workflows/ci.yml`, or the package is unreachable from the gate — a defect class `TESTING.md` explicitly tracks.
- **`agentcore-cdk-app` precedent**: jest 29 + ts-jest, `pnpm test`, no coverage wired. Described as "listed for completeness and reachability accounting, not as a primary test target."
- **`tests/fixtures/` is empty** (only `.gitkeep`) — no recorded PostgREST payloads to reuse as panel fixtures.

Layer 2.5 (real database integration) is the natural home for `v_runs`/`effective_status` verification, and no such package exists yet.

### S5 — Data model

Fully specified in `001_schema.sql` (338 lines). Seven tables, six enums, the `v_runs` view, `reap_stale_runs()`, RLS.

**Not yet applied to any live Supabase project.** There is no `supabase/` directory and no `supabase/migrations/`. The schema lives only as a reference document under `docs/reference/`. Applying it is a manual SQL-Editor step (`pending-manual-config...md` §5, step 5).

This is a migration-tooling gap the spec must address: `001_schema.sql` / `002_seed.sql` are not migration artifacts under version-controlled tooling, they are documents. Two edits are already known to be needed (`runtime_arn` after deploy, `params_schema` corrections per S2), and there is no mechanism to apply a second migration without hand-editing.

**`v_runs` and RLS interact dangerously.** In PostgreSQL 15+, `security_invoker` defaults to `false`, so a view executes with its owner's privileges. A view created by the Supabase SQL Editor (owner `postgres`) therefore **bypasses RLS on its base tables**. Granting `anon` or `authenticated` SELECT on `v_runs` would silently defeat the deny-all posture that D11 establishes — exposing every column of `runs`, including `params` and `error_message`. If the spec exposes `v_runs` to a browser client, it must either create it with `security_invoker = true` plus explicit policies, or keep access server-side.

**Realtime cannot subscribe to `v_runs`.** Lines 212-213 add `run_events` and `runs` to the `supabase_realtime` publication. Views are not publishable. So FR11a (read `v_runs` for `effective_status`) and FR12 (Realtime live tail) use different sources: subscribe to `runs`/`run_events`, but derive displayed status from `v_runs` or recompute `effective_status` client-side. The spec must reconcile these two, or a run that times out while the user watches will keep showing `running` until refetch.

### S6 — Config / env / CI

| Item | State |
|---|---|
| Root `package.json` | absent |
| `pnpm-workspace.yaml` | absent |
| Linter / formatter for TS | none at root (`technical-guidelines.md` §12 confirms) |
| `Makefile` `validate` | Python-only: lint, format-check, typecheck, test-cov, audit |
| CI | `.github/workflows/ci.yml`, Python 3.13 + 3.14 matrix |
| `credentials.ts` env vars | `AWS_ROLE_ARN` (Fly only), `AWS_REGION`, `AWS_PROFILE` (local, optional), plus `FLY_APP_NAME` and `FLY_MACHINE_ID` read for detection |
| Panel Supabase env vars | undefined — no `.env.example` anywhere for the panel |

The panel needs `SUPABASE_URL` plus a key, and per S5 the key choice is constrained by RLS: with zero policies, only the service role key works, which cannot ship to a browser bundle. That forces server-side data access (server components or route handlers) as the default architecture — a consequence the PRD does not state.

### S7 — Relationships

See Relationships section below.

### S8 — Prior history

| Artifact | Relevance |
|---|---|
| `workstream/research-ui-prototype-analysis-2025-01-27.md` | Prior research on the same prototype; its output became `/DESIGN.md` v1.0. Overlaps S3 — not re-derived here |
| `docs/adr/ADR-001-llm-fix-agent-escape-hatch.md` | LLM fix loop + `verify_no_mandate_violation`. Panel-relevant only in that a `MANDATE_VIOLATION` run is `failed`/`needs_review` with no PR artifact |
| `docs/adr/ADR-002-open-pr-step-and-pr-artifact.md` | `open_pr` step + `pull_request` artifact — the artifact the run detail must surface, including on `failed` runs |
| `workstream/specification-prd-dependency-update-agent.md` | Phase 1 spec. The `§6.2` return-payload contract referenced by `build_return_payload` |
| `workstream/fidelity-report-{72,75,issue-76}.md` | Verifier audits of Phase 1 stories. No Phase 2 coverage |
| `workstream/pending-manual-config-dependency-update-agent.md` | Blocking infra runbook; its §9 payload examples are wrong (S2) |
| `docs/requirements/prd-dependency-update-agent.md` | Child PRD for the agent; source of the `MAJOR_UPDATE_REQUIRED` case the panel must render |
| Issue #77 | Deploy + E2E + `runs.metrics` persistence. Panel E2E depends on it |

No prior `/workstream` artifact covers the Next.js panel. This is genuinely unexplored territory in the repo's history.

## Relationships

**Dependency direction.** The panel is downstream of everything and upstream of nothing. It reads tables the agent writes, and invokes a runtime the agent implements. No code dependency exists in either direction — the coupling is entirely through (a) the Supabase schema and (b) the AgentCore payload contract.

**Blast radius of Phase 2 work:** essentially zero on existing code. Nothing imports `credentials.ts`. No Python module reads anything the panel would produce. The panel can be built without touching `agents/`.

**Two exceptions where Phase 2 forces upstream change:**

1. `002_seed.sql` must be edited — English `params_schema` labels, add `max_fix_attempts` — which means re-running the seed against the live database. Touches the agent's runtime behavior via `apply_defaults` only if the panel starts sending `max_fix_attempts`.
2. `Makefile` `validate` and `.github/workflows/ci.yml` must gain a JS/TS branch, or the panel's tests are unreachable from the aggregate gate.

**Shared-clock coupling.** `agents.max_runtime_seconds` (900), `grace_seconds` (60), and `start_timeout_seconds` (300) are snapshotted into each `runs` row by the panel at dispatch (FR14c) and then read by both `reap_stale_runs()` and `v_runs`. A panel bug that omits the snapshot breaks the reaper silently — the run never resolves to a terminal state. `001_schema.sql` gives these columns defaults on `agents` but the spec should confirm whether `runs` has non-null constraints on them.

## Risks and gotchas

1. **RLS deny-all makes the naive browser-client architecture non-functional.** The obvious Supabase + Next.js pattern (anon key in the browser, `supabase-js` subscription) returns zero rows and zero Realtime events. Discovered only at runtime, and it looks like a Realtime misconfiguration rather than an authorization result.
2. **Granting `anon` access to `v_runs` silently bypasses RLS** (PG15 `security_invoker` defaults false). The "fix" for gotcha 1 that a developer reaches for first is the one that quietly exposes `runs.params` and `runs.error_message` to anyone. Combined with D16 (no auth), that is public exposure if the Fly app is ever made public.
3. **Payload contract drift will produce `INVALID_PARAMS` on the first real invocation.** Three documents describe three shapes; only `main.py:64` is authoritative. The runbook's copy-pasteable commands are among the wrong ones.
4. **Realtime source ≠ display source.** Subscribing to `runs` while displaying `v_runs.effective_status` means a live-updating row can regress to a stale status on push. Needs an explicit reconciliation rule.
5. **`params_schema` is Spanish.** The form renders labels from it, so the panel would violate the repository's English-only rule through data, not code — invisible to any linter.
6. **`max_fix_attempts` is accepted by the agent but absent from `params_schema`**, so the schema-driven form cannot expose it. This is exactly the R4 drift class the PRD predicted, already present before the panel exists.
7. **No migration tooling.** `001_schema.sql` is a document, not a migration. There is no `supabase/migrations/`, so the seed corrections in gotchas 5-6 have no versioned path to production.
8. **`credentials.ts` has an unverified token-extraction fallback.** `parsed.value ?? parsed.token ?? parsed.aud` (line 60) guesses at three field names and falls through to the raw body. `parsed.aud` is almost certainly wrong — `aud` is the audience, not a token. This is the empirically-unverified item Open Question #5 tracks, and the fallback would silently send an audience string to STS as a web identity token.
9. **`credentials.ts` comments are Spanish** and it targets a `lib/aws/credentials.ts` path that does not exist. Adopting it requires translation and relocation, not just a copy.
10. **`agentcore-cdk-app` sets a weak jest precedent.** It has no coverage wiring. Following it for the panel would produce a package that passes `pnpm test` while measuring nothing.

## External sources

None. This research was codebase-only. The one question that would benefit from external verification — the Fly OIDC socket response shape — cannot be resolved from documentation with confidence and requires probing a live Machine (Open Question #5 in the PRD).

## Not investigated

- **`docs/prototype/*.dc.html` internals.** Not re-read; `/DESIGN.md` v1.0 and `research-ui-prototype-analysis-2025-01-27.md` already cover them. If `/DESIGN.md` is found lacking during spec authoring, the HTML is the fallback.
- **`001_schema.sql` lines 108-233** (full `runs`, `run_steps`, `run_events`, `run_artifacts` column lists and indexes). Sampled, not exhaustively transcribed — the PRD §9 ER diagram already enumerates them. Null constraints on the snapshot columns are unconfirmed (see Relationships).
- **`agent_reporter.py` write sequencing** (buffering, `seq` monotonicity, retry). Read only for the env-var contract. Matters for what the panel *sees* arriving, but no panel decision depends on it.
- **`reap_stale_runs()` lines 274-330.** Confirmed it exists and the two clocks; did not verify the `run_event` explanation rows it writes, which the run detail will display.
- **`.github/workflows/ci.yml`** not opened. Its existence and Python matrix are quoted from `TESTING.md` and `technical-guidelines.md`, not verified directly.
- **`scripts/`** directory contents not examined.
- **Live Supabase project state.** Cannot be inspected — no credentials used, and per `pending-manual-config...md` the schema is likely not applied at all.
- **Whether `InvokeAgentRuntime` via `@aws-sdk` wraps payloads in `prompt`.** Requires either SDK source reading or a live call. `unwrap_payload` tolerates both, so this was deprioritized.

## Confidence

**High** on the contract findings — the payload mismatch (S2), zero RLS policies (S5), Spanish `params_schema` and missing `max_fix_attempts` (S5, gotchas 5-6), and the empty front-end test surface (S4) are all read directly from source with line references, and each is independently verifiable in seconds.

**Medium** on the `v_runs` RLS-bypass claim (gotcha 2). The PostgreSQL `security_invoker` default is well-established, but the actual view owner depends on how the SQL is executed against Supabase, which cannot be confirmed without a live project. Treat as a hazard to design against rather than a confirmed defect.

**Low** on anything concerning the Fly OIDC endpoint. `credentials.ts` itself flags this (line 57 embeds a `curl` command to verify the shape), the PRD tracks it as an open question, and no Fly Machine was available. Gotcha 8 is a code-reading inference, not an observed failure.
