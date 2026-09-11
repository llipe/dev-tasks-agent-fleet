# Test Plan — S-110: SSE relay and live log tail

- **Mode:** Design
- **Repository:** `llipe/dev-tasks-agent-fleet`
- **GitHub Issue:** [#123](https://github.com/llipe/dev-tasks-agent-fleet/issues/123)
- **Input type:** story
- **Source artifacts:**
  - Story: `workstream/user-stories-prd-agent-fleet-panel-v2.md` § Story S-110
  - Spec: `workstream/specification-prd-agent-fleet-panel-v2.md` v1.6 (§6.2, SD6, SD4, §13)
  - Design contract: `DESIGN.md` v1.0 §6.6
  - Testing contract: `TESTING.md` / spec §14 (SD12)
- **Companion artifact:** `workstream/traceability-matrix-S-110.md`

> Design-mode note: assertions are derived from observable behavior — the SSE wire
> contract, the cursor/dedupe invariant, the auto-scroll predicate, and the
> subscription open/close log pair. The route handler is exercised as a black box
> with Supabase and Realtime mocked; internal function names below are the story's
> named files, not coupling to a specific implementation.

---

## 1. Source Input Summary

S-110 completes **FR12** and satisfies **PRD AC6**: the run log appends in the browser while a run
is in progress, with no reload. Because RLS is deny-all (D11/SD2), the browser cannot subscribe to
Supabase Realtime directly — the **server** subscribes to `run_events`/`runs` and re-publishes over
**Server-Sent Events**. Gap-free reconnect is by monotonic `seq` (**SD6**), never timestamp, because
the agent buffers writes (D5) so arrival order ≠ emission order. Live status is re-derived through
the shared `effectiveStatus` (**SD4**) so a Realtime `running` push cannot un-do a derived
`timed_out`. Subscription lifecycle is a verification obligation (**SR5**): open/close are logged as
a pair keyed by `run_id` and last `seq`.

**Read-only story** — no schema, data-model, or API-shape change to the database; migration lifecycle
is a documented opt-out.

Surfaces under test:

| Surface | Artifact (from story) | Test layer emphasis |
|---|---|---|
| Cursor / dedupe reducer | `lib/sse/cursor.ts` | Layer 1 (pure) |
| SSE frame serializer | `lib/sse/serialize.ts` | Layer 1 (pure) |
| Auto-scroll threshold predicate | `lib/sse/*` or component helper | Layer 1 (pure) |
| Route handler | `app/api/runs/[id]/events/stream/route.ts` | Layer 2 (mocked Supabase + Realtime) |
| Client stream hook | `lib/hooks/useRunStream.ts` | Layer 2 (mocked `EventSource`) |
| Log viewer wiring + live status | `components/run-detail/{LogViewer,LiveTailButton}.tsx` | Layer 2 (RTL) |
| End-to-end relay | local Supabase stack | Layer 2.5 (Docker-gated) + Playwright (S-114) |

---

## 2. Acceptance Criteria Extraction

| AC | Requirement (observable) | Primary source |
|---|---|---|
| **AC-1** | `GET /api/runs/[id]/events/stream` returns `Content-Type: text/event-stream` and accepts `after_seq` (integer, default `0`) as the resume cursor. | Story AC1; spec §6.2 |
| **AC-2** | Handler backfills `seq > after_seq` **first**, **then** opens the server-side Realtime subscription, and drops pushed rows whose `seq` ≤ the highest already sent — no duplicates, no gaps. | Story AC2; SD6 |
| **AC-3** | Four event types are emitted: `event` (a `run_events` row), `run` (run row changed), `heartbeat` (every 15 s), `closed` (`{ reason }` on terminal state). | Story AC3; spec §6.2 |
| **AC-4** | Client stops reconnecting after `closed`; on an unexpected drop it reconnects with its highest rendered `seq` as `after_seq`. | Story AC4; SD6 |
| **AC-5** | Live-updated run status is recomputed through `effectiveStatus`, so a Realtime push carrying `status = 'running'` cannot overwrite a derived `timed_out`. | Story AC5; SD4 |
| **AC-6** | Auto-scroll per `DESIGN.md` §6.6: append-scroll when within 24 px of bottom; scrolling up pauses and shows the paused state; clicking "live tail" resumes and re-scrolls. | Story AC6; DESIGN §6.6 |
| **AC-7** | Server-side subscription is unsubscribed on request `abort`, and open/close are logged as a pair with `run_id` and last `seq` so an imbalance is visible. | Story AC7; SR5, spec §13 |
| **AC-8** | End-to-end: a run in progress appends log lines in the browser with no reload (PRD AC6). | Story AC8; PRD AC6 |

**Business rules / constraints (assertable):**

- **BR-1 (SD2):** No browser Supabase client, no anon key, no `NEXT_PUBLIC_SUPABASE_*`. The relay is the only path.
- **BR-2:** Full reconciliation for long disconnects is deferred to v3; the durable `seq` cursor makes the deferral safe.
- **BR-3 (§13):** SSE relay logs subscription open, close, and reconnect with `run_id` and last `seq`.
- **BR-4 (security #6, inherited from S-109):** appended log messages render as inert text — never `dangerouslySetInnerHTML`.

**Non-goals (out of scope, must not be tested as requirements):** long-disconnect full reconciliation (v3); the Playwright browser scenario itself (owned by S-114 — AC-8 here is the local live-verification + hook coverage).

---

## 3. E2E / Black-Box Scenarios

### SC-1: Stream opens with correct content type and default cursor
| Field | Value |
|---|---|
| **AC(s)** | AC-1 |
| **Type** | happy-path |
| **Severity** | critical |
| **Preconditions** | A known `run_id` exists with ≥1 `run_events` row. |
| **Steps** | 1. `GET /api/runs/{id}/events/stream` with no `after_seq`. 2. Read response headers and first frames. |
| **Expected Result** | `200`, `Content-Type: text/event-stream`; `after_seq` defaults to `0` so all existing events backfill. |
| **Pass Criteria** | Header is exactly `text/event-stream`; backfill starts at the lowest `seq` (nothing dropped). |

### SC-2: Explicit resume cursor backfills only newer events
| Field | Value |
|---|---|
| **AC(s)** | AC-1, AC-2 |
| **Type** | happy-path |
| **Severity** | critical |
| **Preconditions** | Run has events at `seq` 1..10. |
| **Steps** | 1. `GET …/stream?after_seq=7`. 2. Collect emitted `event` frames. |
| **Expected Result** | Only `seq` 8, 9, 10 are backfilled, in ascending `seq` order. |
| **Pass Criteria** | Emitted set = `{8,9,10}`, ordered; no `seq ≤ 7`. |

### SC-3: Backfill precedes subscription; overlap is de-duplicated
| Field | Value |
|---|---|
| **AC(s)** | AC-2 |
| **Type** | happy-path |
| **Severity** | critical |
| **Preconditions** | Backfill returns `seq` 1..5; Realtime mock is primed to push `seq` 5 and 6 immediately after subscribe. |
| **Steps** | 1. Open stream at `after_seq=0`. 2. Let backfill complete. 3. Fire the two pushed rows. |
| **Expected Result** | Client receives `1,2,3,4,5` (backfill) then `6` (push); pushed `seq 5` is dropped as a duplicate. Ordering: backfill fully emitted before the first live push. |
| **Pass Criteria** | Emitted sequence is `1,2,3,4,5,6` exactly once each; subscribe call happens after the backfill read resolves. |

### SC-4: Four event types are emitted with correct names and payloads
| Field | Value |
|---|---|
| **AC(s)** | AC-3 |
| **Type** | happy-path |
| **Severity** | major |
| **Preconditions** | Run active; then transitions to a terminal status. |
| **Steps** | 1. Open stream. 2. Push a `run_events` row. 3. Push a `runs` row change. 4. Advance clock 15 s. 5. Transition run to terminal. |
| **Expected Result** | Emits `event: event` (row payload), `event: run` (`{status, outcome, finished_at, duration_ms, …}`), `event: heartbeat` (`{}`) after 15 s, `event: closed` (`{ reason }`) on terminal. |
| **Pass Criteria** | All four named event types appear with the documented payload shapes; `closed` carries a `reason`. |

### SC-5: Terminal `closed` stops client reconnection
| Field | Value |
|---|---|
| **AC(s)** | AC-4 |
| **Type** | happy-path |
| **Severity** | critical |
| **Preconditions** | Client hook connected; server will emit `closed`. |
| **Steps** | 1. Server emits `closed`. 2. Observe client `EventSource` lifecycle. |
| **Expected Result** | Hook closes the source and does **not** reopen. |
| **Pass Criteria** | Zero reconnect attempts after `closed` received. |

### SC-6: Unexpected drop reconnects with highest rendered `seq`
| Field | Value |
|---|---|
| **AC(s)** | AC-4 |
| **Type** | negative-path |
| **Severity** | critical |
| **Preconditions** | Client has rendered up to `seq = 42`; no `closed` was received. |
| **Steps** | 1. Simulate an error/drop on the source. 2. Observe the reconnect URL. |
| **Expected Result** | Client reopens with `after_seq=42`. |
| **Pass Criteria** | Reconnect request query is exactly `after_seq=42`; no gap on the resumed stream. |

### SC-7: `running` push cannot overwrite a derived `timed_out`
| Field | Value |
|---|---|
| **AC(s)** | AC-5 |
| **Type** | negative-path |
| **Severity** | critical |
| **Preconditions** | Run is past `started_at + max_runtime + grace` (so `effectiveStatus` = `timed_out`), raw column still `running`. |
| **Steps** | 1. Push a `run` event carrying `status='running'`. 2. Read the status the UI renders. |
| **Expected Result** | UI shows `timed_out`; the raw `running` never wins. |
| **Pass Criteria** | Rendered/derived status = `timed_out` after the push; assertion uses the same `effectiveStatus` as `v_runs`. |

### SC-8: Auto-scroll follows within-threshold; pauses on scroll-up; resumes on live tail
| Field | Value |
|---|---|
| **AC(s)** | AC-6 |
| **Type** | happy-path |
| **Severity** | major |
| **Preconditions** | Log viewer mounted with a scrollable region. |
| **Steps** | 1. Scroll to within 24 px of bottom; append a line. 2. Scroll up beyond threshold; append a line. 3. Click "live tail". |
| **Expected Result** | (1) auto-scrolls to bottom; (2) does **not** auto-scroll, live-tail button shows the paused state; (3) re-scrolls to bottom and resumes. |
| **Pass Criteria** | Scroll follows only when within threshold; paused state visible after scroll-up; resume re-scrolls. |

### SC-9: Subscription is unsubscribed on request abort
| Field | Value |
|---|---|
| **AC(s)** | AC-7 |
| **Type** | negative-path |
| **Severity** | critical |
| **Preconditions** | Stream open; server-side Realtime subscription active. |
| **Steps** | 1. Abort the request (`request.signal` fires `abort`). 2. Inspect the Realtime channel. |
| **Expected Result** | The channel is unsubscribed/removed exactly once; no further pushes are processed. |
| **Pass Criteria** | `unsubscribe`/`removeChannel` called once; a close log line is emitted. |

### SC-10: Open/close are logged as a balanced pair (SR5)
| Field | Value |
|---|---|
| **AC(s)** | AC-7 |
| **Type** | happy-path |
| **Severity** | major |
| **Preconditions** | Structured logger captured. |
| **Steps** | 1. Open then close (terminal or abort) the stream. 2. Repeat connect/disconnect N times. |
| **Expected Result** | Each open log has a matching close log; both carry `run_id` and last `seq`. Over N cycles, open count == close count. |
| **Pass Criteria** | Balanced open/close counts; both fields present on every line; an induced imbalance is detectable. |

### SC-11: End-to-end live append with no reload (PRD AC6)
| Field | Value |
|---|---|
| **AC(s)** | AC-8 |
| **Type** | happy-path |
| **Severity** | critical |
| **Preconditions** | Local stack up; a run row exists; the run-detail page is open. |
| **Steps** | 1. Insert `run_events` rows into the open run after the page has loaded. 2. Observe the viewer without reloading. |
| **Expected Result** | New lines append live, in `seq` order, exactly once. |
| **Pass Criteria** | Every inserted event appears exactly once, ordered by `seq`, with no page reload (Layer 2.5 live insert + S-114 Playwright). |

### SC-12 (abuse): Log message containing script/HTML renders inert
| Field | Value |
|---|---|
| **AC(s)** | AC-3, AC-8 (BR-4) |
| **Type** | abuse-case |
| **Severity** | major |
| **Preconditions** | Live tail active. |
| **Steps** | 1. Push a `run_events` row whose `message` is `<script>alert(1)</script>`. |
| **Expected Result** | The text is displayed literally; no HTML is parsed or executed. |
| **Pass Criteria** | No `dangerouslySetInnerHTML`; DOM shows the literal string. |

### SC-13 (abuse/BR-1): No anon key / browser Supabase path exists
| Field | Value |
|---|---|
| **AC(s)** | AC-8 (BR-1 / SD2) |
| **Type** | abuse-case |
| **Severity** | critical |
| **Preconditions** | Built client bundle available. |
| **Steps** | 1. Grep the built client chunks and source for `NEXT_PUBLIC_SUPABASE`, anon key, or a browser Realtime subscribe. |
| **Expected Result** | None present; the SSE relay is the only browser→events path. |
| **Pass Criteria** | Zero matches for anon key / `NEXT_PUBLIC_SUPABASE_*` / browser `supabase.channel(...)` in client code. |

---

## 4. Contract Validation Scenarios

The boundary is the **SSE wire contract** of `GET /api/runs/[id]/events/stream` (provider = route
handler, consumer = `useRunStream` client hook) plus the **request cursor contract** (`after_seq`).

### CT-1: Valid stream request — content type and frame grammar
| Field | Value |
|---|---|
| **AC(s)** | AC-1, AC-3 |
| **Contract type** | provider-driven |
| **Boundary** | `GET /api/runs/[id]/events/stream` |
| **Direction** | response |
| **Input** | `GET …/stream?after_seq=0` for a known run. |
| **Expected Result** | `text/event-stream`; frames follow `event: <name>\ndata: <json>\n\n`; names ∈ `{event, run, heartbeat, closed}`. |
| **Pass Criteria** | Header exact; every frame parses under the SSE grammar; unknown event names never emitted. |

### CT-2: Missing / omitted `after_seq` defaults to 0
| Field | Value |
|---|---|
| **AC(s)** | AC-1 |
| **Contract type** | consumer-driven |
| **Boundary** | request query `after_seq` |
| **Direction** | request |
| **Input** | `GET …/stream` (no `after_seq`). |
| **Expected Result** | Treated as `after_seq=0`; full backfill. |
| **Pass Criteria** | Cursor = 0; lowest existing `seq` included. |

### CT-3: Type mismatch — `after_seq` non-integer
| Field | Value |
|---|---|
| **AC(s)** | AC-1 |
| **Contract type** | consumer-driven |
| **Boundary** | request query `after_seq` |
| **Direction** | request |
| **Input** | `after_seq=abc`, `after_seq=1.5`, `after_seq=`, `after_seq=-3`. |
| **Expected Result** | Documented, deterministic handling — coerce-or-reject. Recommended: non-parseable/negative → `0` (or `400` if the handler chooses to reject); never a crash, never NaN cursor. |
| **Pass Criteria** | Consistent behavior across all malformed values; never `5xx`; cursor is a finite integer ≥ 0. **Flag:** the story does not state coerce-vs-reject — see §7 clarification. |

### CT-4: Extra unknown query params are ignored
| Field | Value |
|---|---|
| **AC(s)** | AC-1 |
| **Contract type** | schema-compat |
| **Boundary** | request query |
| **Direction** | request |
| **Input** | `after_seq=5&foo=bar&limit=99`. |
| **Expected Result** | `foo`/`limit` ignored; behaves as `after_seq=5`. |
| **Pass Criteria** | Extra params do not alter behavior; no error. |

### CT-5: `closed` payload always carries `reason`
| Field | Value |
|---|---|
| **AC(s)** | AC-3, AC-4 |
| **Contract type** | provider-driven |
| **Boundary** | `event: closed` frame |
| **Direction** | response |
| **Input** | Run reaches each terminal status (`succeeded`, `failed`, `canceled`, `timed_out`, `failed_to_start`). |
| **Expected Result** | `data` is `{ "reason": <string> }` for every terminal path. |
| **Pass Criteria** | `reason` present and non-empty on all terminal transitions. |

### CT-6: `run` event payload shape
| Field | Value |
|---|---|
| **AC(s)** | AC-3, AC-5 |
| **Contract type** | provider-driven |
| **Boundary** | `event: run` frame |
| **Direction** | response |
| **Input** | A `runs` row change pushed by Realtime. |
| **Expected Result** | Payload carries `{ status, outcome, finished_at, duration_ms, … }`; consumer derives display status via `effectiveStatus`, not the raw `status`. |
| **Pass Criteria** | Documented fields present; consumer never renders the raw `status` directly (AC-5). |

### CT-7: `event` frame is a faithful `run_events` row
| Field | Value |
|---|---|
| **AC(s)** | AC-2, AC-3 |
| **Contract type** | provider-driven |
| **Boundary** | `event: event` frame |
| **Direction** | response |
| **Input** | A backfilled row and a pushed row. |
| **Expected Result** | Each carries at least `seq`, `level`, `step`/step ref, `message`, `timestamp` — the fields the S-109 `LogLine` consumes. |
| **Pass Criteria** | Consumer can render every emitted row without a follow-up fetch; `seq` present on every `event`. |

### CT-8: Version/compat — extra fields on a pushed row are tolerated
| Field | Value |
|---|---|
| **AC(s)** | AC-2 |
| **Contract type** | schema-compat |
| **Boundary** | `event: event` frame |
| **Direction** | response |
| **Input** | A `run_events` row with an added, unknown column. |
| **Expected Result** | Extra field ignored; dedupe/ordering by `seq` unaffected. |
| **Pass Criteria** | No crash; rendering unaffected; forward-compatible. |

---

## 5. Edge-Case Catalog

All 9 categories evaluated.

### EC-1: `after_seq` beyond highest existing `seq` (Input Domain)
| Field | Value |
|---|---|
| **AC(s)** | AC-1, AC-2 |
| **Category** | Input Domain |
| **Input / Setup** | Run max `seq = 10`; `GET …/stream?after_seq=999`. |
| **Expected Result** | Empty backfill; stream stays open; only genuinely newer pushes (`seq > 999`) ever emit. |
| **Risk if Missed** | Spurious replay or a stuck/empty stream; false "no events". |

### EC-2: `after_seq=0` on a run with no events yet (Input Domain / Data Boundaries)
| Field | Value |
|---|---|
| **AC(s)** | AC-1, AC-2 |
| **Category** | Input Domain |
| **Input / Setup** | Run just inserted (`queued`), zero `run_events`. |
| **Expected Result** | Empty backfill, subscription opens, first agent event streams live. |
| **Risk if Missed** | Empty-collection handling crashes the stream at the very start of a run. |

### EC-3: Run already terminal at connect (State Transitions)
| Field | Value |
|---|---|
| **AC(s)** | AC-3, AC-4 |
| **Category** | State Transitions |
| **Input / Setup** | Run is `succeeded`/`failed`/`timed_out` before the client connects. |
| **Expected Result** | Backfill all events, then emit `closed` immediately; client does not reconnect. |
| **Risk if Missed** | Client reconnects forever against a dead run — connection/subscription churn. |

### EC-4: `running` raw column but effectively `timed_out` at connect (State Transitions)
| Field | Value |
|---|---|
| **AC(s)** | AC-5 |
| **Category** | State Transitions |
| **Input / Setup** | Reaper hasn't materialized yet; raw `running`, past threshold. |
| **Expected Result** | Derived `timed_out`; if the design treats derived-terminal as terminal, `closed` is emitted. Behavior must be consistent with the row screens (S-108/S-109). |
| **Risk if Missed** | UI shows a perpetually "running" run the rest of the app calls `timed_out`. |

### EC-5: Duplicate `seq` across backfill/push overlap (Timing & Concurrency)
| Field | Value |
|---|---|
| **AC(s)** | AC-2 |
| **Category** | Timing & Concurrency |
| **Input / Setup** | Backfill emits `…,5`; Realtime replays `5` then sends `6`. |
| **Expected Result** | `5` emitted once; `6` emitted; cursor is the max sent. |
| **Risk if Missed** | Duplicate log lines — the exact defect SD6 exists to prevent. |

### EC-6: Out-of-order pushes (Timing & Concurrency)
| Field | Value |
|---|---|
| **AC(s)** | AC-2 |
| **Category** | Timing & Concurrency |
| **Input / Setup** | Pushes arrive `7, 6, 8` (D5 buffering: arrival ≠ emission order). |
| **Expected Result** | The dedupe/cursor reducer drops any `seq ≤ highest already sent`; a late-arriving lower `seq` (already covered by backfill/earlier push) is dropped, genuinely-new higher `seq` passes. |
| **Risk if Missed** | Either gaps (dropping a valid event) or duplicates (re-emitting a covered one). **This is the highest-risk reducer case — cover with a property test (RT-1).** |

### EC-7: `seq` regression / cursor never moves backward (Timing & Concurrency)
| Field | Value |
|---|---|
| **AC(s)** | AC-2, AC-4 |
| **Category** | Timing & Concurrency |
| **Input / Setup** | Feed the reducer a sequence whose `seq` decreases after increasing. |
| **Expected Result** | The tracked "highest sent" cursor is monotonic non-decreasing; a reconnect `after_seq` never regresses. |
| **Risk if Missed** | Reconnect replays already-rendered lines; duplicates on every flaky connection. |

### EC-8: Client disconnects mid-backfill — no leaked subscription (Failure Modes / Resource Exhaustion)
| Field | Value |
|---|---|
| **AC(s)** | AC-7 |
| **Category** | Failure Modes |
| **Input / Setup** | Abort the request during backfill, before subscribe completes. |
| **Expected Result** | Any partially-opened channel is torn down; no channel is left subscribed; a close log is written. |
| **Risk if Missed** | Subscription leak — the exact SR5 hazard; leaks accumulate to connection-pool exhaustion. |

### EC-9: Two concurrent clients on one run (Timing & Concurrency / Resource Exhaustion)
| Field | Value |
|---|---|
| **AC(s)** | AC-2, AC-7 |
| **Category** | Timing & Concurrency |
| **Input / Setup** | Two streams open for the same `run_id` with different `after_seq`. |
| **Expected Result** | Each gets its own correct backfill+live set; closing one does not unsubscribe the other; open/close counts stay balanced per connection. |
| **Risk if Missed** | Cross-talk, shared-channel teardown killing a live viewer, or double-counted log-pair. |

### EC-10: Heartbeat cadence / idle connection (Timing)
| Field | Value |
|---|---|
| **AC(s)** | AC-3 |
| **Category** | Timing & Concurrency |
| **Input / Setup** | No events for > 15 s (fake timers). |
| **Expected Result** | A `heartbeat` frame every ~15 s keeps the connection alive; heartbeats stop after `closed`. |
| **Risk if Missed** | Intermediary idles the connection out; false disconnects; heartbeat leak after close. |

### EC-11: 2 KB single-line message (Data Boundaries)
| Field | Value |
|---|---|
| **AC(s)** | AC-3, AC-8 |
| **Category** | Data Boundaries |
| **Input / Setup** | Push a `run_events` row with a ~2 KB single-line `message` (near the 8 KB truncation cap). |
| **Expected Result** | Emitted as one intact SSE `data:` frame (newline-safe serialization); rendered wrapped, not broken. |
| **Risk if Missed** | An embedded newline in the payload corrupts the SSE frame grammar → parse desync for all following events. |

### EC-12: Burst of 200 events in one flush (Resource Exhaustion / Timing — D5)
| Field | Value |
|---|---|
| **AC(s)** | AC-2, AC-8 |
| **Category** | Resource Exhaustion |
| **Input / Setup** | Agent buffer flushes 200 rows at once (D5). |
| **Expected Result** | All 200 emitted, once each, in `seq` order; no dropped/duplicated event; stream stays responsive. |
| **Risk if Missed** | Backpressure loss or duplication under the realistic buffered-flush pattern. |

### EC-13: Unknown / non-existent run id (Auth & Permissions / Failure Modes)
| Field | Value |
|---|---|
| **AC(s)** | AC-1 |
| **Category** | Failure Modes |
| **Input / Setup** | `GET …/stream` for a `run_id` that does not exist. |
| **Expected Result** | Deterministic, documented response (recommend `404`, or an immediate `closed` with a not-found `reason`); no dangling subscription. |
| **Risk if Missed** | A hung stream on a typo'd id, or a leaked channel. **Flag:** story doesn't state the code — see §7 clarification. |

### EC-14: Message containing embedded newlines / CR (Input Domain / Security)
| Field | Value |
|---|---|
| **AC(s)** | AC-3 |
| **Category** | Input Domain |
| **Input / Setup** | `message` contains `\n`, `\r\n`, and a lone `\r`. |
| **Expected Result** | Serializer encodes so the frame boundary is unambiguous (multi-line `data:` or escaping); the consumer reconstructs the original text. |
| **Risk if Missed** | SSE frame injection / desync; a crafted message could forge a frame boundary. |

### EC-15: Auto-scroll threshold exactly at boundary values (Data Boundaries)
| Field | Value |
|---|---|
| **AC(s)** | AC-6 |
| **Category** | Data Boundaries |
| **Input / Setup** | Distance-from-bottom = 0, 23, 24, 25 px. |
| **Expected Result** | Follow at 0 and 23; the 24 px boundary is decided **one way** and asserted (§6.6 says "within 24px" → 24 inclusive should follow; 25 pauses). |
| **Risk if Missed** | Off-by-one at the boundary → the log either fights the user or fails to follow. |

### EC-16: Reconnect storm / rapid connect-disconnect (Idempotency / Resource Exhaustion)
| Field | Value |
|---|---|
| **AC(s)** | AC-4, AC-7 |
| **Category** | Idempotency |
| **Input / Setup** | Force N rapid drops/reconnects. |
| **Expected Result** | Each reconnect carries the current highest `seq`; open/close counts stay balanced; no compounding subscriptions. |
| **Risk if Missed** | Subscription leak under flapping networks; duplicate events per cycle. |

### API Versioning — **N/A**: the SSE contract is unversioned and internal to the panel; `after_seq` is the only compatibility surface, covered by CT-2/CT-3/CT-8.

---

## 6. Randomized / Property-Based Tactics & Seed Policy

**Seed format:** `<tactic>-<AC>-<unix-ts>-<4hex>` (e.g., `prop-AC2-1725500000-a3f1`).
**Replay:** `pnpm --filter panel test -- --seed=<seed> --tactic=<id> --iterations=1` (deterministic-oracle; capture seed on any failure). Follow the verifier Failure Triage Workflow (capture → isolate → minimize → classify → report; ≤3 non-reproducing retries).

### RT-1: Property — cursor/dedupe reducer never gaps and never duplicates
| Field | Value |
|---|---|
| **AC(s)** | AC-2, AC-4 |
| **Tactic type** | property-based |
| **Input surface** | The pure reducer in `lib/sse/cursor.ts`: `(backfill[], stream of pushes)` with random interleavings, duplicates, out-of-order arrivals, and a mid-stream reconnect at a random cursor. |
| **Property / Oracle** | The emitted `seq` sequence is **strictly increasing**, contains **every** `seq > after_seq` present in the input exactly once, and the tracked cursor is monotonic non-decreasing. |
| **Iterations** | 500 |
| **Seed** | captured at run time |
| **Replay instruction** | `pnpm --filter panel test -- --seed=<seed> --tactic=RT-1 --iterations=1` |
| **Shrink strategy** | Delta-debug the input event list to the smallest subsequence that still gaps or duplicates. |

### RT-2: Property — SSE frame serializer round-trips
| Field | Value |
|---|---|
| **AC(s)** | AC-3 |
| **Tactic type** | property-based |
| **Input surface** | `serialize(eventName, payload)` in `lib/sse/serialize.ts` with random event names ∈ the 4 types and random payloads (unicode, embedded `\n`/`\r`, 0–8 KB length, emoji, quotes). |
| **Property / Oracle** | A standard SSE parser fed the serialized output yields back exactly `(eventName, payload)`; frame boundaries are never forged by payload content. |
| **Iterations** | 500 |
| **Seed** | captured at run time |
| **Replay instruction** | `pnpm --filter panel test -- --seed=<seed> --tactic=RT-2 --iterations=1` |
| **Shrink strategy** | Reduce payload to the shortest string that breaks the round-trip (isolates the offending control char). |

### RT-3: Fuzz — `after_seq` query parameter
| Field | Value |
|---|---|
| **AC(s)** | AC-1 |
| **Tactic type** | fuzz |
| **Input surface** | `?after_seq=` value on the route handler. |
| **Property / Oracle** | Never `5xx`; the resolved cursor is always a finite integer ≥ 0; behavior matches the documented coerce-or-reject policy (once fixed per §7). |
| **Iterations** | 300 |
| **Corpus** | `-1`, `0`, `999999999999`, `1.5`, `NaN`, `""`, `abc`, `0x10`, ` 5 `, `5;DROP`, `%20`, unicode digits, very long numeric string, array `after_seq=1&after_seq=2`. |
| **Seed** | captured at run time |
| **Replay instruction** | `pnpm --filter panel test -- --seed=<seed> --tactic=RT-3 --iterations=1` |
| **Shrink strategy** | Binary-search the corpus mutation to the minimal string that trips a `5xx` or non-integer cursor. |

### RT-4: Stateful random walk — connect / disconnect / push / terminal, assert subscription balance
| Field | Value |
|---|---|
| **AC(s)** | AC-4, AC-7 |
| **Tactic type** | stateful-random-walk |
| **Input surface** | Random valid sequences of `{connect, push(seq), drop, reconnect, terminal-close, abort}` against the mocked handler + hook. |
| **Property / Oracle** | After each sequence: `open logs == close logs` (SR5 balance); no channel remains subscribed once every client is closed; total distinct `seq` rendered == distinct `seq` pushed with `seq > initial after_seq`. |
| **Iterations** | 200 |
| **Seed** | captured at run time |
| **Replay instruction** | `pnpm --filter panel test -- --seed=<seed> --tactic=RT-4 --iterations=1` |
| **Shrink strategy** | Reduce the action sequence to the shortest walk that leaves an unbalanced open/close or a leaked channel. |

---

## 7. Clarifications / Flags for `product-engineer`

These are spec-level ambiguities surfaced during design. They do **not** block writing the tests, but
the assertions marked "Flag" above must be pinned before those tests can be strict rather than
tolerant. Route to `product-engineer` (not fixed here):

1. **`after_seq` malformed-value policy (CT-3, RT-3):** the story says "integer, default 0" but does
   not state coerce-to-0 vs. `400` for `abc`/`1.5`/negative. Recommend coerce non-negative-integer
   else `0`; reject only on explicit choice. Pick one so the fuzz oracle is deterministic.
2. **Unknown run id response (EC-13):** `404` vs. immediate `closed{reason:"not_found"}` is
   unspecified. Both are defensible; the leak-free requirement holds either way.
3. **Derived-terminal at connect (EC-4):** whether a raw-`running`/effective-`timed_out` run emits an
   immediate `closed` (treating derived-terminal as terminal) or streams until the reaper
   materializes. Needs to agree with S-108/S-109 status rendering.
4. **24 px boundary inclusivity (EC-15):** DESIGN §6.6 says "within 24px"; confirm 24 is inclusive
   (follow) so the unit test asserts a single truth at the boundary.

---

## 8. Execution Checklist

- [ ] Layer 1 — `tests/unit/sse-cursor.test.ts`: reducer overlap, out-of-order, duplicate `seq`, `seq` regression, empty inputs (SC-3, EC-5, EC-6, EC-7; RT-1).
- [ ] Layer 1 — `tests/unit/sse-serialize.test.ts`: 4 event names, JSON payloads, embedded newline/CR, 2 KB message, unicode (SC-4, EC-11, EC-14; RT-2).
- [ ] Layer 1 — `tests/unit/autoscroll.test.ts`: threshold predicate at 0/23/24/25 px (SC-8, EC-15).
- [ ] Layer 2 — `tests/component/stream-route.test.ts`: content-type + cursor (SC-1, SC-2, CT-1/CT-2/CT-3/CT-4), backfill-before-subscribe + dedupe (SC-3), four event types + `closed` payload (SC-4, CT-5/CT-6/CT-7), heartbeat cadence (EC-10), unsubscribe on abort (SC-9, EC-8), open/close log pair (SC-10, RT-4), concurrent clients (EC-9), unknown id (EC-13), burst-of-200 (EC-12), extra-field tolerance (CT-8).
- [ ] Layer 2 — `useRunStream` hook: stop after `closed` (SC-5), reconnect with highest `seq` (SC-6), reconnect storm (EC-16).
- [ ] Layer 2 — LogViewer/LiveTailButton: `running` push can't overwrite `timed_out` (SC-7, EC-4), inert message render (SC-12/BR-4), paused/resume UI (SC-8).
- [ ] Layer 2.5 — `tests/integration/stream-e2e.test.ts` (Docker-gated): insert-after-open, every event arrives once in `seq` order (SC-11, EC-2). **State whether it ran live or skipped — a skip is not evidence (spec §14).**
- [ ] Security-negative — no anon key / `NEXT_PUBLIC_SUPABASE_*` / browser subscribe in client bundle (SC-13/BR-1); inert log message (SC-12/BR-4).
- [ ] Manual/UI — invoke or replay a run; scroll-up pauses, "live tail" resumes; kill network briefly, confirm gap-free reconnect (AC-8; formal browser check deferred to S-114 Playwright).
- [ ] Quality gates: `pnpm run lint`, `pnpm run format:check`, `pnpm run typecheck`, `pnpm run test`, `pnpm run audit`, then `pnpm run validate` and repo-root `make validate`.
- [ ] SR5 subscription-leak check recorded in the PR (open/close balance under repeated connect/disconnect).
- [ ] Migration lifecycle: **N/A — read-only story (documented opt-out).**

---

## 9. Coverage Status

Every AC maps to ≥1 positive and ≥1 negative/edge scenario — see `traceability-matrix-S-110.md`.
**Coverage: all 8 ACs covered.** No AC left without an executable design.

Residual (non-blocking): AC-8's browser assertion is completed by the S-114 Playwright scenario; the
four §7 clarifications should be pinned so CT-3/EC-13/EC-4/EC-15 assert a single truth rather than a
tolerant range.
