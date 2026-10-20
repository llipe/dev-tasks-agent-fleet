# Fidelity Report — S-172 (#317) shared invoke core + webhook trigger (verifier, Audit Mode)

**Verdict: High fidelity.** All 4 acceptance criteria met. Highest drift impact: **Minor**.

## AC → evidence

| AC | Evidence | Result |
| --- | --- | --- |
| `invokeResolvedRun` runs payload → `buildRunInsert` → `insertQueuedRun` → `invokeAgentRuntime` → `markRunFailedToStart` on throw | `invoke-resolved-run.test.ts` 9/9: order insert → `onQueued` → invoke; contract payload (`repository_org`/`repository_name`); `base_branch` override; no-repository payload; typed failure; mark failure swallowed (`markFailed`); insert failure propagates without an invoke | Pass |
| `TriggerDescriptor` gains `webhook:${string}`; `buildRunInsert` unchanged | `run-insert.test.ts` +2 (webhook shape; a mismatched type/identity is a compile error, `@ts-expect-error`). Typecheck was red before the type change | Pass |
| Fire route refactored onto the core with identical behavior; scheduler suites green | **Baseline before the refactor: 55 tests / 9 files; after: 57/57** (the 55 plus the 2 new run-insert cases). The fire route's mocked L1 suite (ordering, response shapes, G3 increment) passes unchanged. Kept as-is: the `queued_row_inserted` log via `onQueued`, `describeAwsError` (#306) via `cause`, `recordScheduleFireFailure`, every response body and status | Pass |
| The webhook calls the core → `trigger_type='webhook'` run, delivery `fired` + `run_id`, `202 {run_id}` | L2.5 `webhook-fire.test.ts` 3/3: a real `runs` row (`webhook`, `webhook:<ep>:<rule>`, `queued`, params, repo); delivery `fired` with run and rule (AC1); invoke failure → run `failed_to_start`, delivery still `fired`, 202 (EC-22); a replay invokes once (AC2) | Pass |

## Mutation checks (live path)

Removing `markRunFailedToStart` fails 4 tests. A clean order swap (insert after invoke) fails 3. Changing the fire route's trigger to manual fails 1. Dropping the fire route's G3 increment fails 1.

## Drift

| # | Finding | Type | Impact |
| --- | --- | --- | --- |
| 1 | **Latency (task 8.8).** Production run-start latency over 30 days is p50 1.8 s / p95 3.2 s / max 4.1 s (9 runs, agent boot included), under GitHub's 10 s timeout. I kept the invoke synchronous, because background work after the response isn't durable on a Fly Node process, and added an optional `timeoutMs` to `invokeAgentRuntime` (`AbortSignal.timeout`). Only the webhook path passes it (8 s); manual invoke and the schedule fire route are unchanged (a test confirms `send()` gets no options without it). | Intended | Minor |
| 2 | **The manual invoke route keeps its own copy** of the insert → invoke steps. The story scopes the refactor to the schedule fire route, and manual invoke has extra logging (`mark_failed_to_start_failed`). Folding it in is a candidate follow-up. | Scope | Minor |
| 3 | A failed-to-start webhook run still records the delivery as `fired` and answers 202, so GitHub doesn't redeliver an event that already has a run row. | Intended | Minor |
| 4 | The dropped-undeclared-params note (S-171) is kept on the `fired` row. | Intended | — |
| 5 | The S-171 L2.5 file now stubs only the AWS wrapper (its resolved routes really invoke) and expects `fired`. | Expected change | — |
| 6 | Found during the gates: `stream-e2e.test.ts` (SSE) flaked a third time and passed on rerun. Unrelated; filed **#387**. | Out of scope | — |

## Gates

- L1: `invoke-resolved-run` 9/9, `webhook-fire` 4/4, `run-insert` 7/7, `invoke` (incl. 3 new timeout cases) all green.
- L2.5: `webhook-fire` 3/3, `webhook-resolve` 9/9, `webhook-route` 11/11. Baseline set 57/57.
- `make validate-js`: pass (1871 tests; one SSE flake on the first run, #387). `make validate-py`: pass. `next build`: pass.
