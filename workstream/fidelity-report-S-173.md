# Fidelity Report — S-173 (#318) webhook guardrails + per-rule G3 (verifier, Audit Mode)

**Verdict: High fidelity.** All 3 acceptance criteria met. Highest drift impact: **Minor**, with one scheduler behavior change that is called out explicitly.

## AC → evidence

| AC | Evidence | Result |
| --- | --- | --- |
| G1 overlap, G4 cap and G5 open PR apply to webhook runs; a skip records `skipped` + reason | L2.5 `webhook-guardrails.test.ts`: G1 for queued/running, a stale run doesn't count (`effective_status`); G5 blocks until a later manual run supersedes it; G4 cap reached across both triggers. Through the real route, `webhook-fire.test.ts`: a second delivery during an active run → `skipped:overlap`, no run, one invoke | Pass |
| G3 per rule: increment on a start failure, reset on success, auto-disable at threshold + notification | L2.5: disabled at exactly 3 with **one** notification (a 4th failure adds none); success resets (EC-10); the notification names the endpoint. Route level: 3 failed starts disable the rule and the next delivery is `no_match` | Pass |
| G2 documented n/a for webhooks | Migration header | Pass |

Test-plan items covered: AC6, EC-10, EC-16 (shared cap), RT-6 property (N consecutive failures ⇔ disabled, one notification), as deterministic sequences.

## Drift

| # | Finding | Type | Impact |
| --- | --- | --- | --- |
| 1 | **Different mechanism from the story text.** The story said to run G1/G4/G5 inside `invokeResolvedRun()`. The schedule guardrails actually live in the SQL due-tick with block/clear state on the `schedules` row, and the fire route only had placeholder comments. I added a stateless `public.webhook_guardrail` that reuses the scheduler's own predicates (`has_active_run`, `open_pr_block_run`, `max_inflight`) and left the scheduler untouched. Same rules, no rewrite of the live path. Spec §8.4 should be updated to describe this. | Intended (design) | Minor |
| 2 | **Shared G4 cap changes the scheduler.** `scheduler.in_flight_scheduled_runs()` now counts webhook runs, so in-flight webhook runs can push a scheduled run into `concurrency_cap`. This is what FR17 means by "the same G4 cap"; it's called out in the PR, and all scheduler suites stay green. | Intended | Minor |
| 3 | **No manual G5 clear for webhooks.** Scheduled runs have "PR handled · resume anyway" because a schedule keeps firing on its own. For webhooks, a later manual run supersedes the block (G5-a). A per-rule clear would be a possible follow-up. | Intended | Minor |
| 4 | Formatting: `prettier --write` on a file list repeatedly missed integration test files, cause unknown. The fix is package-wide `prettier --write .` followed by `--check`. | Process note | — |

## Gates

- L2.5: `webhook-guardrails` 14/14 (red before the migration: missing column/functions), `webhook-fire` 5/5, `webhook-resolve` 9/9, `webhook-route` 11/11. Scheduler regression: `fire-due-schedules`, `guardrail-overlap`, `guardrail-open-pr`, `guardrail-autopause`, `notify-sweep`, `definer-grants` all green.
- L1: `webhook-fire` 8/8 (6 red before).
- SQL mutants: schedule-only cap (2 failing), no G1 (3), no auto-disable (3).
- `make validate-js`: pass (1891 tests). `make validate-py`: pass. `next build`: pass.
