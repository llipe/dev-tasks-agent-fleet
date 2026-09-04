# Fidelity Report — Story S-102 (Supabase CLI migration baseline adoption)

## Verdict

- **Fidelity: High**
- **Highest drift impact present: Minor**
- **Drift findings: 3 (all Minor)**
- **Scope:** issue #115 · PR #130 · branch `story/S-102-supabase-migrations` · repo `llipe/dev-tasks-agent-fleet`
- **Mode:** Audit (grey-box). Non-blocking — this audit does not gate PR/issue completion and does not replace the quality gates.

---

## Human-readable summary (what changed and why)

Story S-102 moved the project's database schema and seed data out of hand-run reference
files and into the Supabase CLI's migration system, so the database can be stood up and
reset with one command and the "source of truth" file can no longer silently drift from
what actually runs.

What was asked for was delivered, and I re-ran the important checks myself rather than
trusting the notes:

- The new migration file is a **byte-for-byte copy** of the previous schema, including the
  scheduled cleanup job ("reaper") that marks stuck runs as timed-out. Nothing was rewritten.
- The old reference copies were turned into short "this has moved — edit the real file
  instead" pointers, so no one can accidentally change a copy that never runs.
- I brought up the local database from scratch (`supabase db reset`): the schema built
  cleanly, all 7 tables are present, the read-time view and its `effective_status` column
  exist, the reaper function is callable, the scheduled job is registered on a once-a-minute
  cadence, and the seed loaded the expected 1 installation / 2 repositories / 1 agent.
  Loading the seed a second time changed nothing — it is safely repeatable.
- The new automated integration tests **run** (3 passed) when the local database is up, and
  **skip cleanly with a recorded reason** (exit 0, nothing fails) when the database is down.
  They are reachable from the project's single `make validate` command.
- The documentation was updated to say this test layer is now "configured" and to name the
  test harness.

The one thing that could **not** be checked directly was the live/hosted database: the
implementer did not have the live DB password, so the final "is the schedule still there and
is no row data touched?" spot-check on the hosted project was reasoned about rather than run.
This limitation is **disclosed honestly** in the runbook, with the exact commands an operator
should run to confirm. The registration step that was performed against live only writes a
history record and runs no schema changes, so the risk of that gap is low — but it remains an
unverified assertion, not a measurement.

Bottom line: the story does what it set out to do, the sensitive claims (verbatim copies,
"no-op" diff, "no DDL re-run") hold up under scrutiny, and the only open items are minor
wording/documentation drifts plus one honestly-flagged un-run live check.

---

## Per-AC results

| AC | Description | Codebase evidence | Workstream/doc evidence | Test / runtime evidence | Result |
|----|-------------|-------------------|--------------------------|--------------------------|--------|
| AC1 | Migration contains `001_schema.sql` verbatim incl. pg_cron + reap schedule | `diff origin/main:docs/reference/001_schema.sql` vs `supabase/migrations/20260902200101_initial_schema.sql` → **identical**; `create extension if not exists pg_cron` + `cron.schedule('reap-stale-runs','* * * * *', …)` present (uncommented) at file tail | task 1.19 records empty-diff verification | Migration applied cleanly on `db reset` | **Pass** |
| AC2 | `002_seed.sql` → `supabase/seed.sql`; both `docs/reference` copies replaced so they cannot drift | `diff origin/main:docs/reference/002_seed.sql` vs `supabase/seed.sql` → **identical**; both `docs/reference/00{1,2}_*.sql` are now pure comment stubs (**zero DDL/DML**) pointing at canonical files | task 1.4/1.5 | seed wired via `config.toml [db.seed] sql_paths = ["./seed.sql"]` | **Pass** (see D-2) |
| AC3 | `supabase start` + `db reset` bring up a stack matching the migration; seed idempotent | 7/7 public tables; `v_runs` view + `effective_status` column present; `reap_stale_runs()` → `0`; `cron.job` = `reap-stale-runs * * * * *`; seed = `1/2/1` | runbook "Local stack verification — PASS" | **Independently re-run in this audit**: `db reset` clean; all checks confirmed via `psql`; seed re-applied → still `1/2/1` (idempotent) | **Pass** |
| AC4 | `db diff` against live is a no-op; evidence recorded before apply | n/a (live) | Runbook records diff is **not byte-empty** (205 lines) but categorizes **all** lines as Supabase platform-managed state (84 default grants, 1 `rls_auto_enable()` trigger, 1 `drop extension pg_net`); **zero** touch our objects | Diff recorded before registration; decision not to author a corrective migration is reasoned | **Pass** (interpretation sound & honestly recorded — see analysis) |
| AC5 | `migration repair`/baseline marks live at baseline without re-running DDL, after explicit user confirmation | n/a (live) | Runbook: `supabase migration repair --status applied 20260902200101` writes only to `supabase_migrations.schema_migrations`; user approval recorded; `migration list --linked` shows version on Local **and** Remote; post-apply diff unchanged | `migration repair` is history-only by design — no DDL executed | **Pass** |
| AC6 | `test:integration` runs Vitest Layer 2.5 against local stack, reachable from `make validate`; may skip w/ recorded reason when Docker down | `panel/package.json` `test:integration`; `vitest.config.ts` `integration` project; `pg`/`@types/pg` in `package.json` + `pnpm-lock.yaml`; root + Makefile delegate to panel `validate` → `test` (`vitest run` runs ALL projects incl. integration) | TESTING.md wording (see D-1) | **Independently re-run**: stack up → 3 passed (executes); bare `test` includes integration project (4 passed total); stack down (bad port) → 4 skipped, exit 0, recorded reason | **Pass** (reachability holds via `test` aggregation — see D-1) |
| AC7 | TESTING.md Layer 2.5 row flips "not configured" → configured, naming harness | TESTING.md L31 taxonomy row + L64 panel package row both = **"configured (S-102 / #115)"**, naming Vitest `integration` project + Supabase CLI local Postgres | — | — | **Pass** |

**Business rules:** SD3 (adopt not rewrite; baseline records existing state) — upheld (verbatim migration + history-only repair). Apply gated on explicit user confirmation — upheld (no autonomous apply; user approval recorded). Reaper schedule remains registered after adoption — upheld (confirmed live locally: `reap-stale-runs * * * * *`).

---

## Analysis of the three flagged-sensitive areas

**(a) Verbatim migration & seed — CONFIRMED.** Byte-identical to the prior `docs/reference`
files via `git diff` against `origin/main`. pg_cron extension and `reap-stale-runs` schedule
present and uncommented. No drift.

**(b) "Schema-level no-op" interpretation — SOUND and HONESTLY RECORDED.** The runbook does
not hide that the diff is non-empty; it states "205 lines total", enumerates every category,
and asserts zero statements touch project-owned objects (tables, enums, indexes, `v_runs`,
`reap_stale_runs()`, RLS, the pg_cron schedule, the Realtime publication). All three residual
categories (default role grants, `rls_auto_enable()`, `drop extension pg_net`) are genuinely
Supabase-platform-managed artifacts of diffing a hosted project against a bare shadow DB —
this is a well-known CLI behavior. The explicit decision **not** to author a corrective
migration (and not to run the destructive `drop extension pg_net`) is the correct call. The
interpretation is defensible and transparently documented. No drift.

**(c) AC5 "without re-running DDL" — SATISFIED.** `supabase migration repair --status applied`
mutates only `supabase_migrations.schema_migrations` (the history table); it executes no schema
DDL by design. Corroborated by the identical pre/post-apply diff. Correct.

**(d) Gap between claimed and actual evidence — one honestly-disclosed un-run check.** The live
`cron.job` / row-count spot-check was **not** run (live DB password absent from the impl env).
This is explicitly flagged in the runbook and in task 1.18, argued "by construction + unchanged
post-apply diff", with operator SQL provided. This is not misrepresented as done — it is a
transparently recorded verification gap, not fabricated evidence. Captured as D-3 (Minor).

---

## Drift catalog

> All drift below is **non-blocking** to PR/issue completion (Audit Mode is additive).

**D-1 — TESTING.md overstates the `make validate` → integration path mechanism.**
- **Impact: Minor. Intent: Unintended.**
- TESTING.md L31 says the integration layer is "Reachable from the repo-root `make validate`
  JS/TS branch through `test:integration`." In reality `make validate` → panel `validate` →
  `test` (`vitest run`), which runs **all** Vitest projects (unit + component + integration)
  by aggregation; the `test:integration` script itself is **not** invoked anywhere in the
  validate chain. The reachability outcome is correct (verified: bare `test` runs the
  integration project), but the stated mechanism is inaccurate.
- **Evidence:** `panel/package.json` (`validate` calls `test`, not `test:integration`);
  `vitest.config.ts` projects; live run of bare `test` includes `|integration|` (4 passed).
- **Recommendation:** `technical-writer` — reword to "through the `test` project aggregation
  (`vitest run` executes the `integration` project)" or add `test:integration` to the panel
  `validate` chain if explicit invocation is desired. No code defect.

**D-2 — AC2 "links" delivered as pointer-comment stubs, not literal links/symlinks.**
- **Impact: Minor. Intent: Intended.**
- AC2 wording says the `docs/reference` copies are "replaced by links to the canonical files".
  Delivery replaced them with SQL comment stubs that name the canonical path and forbid adding
  DDL. This is functionally equivalent for the AC's actual intent (the canonical SQL cannot
  drift because the copies contain zero executable content), and arguably more robust than a
  symlink. Flagged only because the literal deliverable differs from the literal AC phrasing.
- **Evidence:** `docs/reference/001_schema.sql`, `docs/reference/002_seed.sql` (pure comments).
- **Recommendation:** No action needed (accept as intended), or `product-engineer` may adjust
  AC phrasing to "pointer stubs" for precision.

**D-3 — Live cron.job / row-count post-apply spot-check not empirically run.**
- **Impact: Minor. Intent: Intended (disclosed limitation).**
- The final direct confirmation on the **live** project (schedule still present; `runs`/
  `run_events` counts unchanged) was not executed because the live DB password was not in the
  implementation environment. Argued by construction (`migration repair` is history-only) plus
  the unchanged 205-line post-apply diff. Honestly recorded in the runbook with the exact
  operator SQL to close it.
- **Evidence:** runbook "Empirical live cron.job / row-count spot-check (optional). Not run…";
  task 1.18.
- **Recommendation:** `developer`/operator — run the two provided SQL statements against live
  when the DB password is available, and record the result, to convert the by-construction
  argument into a measurement. Low risk given the history-only nature of the applied step.

---

## Note on a related stale reference (not counted as S-102 drift)

`workstream/research-phase2-panel-spec-inputs-2026-08-27.md` still cites
`docs/reference/001_schema.sql` / `002_seed.sql` with specific line ranges (e.g. lines
234–251, 256–274) that no longer exist now that those files are ~14-line stubs. This is a
consequence of AC2 but lives in a **historical research input artifact**, not in an active
link contract, and predates this story. Recorded for awareness; recommend `product-engineer`/
`technical-writer` repoint those citations to `supabase/migrations/20260902200101_initial_schema.sql`
during the next Phase-2 doc pass. Not counted in the S-102 drift total.

---

## Recommendations summary

| Item | Owner | Action |
|------|-------|--------|
| D-1 | technical-writer | Correct TESTING.md wording re: `make validate` → integration mechanism |
| D-2 | product-engineer | Optional AC-phrasing precision ("pointer stubs"); otherwise no action |
| D-3 | developer/operator | Run the two live SQL confirmations when DB password available; record result |
| Stale research citations | technical-writer | Repoint line-anchored `docs/reference` citations to the migration file |
