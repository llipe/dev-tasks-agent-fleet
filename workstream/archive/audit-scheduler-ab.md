# Fidelity Audit — Agent Scheduler Waves A–B (S-149…S-154 / #261–#266)

> **Mode:** Audit (grey-box, post-merge). **Scope:** issues #261 #262 #263 #264
> #265 #266, PRD `docs/requirements/prd-agent-scheduler.md`, delivered via
> integration PR #296 (merged 2026-10-14). **Verified against `main` @
> `e5dbbbe`** — PR states deliberately NOT trusted (several story PRs are CLOSED,
> all issue checkboxes unticked). Read-only; no code/issue mutation.
> **Date:** 2026-10-15.

## 1. Header / Verdict

| | |
| --- | --- |
| **Overall fidelity** | **High** |
| **Highest drift impact** | **Minor** |
| **Scope** | S-149…S-154 (Waves A–B), PR #296, `main` @ e5dbbbe |
| **Per-issue verdict** | #261 CLOSE · #262 CLOSE · #263 CLOSE · #264 CLOSE · #265 CLOSE · #266 CLOSE-WITH-FOLLOW-UP |

Every acceptance criterion across the six issues is implemented on `main` and
backed by a test at the layer the story specified. L1 unit tests were re-run
here and pass (38/38). L2.5 integration + E2E suites are not re-run locally (per
instructions — no local Supabase/E2E), but the files exist, are
`REQUIRE_LOCAL_DB=1`-gated (skip→fail in CI), and CI passed on `58c1d1c` and
later; production evidence (2026-10-15 Fly logs) independently confirms the live
fire path and the internal-401 boundary. No Critical/Major drift. Two Minor
items (one test-rigor gap, one scope/plan-vs-code nuance) are catalogued as
non-blocking follow-ups.

## 2. Human-readable summary (what changed and why)

Waves A–B lay the scheduler's foundation and its trigger path. The database now
has two new tables — `schedules` (what to run, how often, in which timezone) and
`notifications` (a durable record of notable events) — both locked down so only
the server can read them. A set of database functions works out *when* a
schedule should next fire, correctly handling timezones and daylight-saving
shifts, and understands cron expressions for advanced cases. A once-a-minute
database job finds schedules that are due, respects a cap on how many can run at
once (default 3), and calls a new, secret-protected internal web endpoint that
actually launches the agent — reusing the exact same "record the run first, then
invoke" path a human click already uses, so a scheduled run that fails to start
is just as visible as a manual one. The internal endpoint rejects any call
without the right secret, which the release gate now proves on every deploy.

In plain terms: the plumbing to make agents run on a timer is built, secured,
and proven both by tests and by two real production firings on 2026-10-15. The
only loose ends are housekeeping, not behavior: one integration test proves
"deny-all" on the two new tables only through a generic table sweep rather than
seeding those specific tables, and one acceptance line ("a missed slot records a
miss") is satisfied by the no-catch-up cursor advance rather than by a dedicated
`last_skipped_reason='missed'` write. Neither affects whether the scheduler
works.

## 3. Per-issue AC results

### Issue #261 — S-149: schedules + notifications schema, enums, RLS

| AC | Verdict | Evidence |
| --- | --- | --- |
| Migration applies cleanly on `supabase db reset` | **MET** | `supabase/migrations/20261013160000_scheduler_schema.sql` (enums, both tables, indexes, `set_updated_at` trigger); applied by CI reset; L2.5 `schedules-schema.test.ts:48-70` asserts tables + enums present. |
| Both tables RLS deny-all (anon 0 rows, non-vacuous guard) | **PARTIAL** | `20261013160000…sql:` `alter table schedules/notifications enable row level security` (no policies = deny-all). `rls-deny-all.test.ts:48-56,96-110` enumerates base tables from `information_schema` (so both new tables are swept) — but the non-vacuous guard (`:84-92`) seeds/asserts only `agents`; `schedules`/`notifications` are empty, so the zero-rows assertion for *those two* tables is vacuous. Deny-all is structurally present; the AC's table-specific non-vacuous guard is not. |
| `chk_schedule_cadence` rejects each malformed kind/field combo | **MET** | Check constraint `20261013160000…sql` (per-kind CASE); L2.5 `schedules-schema.test.ts:98-131` rejects daily/null-minute, weekly/null-weekday, every_n_hours/interval<1, advanced/null-cron; accepts a well-formed daily. |
| `uq_notifications_run_kind` rejects duplicate `(run_id, kind)` | **MET** | Unique constraint in migration; L2.5 `schedules-schema.test.ts:135-162` rejects a dup `(run_id,'run_failed')`, allows a different kind for the same run. |

**Overall: CLOSE.** All four ACs implemented; the one PARTIAL is a test-rigor
gap, not a behavior defect — RLS is enabled deny-all identically to every other
table.

### Issue #262 — S-150: buildRunInsert trigger descriptor

| AC | Verdict | Evidence |
| --- | --- | --- |
| Manual descriptor → exact prior row shape (`manual`/`panel`) | **MET** | `panel/lib/domain/run-insert.ts` `TriggerDescriptor` + `buildRunInsert`; L1 `run-insert.test.ts:34-57` asserts byte-identical row via full `toEqual`. Re-run here: pass. |
| Schedule descriptor → `schedule` / `schedule:<id>` | **MET** | `run-insert.ts` writes `input.trigger.triggerType/triggeredBy`; L1 `run-insert.test.ts:59-73`. |
| Malformed `schedule:` identity rejected at the type level | **MET** | `triggeredBy: \`schedule:${string}\`` template-literal union in `run-insert.ts`; `tsc --noEmit` (panel-quality CI) enforces it. Compile-time, not a runtime test — correct for a type-level AC. |
| Existing invoke-route tests pass unchanged | **MET** | Manual route passes `{manual, panel}`; CI `panel-quality` green on 58c1d1c+ with the full invoke-route suite. |

**Overall: CLOSE.** Fully met.

### Issue #263 — S-151: pg_net + Vault + DB settings (migration + runbook)

| AC | Verdict | Evidence |
| --- | --- | --- |
| `pg_net` present after reset | **MET** | `20261013161000_scheduler_pgnet_vault.sql` `create extension if not exists pg_net`; L2.5 `scheduler-extensions.test.ts:30-39` asserts `pg_net`+`supabase_vault` installed. |
| `vault.read_secret('scheduler_trigger_secret')` resolves locally | **MET** | `scheduler.read_secret()` wrapper + dev bootstrap `set_secret('scheduler_trigger_secret',…)` in migration; L2.5 `scheduler-extensions.test.ts:57-66` resolves a non-empty secret; `:68-75` returns null for unknown. (Impl wraps Vault's `decrypted_secrets` under `scheduler.read_secret`, matching the AC's intent.) |
| Runbook documents each privileged step | **MET** | `docs/runbooks/scheduler-deployment.md` exists (delivered same PR, FR-49a); migration embeds the operator steps (enable extensions, `set_secret` + `fly secrets`, `scheduler.config` overrides). |

**Overall: CLOSE.** Fully met. (Settings are a `scheduler.config` table + typed
readers rather than `app.*` GUCs — a documented, intended deviation because the
migration role cannot `ALTER DATABASE SET app.*` on hosted Supabase; the L2.5
test reads them back. Intended drift, Minor, no AC impact.)

### Issue #264 — S-152: compute_next_run_at + cron + RPC

| AC | Verdict | Evidence |
| --- | --- | --- |
| Daily/weekly presets → correct UTC on both sides of DST (AC1) | **MET** | `20261013162000_scheduler_compute_next_run.sql` (all five kinds via `at time zone`); L2.5 `compute-next-run.test.ts:76-99` — Santiago daily 07:00 = 11:00Z (UTC-4 July) vs 10:00Z (UTC-3 Dec), the UTC instant shifts across DST. |
| `every_n_hours` chains from `last_fired_at` | **MET** | migration `every_n_hours` branch coalesces `last_fired_at`; L2.5 `compute-next-run.test.ts:146-156` (06:00+6h=12:00Z after a 09:00 from). |
| `advanced` cron matches/rejects per grammar; unparseable → null + surfaced | **MET** | `cron_field_matches`/`cron_matches` closed grammar; L2.5 `compute-next-run.test.ts:159-220` (Mon 04:00, `*/15`, leap-only `0 0 29 2 *`→2028, bad field→null, wrong arity→null) + grammar matrix `:222-249`. L1 `cadence.test.ts` covers the TS pre-validator (reject-before-save). |
| RPC returns same values as direct computation | **MET** | `scheduler.preview_next_runs` + `public.scheduler_preview_next_runs` wrapper; L2.5 `compute-next-run.test.ts:251-283` asserts RPC parity (3 chained instants) + empty for invalid cron. |

**Overall: CLOSE.** Fully met; OQ-S2 resolved (advanced cron in schedule tz,
baked in and tested).

### Issue #265 — S-153: fire endpoint + shared-secret internal route class

| AC | Verdict | Evidence |
| --- | --- | --- |
| Unauth/wrong-secret → 401 (not 404/409) (AC3) | **MET** | `fire/route.ts:` auth is step 1, 401 before any DB work; `internal-secret.ts` constant-time `timingSafeEqual` fail-closed. L1 `fire-route.test.ts:118-131` (401, `getScheduleById` NOT called) + `internal-secret.test.ts`. Live: release-gate check 5 (`verify-panel-auth.sh:269-278`, `panel-auth-check.mjs:290` `checkInternalRejected`) passed in panel-v1.2.0; Fly log one `UNAUTHORIZED` then correct behavior. Re-run here: pass. |
| Correct secret fires run with `schedule`/`schedule:<id>` (AC2) | **MET** | `fire/route.ts` step 6 builds the schedule descriptor; L1 `fire-route.test.ts:146-166` asserts insert-before-invoke + descriptor; L2.5 `fire-insert.test.ts:97-126` asserts the real row. Live: schedules 2be98399… (14:48Z), face0cae… (15:08Z) `queued_row_inserted→fired`. |
| Invoke throw marks `failed_to_start` | **MET** | `fire/route.ts` catch → `markRunFailedToStart` + `recordScheduleFireFailure`; L1 `fire-route.test.ts:178-192` (502, markFailed called, counter incremented, `recordScheduleFired` NOT called). |
| Stale/disabled schedule → 409 | **MET** | `fire/route.ts` step 2 (`!is_enabled || state!=='active' || absent → 409`); L1 `fire-route.test.ts:134-144` (disabled/paused/absent all 409, no insert). |
| Secret never in logs | **MET** | `logFire()` emits a fixed field set, no secret; `internal-secret.ts` reasons are fixed strings; `internal-secret.test.ts:` "never surfaces secret material". |

**Overall: CLOSE.** All five ACs met in code + tests + live. E2E unauth-401 spec
present (`tests/e2e/`), CI green, release gate live-asserts the boundary.

### Issue #266 — S-154: fire_due_schedules tick + G4 cap + G2 no-catch-up

| AC | Verdict | Evidence |
| --- | --- | --- |
| 5 due / cap 3 → 3 dispatch, 2 skipped `concurrency_cap`, re-eval next tick (AC7) | **MET** | `20261013163000_scheduler_fire_due.sql` (budget = cap − in_flight, over-cap → `last_skipped_reason='concurrency_cap'`, cursor NOT advanced); L2.5 `fire-due-schedules.test.ts:103-126` (3 fired/2 skipped) + `:128-137` (next tick fires the remainder). |
| Due time passed while down → next future occurrence only, miss recorded (AC5/G2) | **PARTIAL** | No-catch-up MET: cursor advances via `compute_next_run_at(id, now())` to a FUTURE instant, never replaying a missed slot; L2.5 `fire-due-schedules.test.ts:94-101` asserts `next_run_at > now()`. The explicit **"miss recorded"** half has no dedicated write/assertion — a dispatched recovery clears `last_skipped_reason` to null rather than recording a `missed` reason; a down-path recovery leaves no distinct miss marker. Behavior (no burst) is correct; the audit-trail "miss recorded" is not materialized. |
| `next_run_at` advances monotonically | **MET** | cursor set to the strictly-future `compute_next_run_at(now())`; `fire-due-schedules.test.ts:94-101`. Bootstrap handled by `20261013170000_scheduler_seed_next_run.sql` (BEFORE trigger seeds a null cursor — a live step-6 bug fix). |
| Stale `running` counts against cap ≤ one tick (safe over-count) | **MET** | `in_flight_scheduled_runs()` counts `status in ('queued','running')` without re-deriving effective_status (documented safe over-count, SD-G4); reaper converges within a tick. Asserted indirectly by the cap matrix; no dedicated stale-overcount L2.5 case. |

**Overall: CLOSE-WITH-FOLLOW-UP.** The tick, G4 cap, and G2 no-catch-up all work
and are tested; the only gap is AC5's "miss recorded" audit half (Minor,
Undetermined intent — the spec/plan emphasize no-catch-up behavior, and the code
delivers that, but the literal "miss recorded" wording is not satisfied by a
distinct marker).

## 4. Drift catalog

All drift below is **non-blocking** to issue/PR completion (verifier audits are
additive and do not gate).

| # | Issue/AC | Description | Impact | Intent | Evidence |
| --- | --- | --- | --- | --- | --- |
| D1 | #261 AC2 | RLS deny-all on `schedules`/`notifications` is proven only via the generic `information_schema` table sweep; the non-vacuous seeded guard seeds `agents` only, so the zero-rows assertion for the two new tables is vacuous (empty tables). | Minor | Unintended | `rls-deny-all.test.ts:84-110` |
| D2 | #266 AC5 | "miss recorded" audit half not materialized: a down-path recovery advances the cursor (correct no-catch-up) but writes no distinct `missed` marker; `last_skipped_reason` is cleared to null on dispatch. | Minor | Undetermined | `20261013163000_scheduler_fire_due.sql`; `fire-due-schedules.test.ts:94-101` |
| D3 | #263 | DB settings implemented as a `scheduler.config` table + typed readers instead of `app.*` GUCs. | Minor | Intended | `20261013161000_scheduler_pgnet_vault.sql` (migration comment documents the hosted-Supabase permission reason) |
| D4 | #266 (plan) | A late `20261013170000_scheduler_seed_next_run.sql` migration (BEFORE-insert cursor seed) fixes a live step-6 bug where a new schedule's null cursor never fired. Correct fix, but outside the S-154 story scope as written — a drift the plan didn't anticipate. | Minor | Intended | `20261013170000_scheduler_seed_next_run.sql` header |

## 5. Edge-case / randomized outcomes

No Design-Mode test plan was re-executed here beyond the L1 re-run (38/38 pass).
The L2.5 DST matrix, cron accept/reject table, RPC parity, cap matrix, and
no-catch-up cursor advance are present as integration tests and were green in CI
on 58c1d1c+. Production firings (2 schedules, 2026-10-15) corroborate the live
path.

## 6. Out-of-scope observation (not in Waves A–B)

- **12:58:21Z digest `UNAUTHORIZED`** belongs to **S-159** (`/api/internal/
  notifications/digest`, Wave D) — outside this A–B audit. Context from
  `panel/app/api/internal/notifications/digest/route.ts`: the endpoint 401s
  fail-closed on a missing/wrong secret exactly like the fire endpoint, then the
  12:58:23Z `empty_window` (204) shows the authorized call succeeded ~2s later.
  The pattern is consistent with a transient secret/propagation mismatch on
  first call, self-correcting — but confirming root cause is **S-159's audit**,
  not this one. Flagging for the Wave D verifier; no action required for #261–#266.

## 7. Recommendations

| Item | Suggested next step |
| --- | --- |
| D1 (RLS non-vacuous guard) | `qa-engineer`: extend `schedules-schema.test.ts` (or the deny-all harness) to seed one `schedules` + one `notifications` row and assert anon reads 0 from each specifically. Low effort; closes the AC2 PARTIAL. |
| D2 (AC5 miss recorded) | `product-engineer` via `activity-drift-reconciliation`: decide whether "miss recorded" requires a distinct `missed` marker/`last_skipped_reason` or is satisfied by the no-catch-up cursor advance. If a marker is wanted, route to `developer`. |
| D3 (settings table) | No action — intended, documented, tested. |
| D4 (seed_next_run migration) | No action beyond noting it in the S-154 issue history — the fix is correct and tested indirectly by `fire-due-schedules.test.ts`. |
| 12:58 digest UNAUTHORIZED | Carry into the **S-159** fidelity audit (Wave D). |

---

## Per-issue decision lines

ISSUE #261: CLOSE — schema/enums/RLS/constraints met; RLS guard rigor is a minor test gap
ISSUE #262: CLOSE — trigger descriptor fully met, manual byte-identical, type-level reject
ISSUE #263: CLOSE — pg_net/Vault/settings + same-PR runbook all present and tested
ISSUE #264: CLOSE — DST/cron/RPC parity all met; OQ-S2 resolved and tested
ISSUE #265: CLOSE — fire endpoint 401/202/409/failed_to_start met in code, tests, and live
ISSUE #266: CLOSE-WITH-FOLLOW-UP — tick/G4/G2 met; AC5 "miss recorded" audit half unmaterialized
