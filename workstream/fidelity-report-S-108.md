# Fidelity Report — S-108 Agent Run History

## 1. Header / Verdict

| Field | Value |
| --- | --- |
| **Overall fidelity** | **High** |
| **Highest drift impact** | **Minor** |
| **Drift count** | 5 (0 Critical, 0 Major, 5 Minor) |
| **Scope** | Story S-108 (issue #121), PR #140, branch `story/S-108-run-history` (head `33ccd54`) |
| **Mode** | Audit (grey-box) — codebase + `/workstream` artifacts + test suite + PRD/spec intent |
| **AC coverage** | 7/7 acceptance criteria covered and passing |
| **Blocking gaps** | None. Drift is non-blocking to PR/issue completion by policy. |

Verdict basis: every one of the seven acceptance criteria is implemented, mapped to test evidence, and passing; the Layer 2.5 suite (including the AC10 stale→`timed_out` guard) **ran live** against the local Supabase stack during this audit. No delivered behavior contradicts the story, spec, or DESIGN.md. All five drift items are documentation/coverage-shape observations, each already disclosed by the team; none changes observable behavior.

---

## 2. Human-Readable Summary — what changed and why

S-108 adds the **agent run history screen** at `/agents/[slug]`. Open an agent, and you see every one of its runs, newest first, in a table: the run's status, its outcome, which repository and branch it touched, how long it took, how many steps completed (`n/m`), and when it started. Above the table sits a header with the agent's name, description, and three summary numbers — how many parameters it takes, its typical (median) run time, and its success rate. If the agent doesn't exist, or an operator has disabled it, the page returns a genuine "not found" rather than a misleading empty table that would read as "this agent has never run."

The single most important behavior — and the one the story was written around — is that the status you see is the **true, current** status, not a stale database value. A run that has blown past its time limit but that the background cleanup job (the "reaper") has not yet gotten to will still correctly show **timed out**, not "running." This is verified two ways: an automated test that inserts an over-the-limit run and confirms the screen derives `timed_out` from the live view, and a hand-run procedure (with the reaper paused) whose evidence is recorded in the runbook and PR. Both confirm it works.

Everything here is **read-only** — the panel writes nothing to the database in this story. Features intentionally left out for a later phase (filters, search, repository chips, pagination, and a "live" indicator) are simply not shown, rather than shown as dead buttons. The run rows link forward to a run-detail page that doesn't exist yet (arriving in S-109), and the "Invoke" button links forward to an invoke screen that doesn't exist yet (S-113) — that button is deliberately rendered **disabled** so it can't lead to a broken page. These forward-links are known, recorded wave-boundary gaps, not defects.

Nothing in the delivered work diverges from what was asked. The few notes below are about test-coverage shape and documentation precision, not about the product behaving differently than intended.

---

## 3. Per-AC Result Table

| AC | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
| --- | --- | --- | --- | --- | --- |
| **AC-108.1** | `/agents/[slug]` lists runs newest-first, unfiltered, unpaginated, from `v_runs` | `getAllRunsByAgentSlug` reads `v_runs`, `order created_at desc`, pages `.range()` unbounded below `max_rows=1000`; `page.tsx` renders full list; `buildRunRows` does not re-sort | Task 3.4/3.6/3.10; test-plan CT-8/EC-21/EC-22 | Integration `runs-by-agent.test.ts` "returns runs newest-first, unpaginated, from v_runs" — **ran live**; unit "preserves newest-first order" | **Pass** |
| **AC-108.2** | Each row: status pill, outcome tag, repo (+branch), duration, `n/m`, relative start, per §5.2 | `RunHistoryRow.tsx` renders all six fields; §4.4 grid `118px 122px minmax(0,1fr) 96px 78px 104px 30px` exact in `RunHistoryTable.module.css`; duration/steps/relative from `lib/format.ts` | §5.2 field list; §4.4 grid; task 3.6/3.7; CT-9/CT-13/EC-18/EC-20 | Component "renders the six documented column headers", "running · Xm", "branch alongside repository", edge "0/0", "0m 00s" | **Pass** |
| **AC-108.3** | Displayed status is `effective_status`, not `runs.status` (FR11a) | `buildRunRow`/`buildAgentHeader` derive **every** status (rows + success-rate metric) via shared `lib/domain/status.ts` `effectiveStatus`; `page.tsx` only maps snapshot fields, never compares timestamps | FR11a; task 3.7; CT-2/CT-3/EC-4 | Unit "derives a stale running row into timed_out", "counts a stale running run as timed_out in the success rate"; component "shows timed out (not running) for a stale running row" | **Pass** |
| **AC-108.4** | Reaper paused + past-threshold run → row shows `timed_out`; recorded as evidence (PRD AC10) | Row shaper + `v_runs.effective_status` mirror pinned by parity test; runbook procedure | Runbook `docs/runbooks/issue-121-ac10-reaper-paused.md` with recorded local-stack evidence (`runs.status=running`, `v_runs.effective_status=timed_out`); test-plan G5 | Integration "presents a stale running run as timed_out through the read path (AC10 guard, G5)" — **ran live** | **Pass** |
| **AC-108.5** | Agent header: breadcrumb, name, description, metadata (params count, p50, success rate) | `AgentHeader.tsx` renders breadcrumb `agents / <slug>`, name+tag, description, three metadata spans; `buildAgentHeader` computes p50 (lower-median) + success rate; null→legible copy | §5.2; task 3.5; EC-16/EC-17 | Unit p50 odd/even, zero-run null, success-rate; component "three metadata values with real numbers", "legible copy (no NaN) for a zero-run agent" | **Pass** |
| **AC-108.6** | Rows link to `/runs/[id]`; empty state offers invoke CTA | `RunHistoryRow` links `/runs/${id}`; `RunHistoryTable` empty state renders CTA (disabled while S-113 unbuilt) | Task 3.8; EC-13/EC-19 | Component "links each row to /runs/[id]", "no-runs message with a disabled Invoke CTA", "enabled Invoke link when route available" | **Pass** |
| **AC-108.7** | Unknown slug or disabled agent → 404, not empty list | `shouldRunHistory404(agent)` returns true for null or `!is_enabled`; `page.tsx` calls `notFound()` | Task 3.9; CT-6/EC-3 | Unit `shouldRunHistory404` three cases (null / disabled / enabled) | **Pass** (see D2 on coverage shape) |

---

## 4. Drift Catalog

All drift below is **non-blocking to completion** by the `implement` activity policy (verifier audit is additive and does not gate PR/issue completion). Each item is a coverage-shape or documentation observation; none changes observable behavior.

### D1 — CT-3 mechanical status-discipline gate not delivered as a test (Minor / Intended)

- **Description:** The Wave 3 test plan (CT-3) called for a *mechanical* grep-style unit test — in the shape of `token-discipline.test.ts` — asserting that no module outside `lib/domain/status.ts` restates the SD4 threshold arithmetic (`max_runtime_seconds`/`grace_seconds`/`start_timeout_seconds`) or reads `.status` for display without routing through `effectiveStatus`. No such standing gate exists (`ls panel/tests/unit` shows `token-discipline.test.ts` and `status.test.ts`, but no status-derivation-discipline guard).
- **Impact class:** Minor. **Intent:** Intended (the *behavior* CT-3 protects is fully met — verified below).
- **Evidence source(s):** codebase (`grep max_runtime_seconds|grace_seconds|start_timeout_seconds` over `panel/app/**/*.tsx` finds only field-mapping into the shaper input, no comparison; `grep Math.floor|toLocaleString|Intl.|padStart` over `components/runs/**` finds nothing — CT-10 also satisfied in substance); test suite (no discipline test file); test plan CT-3.
- **Recommendation:** `developer` — optionally add the CT-3/CT-10 mechanical gate so a future third copy of the SD4 expression fails CI permanently. Not required for S-108 correctness; the invariant holds today.

### D2 — Page-level 404 wiring has no test, and a test comment references a non-existent file (Minor / Intended)

- **Description:** `run-history-edge.test.tsx` states the unknown-slug/disabled-agent 404 cases are "asserted directly in `run-history-page.test.ts` against the extracted guard." That file **does not exist** (`ls` confirms). The *pure* guard `shouldRunHistory404` is unit-tested (three cases), but the `page.tsx` wiring that calls `notFound()` on the guard's result has no direct test, and the referenced file name is stale/inaccurate.
- **Impact class:** Minor. **Intent:** Intended (the guard is pure and fully tested; wiring is a one-line `if (shouldRunHistory404(agent)) notFound()`), but the dangling filename reference is an accuracy defect in a test comment.
- **Evidence source(s):** codebase (`page.tsx` guard wiring); test suite (`run-history-edge.test.tsx` comment vs. missing file); AC-108.7.
- **Recommendation:** `developer` — correct the comment to reference the actual `shouldRunHistory404` unit coverage (or add the page-level test the comment promises). CT-6's URL-decode/traversal cases (EC-3: `foo%2Fbar`, `..%2F..`) are covered by Next.js routing + the guard returning 404 for an unresolved slug, but are not asserted explicitly.

### D3 — CT-9 null-tolerance regex assertion is partial (Minor / Intended)

- **Description:** CT-9 recommended a single regex over each row's text content for `null|undefined|NaN|Invalid Date` across the full nullable-field matrix. The delivered tests assert `not.toMatch(/null/)` for the missing-repository case and `not.toMatch(/NaN|undefined/)` for the canceled/zero-run cases, but no single test sweeps the whole matrix (branch-null, finished_at-null-on-terminal, outcome-null, zero-steps) with the combined `null|undefined|NaN|Invalid Date` regex in one place.
- **Impact class:** Minor. **Intent:** Intended (each individual nullable field *is* exercised — outcome `—`, `0/0`, clean repo cell, `—` duration — just not under one consolidated regex).
- **Evidence source(s):** test suite (`run-history.test.tsx`, `run-history-edge.test.tsx`); test plan CT-9.
- **Recommendation:** `developer` — optionally consolidate into the CT-9 combined-regex sweep. No behavior gap observed; the individual assertions already catch the class.

### D4 — AC-108.2 §5.2 "outcome tag" vocabulary extends beyond DESIGN §8.2 enumerated values (Minor / Intended)

- **Description:** DESIGN §8.2 enumerates outcome-tag values `FIXED`, `NO VULNS`, `PARTIAL`, `NEEDS REVIEW`, `—`. The delivered `outcomeLabel` also emits `N/A` for the `not_applicable` outcome (a real `run_outcome` enum value per the schema). This is a faithful extension driven by the data model, but `N/A` is not listed among §8.2's "known values."
- **Impact class:** Minor. **Intent:** Intended (the `not_applicable` outcome exists in the schema and must render *something*; `N/A` is the sensible uppercase tag).
- **Evidence source(s):** codebase (`run-row.ts` `outcomeLabel`); DESIGN §8.2; schema `run_outcome` enum.
- **Recommendation:** `product-engineer` — add `N/A` to the DESIGN §8.2 known-values list (documentation write-back), so the design contract matches the shipped, data-driven vocabulary.

### D5 — AC-106.6-class 1024px geometry deferred; not an S-108 gap but inherited on this screen (Minor / Intended)

- **Description:** The run-history table uses fixed-px grid tracks (§4.4). "Layout holds at 1024px with no horizontal scroll" cannot be asserted in jsdom (no layout engine), so it rests on token-driven CSS + manual comparison, with the Playwright scenario deferred to S-114 (test-plan G7). S-108's tasks recorded the manual 1024/1440px check (task 3.17).
- **Impact class:** Minor. **Intent:** Intended and explicitly deferred (G7 → S-114 #127).
- **Evidence source(s):** codebase (`RunHistoryTable.module.css` fixed tracks); test plan G7; task 3.17; DESIGN §9.
- **Recommendation:** `product-engineer`/`planner` — carry as the already-planned Playwright scenario in S-114. No action in S-108.

---

## 5. Edge-Case and Randomized Test Outcomes

Design Mode test plan (`test-plan-wave3-S-106-S-107-S-108.md`) exists for this scope; S-108-relevant scenarios were checked against delivered tests.

| Scenario | Status | Evidence |
| --- | --- | --- |
| CT-2 (derived status reaches the pill) | Covered | component "shows timed out (not running) for a stale running row" |
| CT-3 (both screens consume derivation, no restatement) | Behaviorally met; mechanical gate absent | grep confirms no restated thresholds; see D1 |
| CT-6 (unknown slug + disabled → 404) | Guard covered; page-wiring/decode not directly tested | unit `shouldRunHistory404`; see D2 |
| CT-8 (bounded below `max_rows`, count stays true) | Covered by paged `.range()` read | `getAllRunsByAgentSlug` paging; integration ran live |
| CT-9 (null-tolerance) | Partial-consolidated | see D3 |
| CT-10 (§7 formatters, no reimplementation) | Met | grep: no `Math.floor`/`Intl`/`padStart`/`toLocaleString` in `components/runs/**` |
| CT-13 (semantic `<table>`, §4.4 grid) | Covered | component role-based queries; CSS grid string exact |
| EC-4 (terminal run never re-derived) | Covered | unit "passes a terminal status through unchanged" |
| EC-16/EC-17 (p50 + success rate boundaries) | Covered | unit p50 odd/even/none, zero-run null rate |
| EC-18 (sub-second/zero duration) | Covered | edge "0m 00s" |
| EC-20 (no-repository run) | Covered | component "missing repository as a clean —" |
| EC-23 (future/`canceled` status fallback) | Covered | edge "canceled" + "paused" pass-through |
| AC10 stale→timed_out (G5 standing guard) | Covered, **ran live** | integration guard executed against local stack this audit |

No randomized/fuzz tests are in S-108 scope; none required by the plan.

**Live execution note (test-plan G2 — a skip is not evidence):** during this audit the Layer 2.5 suite `runs-by-agent.test.ts` **ran live** (Docker + local Supabase up, service key exported from `supabase status -o env`): `[integration] local Supabase Postgres reachable`, 5/5 integration tests passed. Combined S-108 run: **57 passed** (28 unit + 17 component + 7 edge + 5 integration). `typecheck` clean. This matches the PR's claim that the integration suite ran live rather than skipped.

---

## 6. Recommendations (per drift item)

| Drift | Suggested next step | Owner |
| --- | --- | --- |
| D1 | Optionally add the CT-3/CT-10 mechanical status/format-discipline gate | `developer` |
| D2 | Fix the stale `run-history-page.test.ts` comment reference; optionally add page-level `notFound()` test | `developer` |
| D3 | Optionally consolidate CT-9 into one `null|undefined|NaN|Invalid Date` sweep | `developer` |
| D4 | Add `N/A` (`not_applicable`) to DESIGN §8.2 known outcome-tag values | `product-engineer` |
| D5 | Carry 1024px geometry as the planned S-114 Playwright scenario | `product-engineer` / `planner` |

All recommendations are optional relative to S-108 completion. Drift is routed to `product-engineer`'s `activity-drift-reconciliation` flow; `verifier` reports only and applies no changes.
