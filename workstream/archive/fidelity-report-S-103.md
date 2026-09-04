# Fidelity Report — Story S-103 (English-only SQL surface and seed fix)

## Verdict

- **Fidelity: High**
- **Highest drift impact present: Minor**
- **Drift findings: 3 (all Minor; 1 is a disclosed, user-approved decision, not a defect)**
- **Behavior-preserving claim: CONFIRMED** — the reaper replacement changes only operator-facing text; every behavioral dimension is byte-identical to the baseline.
- **Scope:** issue #116 · PR #131 (draft, open) · branch `story/S-103-english-sql-surface` · repo `llipe/dev-tasks-agent-fleet`
- **Mode:** Audit (grey-box). Non-blocking — this audit does not gate PR/issue completion and does not replace the quality gates (`test`/`lint`/`format:check`/`typecheck`/`audit`).

---

## Human-readable summary (what changed and why)

Story S-103 makes every piece of text the database writes for a human to read — and every
label the invoke form will show — English instead of Spanish, and corrects one stale comment
about a timeout that had quietly become wrong.

Three things were fixed in one story:

1. **The reaper's messages.** A scheduled database job (`reap_stale_runs`) marks runs that
   silently died and writes a short explanation of *why* they ended. That explanation was in
   Spanish, and the panel's Run Detail screen shows it word-for-word. It is now English. The
   important part: **nothing about how the job behaves changed** — same states, same error
   codes, same sequencing, same clean-up of leftover steps. Only the sentences a person reads
   are different.
2. **The invoke-form labels.** The names and help text for the dependency-update agent's four
   options were Spanish; they feed the form an operator fills in. They are now English, with
   the machine-readable parts (allowed values, defaults, min/max, required list) untouched.
3. **A misleading comment.** A seed comment claimed one timeout value "must equal" another. A
   previous change made that false. The team confirmed the two timeouts measure different
   things and were never meant to match, corrected the comment, and left the value alone.

**Did the work match what was asked? Yes.** I did not take the evidence on trust — I re-ran
the tests and read the live-applied function directly. All 14 database integration tests pass,
the Python agent's full suite (436 tests) still passes, the reaper function running in the
database reads back as English with no Spanish left and every behavioral element preserved,
the scheduled job is still registered, and the agent's form labels read back English with their
structure intact.

**One honest caveat, and it was disclosed up front.** The story's wording says "no Spanish
remains in the migrations directory." The *effective* database — what you get after a reset or
on the live project — is 100% English. But the original S-102 baseline migration file still
contains the old Spanish sentences as *historical record*, because a later migration converts
them forward. Rewriting already-applied history is itself risky and was a deliberate,
user-approved choice. So the live surface fully meets the intent, while the literal file-level
wording of one criterion has a documented exception. I rank this Minor.

---

## Per-AC result table

Story ACs are numbered AC-1…AC-6 (matching the six user-story acceptance criteria), cross-referenced to task-list verification items 2.20–2.25.

| AC-ID | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
|---|---|---|---|---|---|
| AC-1 (2.20) | Reaper replaced via `create or replace`, English message/error text, **all** behavior preserved (`error_code`, `seq=coalesce(max,0)+1`, `data.reaped_by`/`reason`, #99 step closure on both branches) | `20260903090000_english_reaper_messages.sql` is structurally byte-identical to the baseline body (lines 254–340 of `20260902200101`); only the 4 string literals differ. Live-read `pg_proc.prosrc`: English, no Spanish residue, `coalesce((select max(seq)…)` present, `for update skip locked` present, step-closure predicate present on both branches (2 occurrences) | Runbook §Migrations; PR-comment AC map row 2.20 | `reaper.test.ts` 7/7 pass, authored test-first against Spanish (90099f7) then flipped to English (c72c023) — every non-message assertion unchanged across the flip | **Pass** |
| AC-2 (2.21) | Every `params_schema` `title`/`description` English; `additionalProperties:false` + `required` unchanged | `20260903090100_seed_params_schema_english.sql` + converged `seed.sql`: 4 English titles/descriptions; `type`/`enum`/`default`/`min`/`max`/`required`/`additionalProperties` identical to baseline. Live-read: `fix_mode` title = "Fix mode", `required=["fix_mode"]`, `additionalProperties=false`, schema ASCII-clean | PR-comment AC map row 2.21 | `seed-schema.test.ts` 4/4 pass: English titles, structure unchanged, per-property constraints preserved, whole-schema ASCII assertion | **Pass** |
| AC-3 (2.22) | No Spanish in `supabase/seed.sql` or `supabase/migrations/` (grep evidence) | `seed.sql` + both new migrations: **0** non-ASCII lines (verified `perl -ne '/[^\x00-\x7F]/'`). Baseline `20260902200101` retains **6** Spanish literal lines (279, 288, 296, 315, 322, 330) — the four `reap_stale_runs()` strings, converted forward by 090000 | Disclosed exception documented in PR-comment AC map row 2.22 with user-approved rationale; runbook records forward-conversion | Effective applied surface confirmed English by the live `pg_proc.prosrc` read | **Drift (Minor)** — see D1 |
| AC-4 (2.23) | `start_timeout_seconds` question resolved + recorded; guidelines §8 updated if relation changed | `seed.sql` block 3 comment corrected (queue clock, D9, ≠ `idleRuntimeSessionTimeout`); `docs/technical-guidelines.md` §8 note added (direction A: correct comment, keep value 300, no invariant change) | Runbook §`start_timeout_seconds` resolution; PR-comment AC map row 2.23 | Doc-diff / rationale (no automated test applicable per story) | **Pass** |
| AC-5 (2.24) | Existing agent behavior unaffected; Python gate passes | SQL-only change; no Python file touched. Agent `error_code`s + `INVALID_PARAMS` path untouched | PR-comment AC map row 2.24 | Independently re-ran Python agent suite: **436 passed** (matches reported evidence) | **Pass** |
| AC-6 (2.25) | After apply, synthetic reaped run produces English event + English `error_message` | Live-applied function on local stack (rolled-back txn): `error_message` = "No completion report after 3720 s (max_runtime 3600 + grace 120)."; `run_events.message` = "The system marked this run as timed_out: the agent never reported completion." (`level=error`, `reason=RUNTIME_TIMEOUT`) | Runbook §Applied-state evidence (task 2.19); PR-comment AC map row 2.25 | Reproduced via `reaper.test.ts` timed_out/failed_to_start branches, both assert the English strings | **Pass** |

**AC coverage: 6/6 covered.** 5 Pass, 1 Drift (Minor, disclosed). No uncovered AC.

---

## Drift catalog

> All drift below is **non-blocking to PR/issue completion** per the verifier operating rules and the implement-activity closing gate. Drift is routed to `product-engineer`'s `activity-drift-reconciliation` flow for disposition; the verifier reports only.

### D1 — Baseline migration retains Spanish string literals vs. literal AC-3 wording

- **Description:** AC-3 (task 2.22) reads "no Spanish remains in `supabase/seed.sql` or `supabase/migrations/`." The delivered state satisfies this for `seed.sql` and both new migrations (all ASCII-clean), but `supabase/migrations/20260902200101_initial_schema.sql` (the S-102 baseline) still contains the four Spanish `reap_stale_runs()` string literals (6 non-ASCII lines: 279, 288, 296, 315, 322, 330). Its *comments* were translated to English (comment-only, no executable change); the literals were left as applied history and are converted forward by `20260903090000`.
- **Impact class: Minor.** The **effective** SQL surface — the function body and seed labels present after `supabase db reset` or on the live project — is 100% English, empirically confirmed by reading `pg_proc.prosrc` and `agents.params_schema` on the live-applied local stack. No Spanish string can reach the panel's Run Detail viewer. The gap is purely at the file level of an already-applied historical migration.
- **Intent class: Intended.** Explicitly disclosed in the PR-comment AC map (row 2.22) with the rationale "keep baseline literals as history rather than rewrite S-102," recorded as user-approved. Rewriting an already-applied migration's executable literals is itself an anti-pattern (breaks the applied-history invariant S-102 established).
- **Evidence source(s):** `grep`/`perl` non-ASCII scan of `supabase/`; live `pg_proc.prosrc` read; PR #131 AC-map comment; runbook `docs/runbooks/issue-116-english-sql-surface.md`.
- **Non-blocking.** Recommendation under D-Rec below.

### D2 — Live *remote* content verification is by-construction, not empirical (task 2.15)

- **Description:** Task 2.15 calls for reading `pg_proc.prosrc` / `cron.job` / `agents.params_schema` on the applied **live** project (`hegxeycmbmjfgzqpdiik`). The implementation environment lacks the live DB password (same constraint recorded for S-102 #115), so live-remote content was asserted **by construction** (deterministic `create or replace` + slug-keyed `update`, both confirmed applied via `migration list --linked` showing all three on Remote) plus operator SQL provided for later manual confirmation. The empirical read was performed only on the **local** stack.
- **Impact class: Minor.** The statements are deterministic and idempotent; `migration list --linked` confirms both migrations reached Remote; the identical statements produce verified-English results locally. The residual risk (live remote diverging from local) is very low for `create or replace` + a keyed `update` with no data-dependent branching. I independently reproduced the empirical read on the local applied function and it passed on every dimension.
- **Intent class: Intended** (disclosed environmental constraint, not an oversight).
- **Evidence source(s):** runbook §Applied-state evidence; `migration list --linked` output cited in runbook; my local `pg_proc.prosrc` read.
- **Non-blocking.**

### D3 — `grep` evidence and AC-to-test map are described in the PR body but the literal grep output is not embedded (task 2.22 / 2.26)

- **Description:** AC-3 asks for "grep evidence in the PR" and task 2.26 asks the AC-to-test mapping be recorded in the PR. The AC-to-test mapping **is** published as a PR comment (thorough, per-AC). The literal `grep -nP "[^\x00-\x7F]"` command output is *described* ("`seed.sql` + both new migrations are ASCII-clean") rather than pasted as raw output.
- **Impact class: Minor** (documentation completeness only). I independently ran the equivalent scan and it corroborates the claim exactly (seed + new migrations clean; baseline 6 lines).
- **Intent class: Undetermined** — plausibly an intentional summarization; no rationale is recorded either way.
- **Evidence source(s):** PR #131 body + AC-map comment; my `perl` non-ASCII scan.
- **Non-blocking.**

---

## Edge-case and randomized test outcomes

No Design-Mode test plan was produced for this scope, so this section reports the delivered test suite's edge coverage (independently re-run, all green):

| Edge case (story matrix) | Covered by | Result |
|---|---|---|
| Run with zero steps (0-row step update, no error) | `reaper.test.ts` "safe no-op for a queued run that has no steps" | Pass |
| Run whose `max(seq)` is null (first event → seq=1) | `reaper.test.ts` "handles a stale run whose max(seq) is null" | Pass |
| Already-terminal run untouched by a second pass | `reaper.test.ts` "leaves an already-terminal run untouched on a second pass" (finished_at stable, exactly 1 reaper event) | Pass |
| Steps already terminal left alone | `reaper.test.ts` "closes open run_steps … (issue #99)" asserts `succeeded` step untouched | Pass |
| Both reaper branches (`timed_out`/`RUNTIME_TIMEOUT`, `failed_to_start`/`START_TIMEOUT`) | `reaper.test.ts` branch tests | Pass |
| `seq = max(seq)+1` with pre-existing events | `reaper.test.ts` "writes the explanatory event at seq = max(seq)+1" (seeds seq 4,5 → asserts 6) | Pass |
| Seed migration idempotency (re-apply twice) | Structural: slug-keyed `update` is inherently idempotent; `seed-schema.test.ts` reads the converged row | Pass (by construction) |

Docker-gating note: the integration suite is correctly Docker-gated (`describe.skipIf`) with a recorded skip reason, keeping it reachable from `make validate` without turning a missing daemon into a red gate. In this audit the local stack was up, so all 14 tests executed (not skipped).

---

## Independent verification performed by this audit

Rather than trust the reported evidence, I re-ran the key checks:

- **`panel` Layer 2.5 integration:** `pnpm --filter panel run test:integration` → **14 passed** (reaper 7 + seed-schema 4 + baseline 3). Matches reported.
- **Python agent gate:** `make -C agents/dependency-update/app/dependencyUpdate test` → **436 passed**. Matches reported.
- **Live-applied function (local stack):** read `pg_proc.prosrc` directly — English on all four strings, zero Spanish residue, `coalesce(max(seq),0)+1` preserved, `for update skip locked` preserved, both-branch step closure preserved (2 predicate occurrences).
- **Schedule intact:** `cron.job` → `reap-stale-runs` at `* * * * *`.
- **`params_schema` live read:** `fix_mode` title = "Fix mode", `required=["fix_mode"]`, `additionalProperties=false`, whole-schema ASCII-clean.
- **Non-ASCII scan** of `supabase/`: `seed.sql` clean, both new migrations clean, baseline retains exactly the 6 disclosed Spanish literal lines. (`config.toml` has 2 em-dash `—` lines in CLI-generated comments — not Spanish, outside AC-3 scope; informational only.)

The behavior-preserving claim is **confirmed**: a line-by-line comparison of `20260903090000` against the baseline body shows the only differences are the four operator-facing string literals.

---

## Recommendations

| Item | Recommendation | Owner |
|---|---|---|
| D1 (baseline Spanish literals vs. literal AC-3 wording) | **No code action needed.** The intent (English effective SQL surface) is fully met and the exception is user-approved. Recommend `product-engineer` reconcile the AC-3 *wording* to match the delivered/agreed reality — e.g., "no Spanish remains in the *effective* SQL surface (`db reset` / live); already-applied baseline literals are exempt and converted forward" — via `activity-drift-reconciliation`, so a future literal-grep audit does not re-flag this. | product-engineer (spec/AC wording) |
| D2 (live-remote by-construction verification) | **No action needed to complete S-103.** When the live DB password is available, run the operator SQL already provided in the runbook §Applied-state evidence and paste the result into the PR/issue to close the empirical gap. | developer / operator (follow-up) |
| D3 (grep output described, not embedded) | **Optional.** Paste the literal `grep`/scan output into the PR body for auditor convenience. Low value; the claim is corroborated. | developer (optional) |

---

## Output contract

- **Mode / phase:** Audit Mode · Phase 4 (Reporting & Publication)
- **Source artifact used:** `workstream/user-stories-prd-agent-fleet-panel-v2.md` (Story S-103 ACs) + `workstream/tasks-prd-agent-fleet-panel-v2-plan.md` (tasks 2.0–2.28) + PRD/spec intent (F3, D9)
- **Codebase audited:** `supabase/migrations/20260903090000_english_reaper_messages.sql`, `20260903090100_seed_params_schema_english.sql`, `supabase/seed.sql`, `supabase/migrations/20260902200101_initial_schema.sql` (baseline), `panel/tests/integration/{reaper,seed-schema,db}.ts`, `docs/technical-guidelines.md` §8, `docs/runbooks/issue-116-english-sql-surface.md`
- **Output file:** `workstream/fidelity-report-S-103.md`
- **GitHub target:** issue #116 / PR #131 (header/verdict + human-readable summary to be posted)
- **AC coverage status:** 6/6 covered (5 Pass, 1 Minor drift — disclosed)
- **Overall fidelity verdict:** High · **Highest drift impact:** Minor
- **Blocking gaps:** None. Audit is additive and non-blocking.
