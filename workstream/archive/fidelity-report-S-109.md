# Fidelity Report — S-109 Run Detail (Issue #122)

> **Agent:** `verifier` · **Mode:** Audit (grey-box) · **Phase:** Reporting & Publication (Phase 4)
> **Repository:** `llipe/dev-tasks-agent-fleet` · **Issue:** [#122](https://github.com/llipe/dev-tasks-agent-fleet/issues/122) · **PR:** #150 (draft, base `main`) · **Branch:** `story/S-109-run-detail`
> **Sources cross-checked:** codebase (delivered diff, 23 files / +2,901), `/workstream` artifacts (story, test-plan-S-109, traceability-matrix-S-109, s109-plan), test suite (5 S-109 suites re-run live), PRD/spec intent (story S-109 + DESIGN §4.2/§5.3/§7.5/§8.3).

---

## 1. Verdict

| Field | Value |
| --- | --- |
| **Overall fidelity** | **High** |
| **Highest drift impact** | **Minor** |
| **Drift finding count** | **3** (all Minor; 2 Intended, 1 Undetermined) |
| **AC coverage** | **9/9 covered** (AC-1…AC-9, AC14 tracked under AC-3) — all **Pass** |
| **Mandatory security-negative** | **SEC-5 present & effective · SEC-6 present & effective** (both non-vacuous) |
| **Scope** | `/runs/[id]` read-only screen · no schema/data/API change (documented migration opt-out) |
| **Blocking gaps** | **None** |

> Audit Mode is **additive and non-blocking**: nothing below blocks PR/issue completion, and it does not replace the standing quality gates (`test`/`lint`/`format:check`/`typecheck`/`audit`).

---

## 2. Human-readable summary (what changed and why)

Story S-109 delivers the **Run Detail page** — the single screen an operator opens to see everything one agent run did: its status and timings, the artifacts it produced (like the pull request it opened), and its full log. The goal is to diagnose a run without opening the AWS console.

What was built matches what was asked, closely. The page shows a summary panel (status, outcome, run ID, repository, and a timing grid), a log area that fills the rest of the screen and scrolls on its own while the page itself stays put, and — for runs that timed out or never started — a coloured banner explaining why, using the text the system's watchdog recorded.

Two safety behaviours were specifically required because the log text and artifact links are written by the agent (untrusted), and both are genuinely in place:

- **Artifact links are only clickable when they point at a proper secure (`https:`) address.** Anything suspicious — a `javascript:` trick, a `data:` blob, an insecure `http:` link, or a broken value — is shown as plain non-clickable text. This was verified with a large battery of hostile inputs, including a 5,000-string fuzz run, and the check never crashes.
- **Log messages are shown as literal text and never executed.** A message containing `<script>` or an image-based attack shows up as the exact characters, and no live element is created. Verified by inspecting the rendered page for injected elements — the test would fail if anything executed.

The **highest-risk requirement (AC14)** — showing the pull-request link even on a *failed* run rather than hiding it behind the failure — was explicitly confirmed at three levels (component, whole-page, and database read).

The log is deliberately capped at the most recent **2,000 events** because that table grows far faster than any other; when a run has more, a "Load earlier" control fetches the previous slice. A property test proves the windows fit together perfectly — no event shown twice, none skipped.

Nothing was cut that was in scope. Two items are **deliberately deferred and recorded in the plan** (not gaps): the exact 1024px-width pixel check moves to S-114 (the test tools used here don't compute on-screen geometry), and the live-updating log tail is the next story, S-110 — this story already leaves a stable hook in the markup for it.

**Bottom line:** High fidelity. Every acceptance criterion is met and evidenced, both mandatory security checks are real and effective, and the only drift is minor and intentional.

---

## 3. Per-AC result table

| AC-ID | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
| --- | --- | --- | --- | --- | --- |
| **AC-1** | Full-height, no outer scroll; log region owns the scroll (DESIGN §4.2) | `app/runs/[id]/page.module.css` `.page{height:100%;overflow:hidden}`; `LogViewer.module.css` `.log{flex:1;min-height:0;overflow-y:auto}` | plan 1.10/1.18; test-plan SC-1 | Token-driven CSS present; layout structurally correct. Pixel-geometry (1024px) deferred to S-114 (jsdom computes no geometry) | **Pass** |
| **AC-2** | Summary: status pill from `effective_status`, outcome tag, short mono run ID, repository, metadata grid | `run-detail.ts` `buildSummary` derives via `effectiveStatus` (SD4); `RunSummary.tsx` renders pill/tag/runId/repo/`<dl>` grid | test-plan SC-1/2/3/20 | `run-detail.test.ts` (derived status, dash-not-NaN, clocks); `run-detail.test.tsx` (pill, outcome, short id, no null/NaN) | **Pass** |
| **AC-3 / AC14** | Artifacts as pill links **incl. on `failed`**, `rel="noopener noreferrer"`, `https:` only | `ArtifactLinks.tsx` receives artifacts (not status) → no failure-hide path; anchor only when `isSafeArtifactUrl`; `rel` hardened; `artifact-url.ts` `https:`-only via WHATWG `URL` | test-plan SC-4/5/14/15; plan 1.11/1.20 | `run-detail.test.tsx` PR link alongside `failed` pill + `rel`; page-wiring PR-on-failed end-to-end; integration CT-4 read side | **Pass** |
| **AC-4** | 4-column log grid (time/level/step/message) ordered by `seq`, level color, hover; step labels via `run_steps` | `LogViewer.tsx` maps `LogLine` grid; `LogLine.tsx` 4-column; `buildLogLines` labels via `stepById`, title→key fallback, blank on null/unresolvable | test-plan SC-6/7/16 | `run-detail.test.ts` step labeling, null step blank, verbatim message; `run-detail.test.tsx` 8 KB no-truncate | **Pass** |
| **AC-5** | Bounded 2,000 initial fetch (SD11) + "load earlier" | `log-window.ts` `selectRecentWindow`/`priorWindowRange`; `getRunEvents` paged `.range()` under `max_rows=1000`; `getRunEventsInRange`; page server action `loadEarlier` | test-plan SC-8/9, RT-3, CT-2 | `log-window.test.ts` boundaries 0/1/2000/2001/2500 + RT-3 partition property; integration CT-2 (2500→2000) + load-earlier slice (live) | **Pass** |
| **AC-6** | Terminal-state banners for `timed_out`/`failed_to_start` (DESIGN §8.3) w/ reaper text | `run-detail.ts` `selectBanner` (total fn); `StateBanner.tsx` §8.3 border/tint + inert `error_message` | test-plan SC-10/11/12, RT-4 | `run-detail.test.ts` RT-4 total-function; `run-detail.test.tsx` banner + inert text; page-wiring timed_out reaper text | **Pass** |
| **AC-7** (SEC-6) | Messages render inert — never `dangerouslySetInnerHTML`; HTML/script displays literally | `LogViewer`/`LogLine` render `message` as JSX text child (React auto-escape); no `dangerouslySetInnerHTML` anywhere in surface | test-plan SC-13, RT-2; plan 1.15/1.24 | `run-detail.test.tsx` `<script>` & `<img onerror>` literal + `region.querySelector('script'/'img')` null; banner inert too | **Pass** |
| **AC-8** | Log region `aria-live="polite"` | `LogViewer.tsx` `role="log" aria-live="polite" data-sse-mount="run-log"` | test-plan SC-17; plan 1.25 | `run-detail.test.tsx` aria-live assertion + empty-region still aria-live; page-wiring re-asserts | **Pass** |
| **AC-9** | Unknown run id → 404 | `page.tsx` `getRunById` null → `notFound()`; parameterized read (no injection) | test-plan SC-18/19; plan 1.26 | page-wiring `notFound()` throw for unknown id; integration null for random UUID | **Pass** |

**Contract checks (CT-1…CT-6):** all consumed from S-104 and re-exercised — `getRunById`→`VRunRow|null` w/ `effective_status` (CT-1), SD11 cap under `max_rows=1000` (CT-2), `getRunSteps` seq-asc (CT-3), `getRunArtifacts` incl. `pull_request` on `failed` (CT-4), row shapes (CT-5), `effectiveStatus`≡`v_runs.effective_status` reused via S-104 parity (CT-6). Integration suite ran live per verified state.

---

## 4. Mandatory security-negative categories — effectiveness check

Both are **present and genuinely effective (non-vacuous)** — each asserts the security-relevant *consequence*, not merely that a function was called.

### SEC-5 — Artifact URL scheme validation (spec §12 / A10 SSRF/XSS)

- **Implementation:** `lib/domain/artifact-url.ts` `isSafeArtifactUrl` — pure, total; parses via WHATWG `URL`, returns `true` only when `protocol === "https:"`; `try/catch` returns `false` (never throws) on malformed input. `ArtifactLinks.tsx` renders an `<a href>` **only** when the guard passes; every other value is inert `<span>`.
- **Non-vacuous evidence** (`tests/unit/artifact-url.test.ts`):
  - Positive: `https:`, https w/ port/path/query/fragment, mixed-case `HTTPS:`/`HtTpS:` accepted.
  - Negative: `http:`, `javascript:` (+ mixed-case + leading-space + tab-obfuscated `java\tscript:`), `data:`, `vbscript:`, `file:`, `ftp:`, relative (`/runs/123`, `github.com/x`, `//evil.com/x`), empty, whitespace-only, `null`/`undefined` — all rejected.
  - **RT-1 fuzz:** 5,000 pseudo-random strings (documented seed `0x9e3779b9`, xorshift32) — asserts **never throws**, always returns boolean, and **no false-accept** (any `true` must start `https:`).
  - Render consequence (`run-detail.test.tsx`): `javascript:` and `http:` artifacts produce **no** `<a>` (`queryByRole("link")` null) but keep inert label text.
- **Verdict:** effective. No non-`https:` value can reach an `href`; validator is total.

### SEC-6 — Inert log-message rendering (spec §12 / A10 XSS)

- **Implementation:** messages flow `getRunEvents` → `buildLogLines` (carries raw string verbatim, no escape/mangle) → `LogLine` renders as a **JSX text child** (React auto-escapes). No `dangerouslySetInnerHTML` exists anywhere in the S-109 surface (grep-confirmed). `StateBanner` renders `error_message` the same inert way.
- **Non-vacuous evidence** (`tests/component/run-detail.test.tsx`):
  - `<script>alert(1)</script>` renders as literal text **and** `region.querySelector("script")` is `null`.
  - `<img src=x onerror="alert(1)">` renders literally **and** `region.querySelector("img")` is `null`.
  - Banner path: `<script>` literal + no injected node.
  - 8 KB message rendered in full (no truncation, DESIGN §7.5).
- **Verdict:** effective. The tests would fail if any live node were injected; they assert absence of the executed element, not just presence of the string.

---

## 5. Edge-case & randomized outcomes (against the prior test plan)

| Case | Scenario | Result |
| --- | --- | --- |
| 0 / 1 / 2000 / 2001 / 2500 events | SC-8, log-window unit | Pass — boundaries exact; `hasEarlier` correct at 2000 (false) vs 2001 (true) |
| RT-1 URL fuzz (5,000, seeded) | never-throw / https-only | Pass |
| RT-2 inert message | `<script>`/`<img onerror>` | Pass — no injected node |
| RT-3 window partition | 0..~6000, 50 seeded trials | Pass — no gap, no duplicate, seq-monotonic union |
| RT-4 banner total-function | all statuses + unknown-future | Pass — banner only for `timed_out`/`failed_to_start` |
| null `step_id` | SC-7 | Pass — blank step cell, no "undefined" |
| no repository / null `finished_at` | SC-3 | Pass — no `null`/`NaN`; dashes |
| `failed_to_start`, no steps/events | SC-11 | Pass — banner only, empty log graceful (`[]` from integration) |
| load-earlier slice | SC-9 | Pass — prior 1..500 with no overlap (live integration) |

Independent re-run: **69/69 S-109 non-integration tests pass** (`vitest run` on the five suites). Integration suite is Docker+service-role-key gated and ran live per the verified state (Python 452 + panel 711 passed / 4 skipped; `make validate` exit 0).

---

## 6. Drift catalog

All drift is **Minor** and **non-blocking to completion**.

### D1 — "Load earlier" is a server action, not raw `getRunEvents` reuse — *Minor, Intended*
- **Description:** The plan (task 1.8) suggested reusing `getRunEvents` where possible and adding a windowed variant "only if needed." A new helper `getRunEventsInRange` plus a page-level `loadEarlier` server action were added.
- **Evidence:** `queries.ts` `getRunEventsInRange`; `page.tsx` inline `"use server"` action. This is the cleaner realization of the `priorWindowRange` contract (inclusive seq slice, ascending), and the plan explicitly permitted a windowed variant. Contract honored (paged under `max_rows`, no overlap — proven by integration).
- **Impact class:** Minor · **Intent:** Intended · **Source:** codebase vs plan.
- **Recommendation:** No action needed.

### D2 — A dedicated `run-detail.ts` domain module beyond the two named pure files — *Minor, Intended*
- **Description:** Story "Files to Create/Modify" named `artifact-url.ts` and `log-window.ts`. The delivery adds a third pure module `lib/domain/run-detail.ts` (`selectBanner`/`buildLogLines`/`buildSummary`).
- **Evidence:** `lib/domain/run-detail.ts` (212 lines, 100%/97.22% covered per qa-engineer). It concentrates the presentation *decisions* out of JSX (banner selection, log-line projection, summary derivation via shared `effectiveStatus`), consistent with the S-107/S-108 `lib/domain/*` pattern and the "keep business logic out of presentational JSX" convention.
- **Impact class:** Minor · **Intent:** Intended · **Source:** codebase vs story file list.
- **Recommendation:** No action needed (net-positive structural choice, matches existing convention).

### D3 — SD11 sizing note (observed events-per-run) not yet recorded — *Minor, Undetermined*
- **Description:** BR-3 / story business rule and plan task **1.27** (manual: open a real Phase 1 run, record observed events-per-run for the SD11 sizing note) and **1.33/1.34/1.35** remain unchecked in the plan. Task 1.27 produces the empirical sizing datapoint; it is a manual/live step, not an automated AC.
- **Evidence:** `tasks-...-s109-plan.md` tasks 1.27, 1.33–1.35 unchecked. No AC depends on it (the 2,000 bound is a bound, not a capacity estimate — BR-3). 1.34 is *this* audit.
- **Impact class:** Minor · **Intent:** Undetermined (a deferred manual observation, not a behavior defect) · **Source:** `/workstream` plan vs delivery.
- **Recommendation:** `product-engineer` / operator to close via `activity-drift-reconciliation` — record the observed events-per-run once a real 60-minute `llm_fix` run exists (or explicitly re-defer). Not a code fix; does not block PR readiness.

### Recorded deferrals (NOT drift — do not miscount)
- **1024px pixel-geometry check → S-114** (Playwright; jsdom computes no on-screen geometry). AC-1 layout is delivered as token-driven CSS.
- **SSE live tail → S-110 (#123).** Story is the *static* half of FR12; a stable `data-sse-mount="run-log"` hook is left in `LogViewer` per BR-7.
- **Steps panel, log virtualization, log filters/search/pagination → v3.**
- **Host/allowlist filtering of artifact URLs → out of scope** (S-109 validates scheme only, BR-1; panel performs no server-side fetch, so rendering triggers no SSRF — SC-15).

---

## 7. Recommendations (per finding)

| Finding | Suggested next step |
| --- | --- |
| D1 | No action needed |
| D2 | No action needed |
| D3 | `product-engineer` `activity-drift-reconciliation`: record the SD11 events-per-run observation (task 1.27) or re-defer explicitly; close plan tasks 1.33/1.35 in the normal closeout flow |
| SEC-5 / SEC-6 | No action — both effective and non-vacuous |
| All ACs | No action — 9/9 Pass |

---

## 8. Output contract

- **Mode / phase:** Audit / Phase 4 (Reporting & Publication)
- **Source artifact:** `workstream/user-stories-prd-agent-fleet-panel-v2.md` → Story S-109 (+ DESIGN §4.2/§5.3/§7.5/§8.3); companion test-plan-S-109 / traceability-matrix-S-109
- **Files created:** `workstream/fidelity-report-S-109.md`
- **GitHub target:** Issue #122 / PR #150 — post §1 Verdict + §2 Human-readable summary
- **AC coverage:** 9/9 covered, 9/9 Pass (AC14 under AC-3 explicitly confirmed)
- **Overall fidelity:** High · **Highest drift impact:** Minor · **Drift count:** 3 (2 Intended, 1 Undetermined)
- **Blocking gaps:** None
