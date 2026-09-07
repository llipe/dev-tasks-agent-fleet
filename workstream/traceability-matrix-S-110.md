# Traceability Matrix — S-110: SSE relay and live log tail

- **Mode:** Design
- **Repository:** `llipe/dev-tasks-agent-fleet`
- **GitHub Issue:** [#123](https://github.com/llipe/dev-tasks-agent-fleet/issues/123)
- **Companion:** `workstream/test-plan-S-110.md`

Mapping: `AC-ID → Test-Case-ID → Observed-Result (to be filled at execution) → Pass/Fail/Drift`.
Design-mode result cells are `—` (pending implementation/audit). Every AC has ≥1 positive and ≥1
negative/edge case.

## AC → Test-Case coverage

| AC | Requirement (short) | Positive case(s) | Negative / edge case(s) | Contract / property | Observed | Verdict |
|---|---|---|---|---|---|---|
| **AC-1** | `text/event-stream`; `after_seq` int, default 0 | SC-1, SC-2 | EC-1, EC-2, EC-13, CT-3 | CT-1, CT-2, CT-4; RT-3 | — | — |
| **AC-2** | Backfill first, then subscribe, drop `seq ≤` highest (no dup/gap) | SC-2, SC-3 | EC-5, EC-6, EC-7, EC-12, CT-8 | CT-7; **RT-1** | — | — |
| **AC-3** | Four event types (`event`/`run`/`heartbeat` 15 s/`closed{reason}`) | SC-4 | EC-10, EC-11, EC-14 | CT-1, CT-5, CT-6, CT-7; RT-2 | — | — |
| **AC-4** | Stop reconnect after `closed`; else reconnect at highest `seq` | SC-5, SC-6 | EC-3, EC-7, EC-16 | CT-5; RT-1, RT-4 | — | — |
| **AC-5** | Live status via `effectiveStatus` (`running` push ≠> `timed_out`) | SC-7 | EC-4 | CT-6 | — | — |
| **AC-6** | Auto-scroll §6.6: 24 px follow, scroll-up pause, live-tail resume | SC-8 | EC-15 | — | — | — |
| **AC-7** | Unsubscribe on abort; open/close logged as a pair (SR5) | SC-10 | SC-9, EC-8, EC-9, EC-16 | RT-4 | — | — |
| **AC-8** | End-to-end live append, no reload (PRD AC6) | SC-11 | SC-12, SC-13 (abuse) | — (S-114 Playwright) | — | — |

## Business-rule / constraint coverage

| Rule | Source | Test-Case(s) | Observed | Verdict |
|---|---|---|---|---|
| **BR-1** — no browser Supabase / anon key / `NEXT_PUBLIC_SUPABASE_*` | SD2 | SC-13 | — | — |
| **BR-2** — long-disconnect reconciliation deferred; durable `seq` cursor makes it safe | Story | SC-6, EC-7 (cursor durability) | — | — |
| **BR-3** — relay logs open/close/reconnect with `run_id` + last `seq` | §13, SR5 | SC-10, RT-4 | — | — |
| **BR-4** — appended messages render inert (never `dangerouslySetInnerHTML`) | Security #6 | SC-12, EC-14 | — | — |

## Test artifact → case index (files from the story)

| Test file | Layer | Cases covered |
|---|---|---|
| `tests/unit/sse-cursor.test.ts` | 1 | SC-3, EC-5, EC-6, EC-7, RT-1 |
| `tests/unit/sse-serialize.test.ts` | 1 | SC-4, EC-11, EC-14, CT-5/CT-6/CT-7, RT-2 |
| `tests/unit/autoscroll.test.ts` | 1 | SC-8, EC-15 |
| `tests/component/stream-route.test.ts` | 2 | SC-1, SC-2, SC-3, SC-4, SC-9, SC-10, EC-3, EC-8, EC-9, EC-10, EC-12, EC-13, CT-1–CT-8, RT-3, RT-4 |
| `useRunStream` (component) | 2 | SC-5, SC-6, EC-16 |
| `LogViewer` / `LiveTailButton` (component) | 2 | SC-7, SC-8, SC-12, EC-4 |
| `tests/integration/stream-e2e.test.ts` | 2.5 | SC-11, EC-2 (live insert; state live-vs-skipped) |
| client-bundle grep (security-negative) | 1/2 | SC-13 / BR-1 |

## Coverage summary

- **ACs covered:** 8 / 8.
- **ACs uncovered:** none.
- **Positive + negative per AC:** satisfied for every AC.
- **Highest-risk reducer path (EC-6/EC-7)** backed by property test RT-1.
- **Open clarifications** (do not block design; pin before strict assertions): CT-3/RT-3
  `after_seq` malformed policy; EC-13 unknown-id response; EC-4 derived-terminal-at-connect; EC-15
  24 px inclusivity. See test plan §7 — routed to `product-engineer`.
