# Fidelity Report — S-110: SSE relay and live log tail

## 1. Header / Verdict

- **Fidelity: High**
- **Highest drift impact present: Minor**
- **Scope:** Story S-110 · Issue [#123](https://github.com/llipe/dev-tasks-agent-fleet/issues/123) · PR #152 · branch `story/S-110-sse-live-tail` · repo `llipe/dev-tasks-agent-fleet`
- **Mode:** Audit (grey-box) · **Phase:** 4 (reporting & publication)
- **Overall AC result:** 8 / 8 Pass · 0 Partial · 0 Fail
- **Completion gate:** This audit is additive and **non-blocking**. Drift below does not block PR/issue completion and does not replace the standing quality gates (`test`/`lint`/`format:check`/`typecheck`/`audit`).

---

## 2. Human-readable summary — what changed and why

This story makes the run log **update itself in the browser while a run is happening**, so an operator can watch a run without hitting refresh. That sounds simple, but there is a real constraint behind it: for security the browser is not allowed to talk to the database directly. So the panel's own server opens the database "live feed" and re-broadcasts it to the browser over a long-lived connection (Server-Sent Events).

Two things had to be gotten right, and both were:

1. **No missed lines and no repeated lines.** When the browser connects (or re-connects after a hiccup), the server first hands over everything the browser hasn't seen yet, *then* switches to the live feed, and throws away anything that would arrive twice. Ordering is done by a strictly increasing line number the agent stamps on every log line — not by clock time, because the agent sends logs in bursts and timestamps can arrive out of order. The result is a log that is gap-free and duplicate-free even across a dropped connection.
2. **A run that has secretly expired still looks expired.** If a run has run past its time limit but the database row hasn't been updated yet, a stray "still running" message from the live feed must not make the UI flip back to "running". The screen recomputes the true status the same way every other screen in the app does, so it stays consistent.

Supporting behavior delivered: the connection sends a tiny "heartbeat" every 15 seconds so network middle-boxes don't kill an idle connection; when the run finishes the server sends a "closed" signal and the browser stops trying to reconnect; the log auto-follows new lines only while you're near the bottom, pauses if you scroll up, and a "live tail" button jumps you back to the bottom; and the server always releases its database feed when you close the tab, with paired open/close log entries so a leak would be visible.

**What was proven, and how.** The tricky ordering/dedupe logic and the frame format are covered by fast unit tests; the connection behavior by component tests with the database mocked. Most importantly, the end-to-end "insert a log line and watch it appear exactly once, in order" property was **run for real** against a local database (not a mock) and passed repeatedly. The one thing deliberately left for a later story is the in-a-real-browser scroll-and-reconnect check (a Playwright test, owned by S-114).

**Nothing here changed the database, the data model, or any existing API.** It is a read-only feature; the migration step is a documented not-applicable.

---

## 3. Per-AC result table

| AC | Description (short) | Codebase evidence | Workstream evidence | Test evidence | Result |
|---|---|---|---|---|---|
| **AC-1** | `text/event-stream`; `after_seq` integer, default 0 | `route.ts` sets `content-type: text/event-stream; charset=utf-8`; `parseAfterSeq` coerces non-finite/negative → 0, floors, default 0; inline `force-dynamic`/`revalidate=0`/`fetchCache` | Story AC1; spec §6.2; test-plan SC-1/SC-2/CT-1–CT-4 | `tests/unit/after-seq.test.ts`; `tests/component/stream-route.test.ts` (content-type, cursor) | **Pass** |
| **AC-2** | Backfill `seq>after_seq` first, then subscribe, drop `seq ≤` highest | `relay.ts` `createStreamResponse`: backfill → `dedupeAndOrder` → `isTerminal` probe → `openChannel().subscribe()`; `SeqCursor.admit` drops `seq ≤ highest`; `cursor.ts` monotonic | Story AC2; spec §6.2/SD6; SC-3, EC-5/6/7/12, RT-1 | `tests/unit/sse-cursor.test.ts` (overlap, out-of-order, regression); `stream-route.test.ts` (order-before-subscribe, dedupe); **live L2.5** exactly-once/in-order | **Pass** |
| **AC-3** | Four event types (`event`/`run`/`heartbeat` 15s/`closed{reason}`) | `serialize.ts` union `event\|run\|heartbeat\|closed`; `relay.ts` emits all four; `heartbeatMs=15_000`; `closed` carries `{reason}` | Story AC3; spec §6.2 event table; SC-4, EC-10/11/14, CT-5/6/7, RT-2 | `tests/unit/sse-serialize.test.ts` (round-trip, newline/CR safety); `stream-route.test.ts` (four types, heartbeat cadence, closed payload) | **Pass** |
| **AC-4** | Stop reconnect after `closed`; else reconnect at highest `seq` | `useRunStream.ts`: `closedRef` gates `onerror`; on unexpected drop reopens `streamUrl(runId, cursor.highest)`; client-side `SeqCursor` dedupe | Story AC4; SD6; SC-5/SC-6, EC-16, RT-4 | `tests/component/use-run-stream.test.tsx` (stop-after-closed, reconnect `after_seq`) | **Pass** |
| **AC-5** | Live status via `effectiveStatus` (raw `running` ≠> `timed_out`) | `LiveLogViewer.tsx` derives `effectiveStatus(...)` at render; hook forwards **raw** status only; route `isRunTerminal` also uses shared `effectiveStatus` (SD4) | Story AC5; spec SD4; SC-7, EC-4, CT-6 | `tests/component/live-log-viewer.test.tsx` (`running` push on expired run renders `timed_out`) | **Pass** |
| **AC-6** | Auto-scroll §6.6: 24px follow, scroll-up pause, live-tail resume | `autoscroll.ts` `shouldAutoScroll` (≤24px inclusive); `LiveLogViewer` follow state + `useLayoutEffect` pin; `LiveTailButton` active/paused + `aria-pressed` | Story AC6; DESIGN §6.6; SC-8, EC-15 | `tests/unit/autoscroll.test.ts` (0/23/24/25px boundary); `live-log-viewer.test.tsx` (pause/resume) | **Pass** |
| **AC-7** | Unsubscribe on abort; open/close logged as a pair (SR5) | `relay.ts` `signal.addEventListener("abort", cleanup)` + `cancel()`; `unsubscribe()` once; `sse_open`/`sse_close` both carry `run_id` + `last_seq`; route logs JSON to stdout (§13) | Story AC7; spec §13, SR5; SC-9/SC-10, EC-8/9/16, RT-4 | `stream-route.test.ts` (unsubscribe once; balanced open/close pair with `run_id`+`last_seq`) | **Pass** |
| **AC-8** | End-to-end live append, no reload (PRD AC6) | `page.tsx` selects `LiveLogViewer` vs `LogViewer` by `effectiveStatus`; `data-sse-mount="run-log"` hook; inert message render via `LogLine` (never `dangerouslySetInnerHTML`) | Story AC8; PRD AC6; SC-11 (+ S-114 Playwright for browser assertion) | **live L2.5** `stream-e2e.test.ts` — RAN LIVE, 3/3 deterministic: every inserted event arrives exactly once, in `seq` order | **Pass** |

**Business rules:** BR-1 (SD2, no browser Supabase / anon key) — server-only relay, `createServerClient` server-side; no `NEXT_PUBLIC_SUPABASE_*` in client path (bundle-grep obligation carried by S-104 CT-7 harness). BR-3 (§13 open/close/reconnect logging) — satisfied for open/close; reconnect is client-initiated so it produces a fresh `sse_open` (see D3). BR-4 (inert render) — `LogLine` renders message as a text node; confirmed in `LiveLogViewer`.

---

## 4. Drift catalog

All drift below is **non-blocking to completion.**

### D1 — `after_seq` malformed-value policy is coerce-to-0 (Minor · Intended)
- **What:** `parseAfterSeq` coerces `abc`, `1.5`, `""`, negative, and `NaN` to `0` (full backfill) rather than returning `400`. Non-integer floats are floored.
- **Evidence:** `route.ts` `parseAfterSeq`; `tests/unit/after-seq.test.ts`; test-plan §7 flag 1 / CT-3 / RT-3.
- **Intent:** **Intended.** The test plan explicitly flags coerce-vs-reject as an unpinned spec ambiguity left to `product-engineer`; the implementation picked the recommended coerce-to-0 and documented it. Deterministic, never `5xx`, cursor always finite ≥ 0 — matches the CT-3 pass criteria.
- **Recommendation:** `product-engineer` — pin the policy in spec §6.2 so the fuzz oracle can assert a single truth. No code change needed.

### D2 — AC-8 browser scroll/reconnect assertion deferred to S-114 (Minor · Intended)
- **What:** The in-browser auto-scroll-follow and network-drop-reconnect assertions are not automated in this story; AC-8's automated core is the live Layer 2.5 exactly-once/in-order test plus the hook/unit coverage.
- **Evidence:** test-plan §2 non-goals, §9 residual; traceability AC-8 "— (S-114 Playwright)"; issue #123 testing notes.
- **Intent:** **Intended.** Declared scope boundary; the observable end-to-end append property is proven live.
- **Recommendation:** No action for S-110. Ensure S-114 Playwright covers SC-8 browser behavior and SC-6 reconnect-after-drop in a real `EventSource`.

### D3 — Reconnect is not separately logged server-side (Minor · Intended)
- **What:** BR-3/§13 names "open/close/**reconnect**" logging. The server logs `sse_open`/`sse_close` as a balanced pair; a client reconnect is a brand-new request that emits its own `sse_open` (with the resumed `after_seq`), so reconnects are observable as additional open/close pairs rather than a distinct `reconnect` log line.
- **Evidence:** `relay.ts` `deps.log("sse_open"/"sse_close", …)`; `useRunStream` reopens a fresh `EventSource` on drop; `stream-route.test.ts` open/close balance assertion.
- **Intent:** **Intended / defensible.** SSE reconnect is a new TCP request by construction; the SR5 imbalance-detection goal (open count == close count, keyed by `run_id`+`last_seq`) is fully met. A dedicated `reconnect` tag would be cosmetic.
- **Recommendation:** `product-engineer` (optional) — either soften §13 wording to "open/close pairs (a reconnect is a new open)" or, if a distinct signal is wanted, add a `resumed_from_seq` field to `sse_open`. No behavior gap.

### D4 — Route-handler line coverage ~12% (Minor · Intended)
- **What:** `route.ts` (the thin Supabase/Next adapter) sits at ~12% line coverage; the pure `createStreamResponse` core is 89%+, and the Supabase-channel wrapper is exercised by the live Layer 2.5 suite via its own channel copy.
- **Evidence:** qa-engineer `coverage_gate: PASS` with this recorded as accepted non-blocking item (1); `relay.ts` holds the SD6/SR5 logic under unit+component test; `stream-e2e.test.ts` drives the real channel.
- **Intent:** **Intended.** Deliberate thin-adapter / dependency-injection split — the untested lines are Supabase glue, proven end-to-end live. `wrapSupabaseChannel` in the route is not directly unit-tested (the L2.5 suite uses a structurally identical copy).
- **Recommendation:** No action required. Optional future hardening: a single component test that asserts the route's `wrapSupabaseChannel` registers both `postgres_changes` filters (`run_events` INSERT, `runs` UPDATE) so route and test-copy cannot silently diverge.

### D5 — Integer-overflow fix on `getRunEventsAfterSeq` (No drift — improvement, recorded for traceability)
- **What:** An earlier `Number.MAX_SAFE_INTEGER` upper-bound ceiling overflowed the `seq` `integer` column (pg 22003); replaced with an unbounded `seq > afterSeq` paged read.
- **Evidence:** `queries.ts` `getRunEventsAfterSeq` docstring + implementation; caught by the live Layer 2.5 run.
- **Intent:** **Intended** correction; strengthens AC-1/AC-2 fidelity. The live suite is what surfaced it — evidence that the Layer 2.5 gate is doing real work, not skipping to green.
- **Recommendation:** None.

---

## 5. Edge-case & randomized test outcomes (against the design-mode plan)

| Plan item | Covered by | Observed |
|---|---|---|
| RT-1 cursor never gaps/dupes | `sse-cursor.test.ts` + live L2.5 | Pass — monotonic cursor; exactly-once verified live |
| RT-2 serializer round-trip | `sse-serialize.test.ts` | Pass — newline/CR-safe via `JSON.stringify` |
| EC-3 terminal-at-connect → immediate `closed`, no subscribe | `relay.ts` `isTerminal` branch | Pass (code + component) |
| EC-10 heartbeat cadence / stops after close | `stream-route.test.ts` | Pass |
| EC-11/EC-14 large / newline-bearing message | `sse-serialize.test.ts` | Pass |
| EC-13 unknown run id | `route.ts` returns `"not_found"` reason → immediate `closed`, no dangling channel | Pass — deterministic, leak-free (one of the two §7-flagged options) |
| EC-15 24px boundary inclusive | `autoscroll.test.ts` (0/23/24/25) | Pass — 24 follows, 25 pauses |
| SC-11 / EC-2 live append exactly-once | `stream-e2e.test.ts` **RAN LIVE** | Pass 3/3 deterministic after subscribe-await harness fix |
| AC-8 browser scroll/reconnect | S-114 Playwright | Deferred (D2, intended) |

**Live-vs-skip honesty (spec §14):** the Layer 2.5 suite is Docker + service-role-key + Realtime-gated and records a skip reason rather than passing vacuously; for this delivery it **ran live** and passed deterministically. This is credited as real evidence, not a skip.

---

## 6. Recommendations (per item; nothing applied here)

1. **D1** → `product-engineer`: pin `after_seq` malformed policy (coerce-to-0) in spec §6.2. Routed via `activity-drift-reconciliation`.
2. **D2** → S-114: cover browser scroll-follow (SC-8) and reconnect-after-drop (SC-6) in Playwright.
3. **D3** → `product-engineer` (optional): reconcile §13 "reconnect" wording with the open-pair model, or add `resumed_from_seq` to `sse_open`.
4. **D4** → `developer` (optional, non-blocking): one route-level test pinning the two `postgres_changes` filter registrations so route and L2.5 channel copy cannot drift.
5. **EC-13 / EC-4** → `product-engineer` (optional): pin unknown-id response and derived-terminal-at-connect behavior in the spec so they assert a single truth (implementation already deterministic and consistent with S-108/S-109).

---

## 7. Output contract

- **Mode / phase:** Audit / Phase 4
- **Source artifacts:** issue #123 ACs; `test-plan-S-110.md`; `traceability-matrix-S-110.md`; spec `specification-prd-agent-fleet-panel-v2.md` §6.2/SD6/SD4/SR5/§13; DESIGN.md §6.6
- **Output files:** `workstream/fidelity-report-S-110.md`
- **GitHub:** verdict/summary posted to issue #123 and PR #152
- **AC coverage:** 8 / 8 covered, 8 Pass
- **Fidelity verdict:** High · **Highest drift impact:** Minor
- **Blocking gaps:** none
