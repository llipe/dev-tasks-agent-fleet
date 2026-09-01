# Traceability Matrix — Issue #99: reap_stale_runs closes open run_steps

> Mode: **verifier / Design Mode** (pre-implementation)
> Companion: `workstream/test-plan-issue-99.md`
> Format: `AC-ID → Test-Case-ID → Observed-Result → Pass/Fail/Drift`
> `Observed-Result` / `Verdict` are filled during execution (operator run / Audit Mode). All `Pending` at design time.

## AC → Test Coverage

| AC | Statement | Positive test(s) | Negative / edge test(s) | Observed Result | Verdict |
|---|---|---|---|---|---|
| AC-1 | `timed_out` run has no `run_steps` left in `running` | TC-1, TC-2, CT-3 | TC-5 (un-reaped step untouched), EC-1 (terminal step not overwritten) | _pending_ | Pending |
| AC-2 | `failed_to_start` handled with or without steps, no error | TC-3 (with step) | TC-4 (no step — primary guard), TC-5 | _pending_ | Pending |
| AC-3 | Chosen terminal step status documented in `technical-guidelines.md` | DOC-1, DOC-2 | grep old §7 caveat absent/qualified | _pending_ | Pending |
| AC-4 | `001_schema.sql` reflects the updated function | ART-1 | CT-1 (no new `step_status` enum value) | _pending_ | Pending |

## Business-Rule → Test Coverage

| BR | Rule | Test(s) | Observed Result | Verdict |
|---|---|---|---|---|
| BR-1 | Reaped step status is `failed` | TC-1, TC-3, CT-2 | _pending_ | Pending |
| BR-2 | Only `running`/`pending` steps closed; terminal untouched | TC-2 (seq1 succeeded), EC-1 | _pending_ | Pending |
| BR-3 | Closed step gets `finished_at` + attributing `error_message` | TC-1, TC-3 | _pending_ | Pending |
| BR-4 | Run transitions/thresholds/cron unchanged | TC-5, TC-6, CT-1 | _pending_ | Pending |
| BR-5 | Reaper idempotent on already-reaped runs | EC-3, RT-2 | _pending_ | Pending |

## Test Case Index

| Test ID | Title | Kind | AC / BR |
|---|---|---|---|
| TC-1 | `timed_out` + single open step | Positive | AC-1, BR-1, BR-3 |
| TC-2 | `timed_out` + multiple mixed steps | Positive (fan-out) | AC-1, BR-2 |
| TC-3 | `failed_to_start` + open step | Positive | AC-2, BR-1 |
| TC-4 | `failed_to_start` + no steps | Edge (primary AC-2 guard) | AC-2 |
| TC-5 | Healthy run below threshold | Negative (must-not-act) | AC-1, BR-4 |
| TC-6 | `v_runs` two-layer read unchanged | Regression | BR-4 |
| CT-1 | No new `step_status` enum value | Contract / schema-compat | AC-4 |
| CT-2 | Reaper step-close shape == agent path | Contract / symmetry | BR-1, BR-3 |
| CT-3 | Zero open steps under terminal runs invariant | Contract / consumer | AC-1 (+ backfill verify) |
| EC-1 | Already-terminal step not overwritten | Negative | BR-2 |
| EC-2 | `pending`-only steps closed | Edge | AC-1 |
| EC-3 | Idempotent double reap | Negative | BR-5 |
| EC-4 | Multiple reaped runs, mixed states | Data boundary | AC-1 |
| RT-1 | Property: no open step survives a reap | Randomized (seeded) | AC-1 |
| RT-2 | Property: idempotence | Randomized (seeded) | BR-5 |
| DOC-1 | §8 documents `failed` closure | Doc | AC-3 |
| DOC-2 | §7/§18 caveat resolved | Doc | AC-3 |
| ART-1 | `update run_steps` in both loops | Artifact | AC-4 |

## Coverage Verdict (design-time)

- Every AC has ≥1 positive **and** ≥1 negative/edge test: **satisfied**.
- Every derived business rule is mapped: **satisfied**.
- Out-of-scope items (run transitions/thresholds/cron, heartbeat, cancellation, retention, application code) have explicit **regression guards** (TC-5, TC-6, CT-1), not new behavior.
- **AC coverage status: covered (4/4).** No uncovered AC.
- **Blocking gaps:** none at design time. Execution constraint recorded: operator-driven SQL (no automated DB-function harness; tracked in `TESTING.md`).
