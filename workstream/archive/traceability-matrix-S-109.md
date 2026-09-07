# Traceability Matrix — S-109 Run Detail (Issue #122)

> **Agent:** `verifier` · **Mode:** Design · **Companion to:** [`test-plan-S-109.md`](test-plan-S-109.md)
> **Source:** [`user-stories-prd-agent-fleet-panel-v2.md`](user-stories-prd-agent-fleet-panel-v2.md) → Story S-109 · Issue [#122](https://github.com/llipe/dev-tasks-agent-fleet/issues/122)
> **Format:** `AC-ID → Test-Case-ID → Observed-Result → Pass/Fail/Drift`
> **Observed-Result** is filled during **Audit Mode** (post-implementation). In Design Mode it reads `pending`.
> **Audit filled 2026 (verifier, Audit Mode):** see [`fidelity-report-S-109.md`](fidelity-report-S-109.md). Verdict **High fidelity, 9/9 Pass, highest drift Minor**.

## AC → Test Case → Result

| AC-ID     | Acceptance Criterion (short)                                   | Test Case(s)                              | Layer            | Type                    | Severity | Observed Result | Verdict |
| --------- | ------------------------------------------------------------- | ----------------------------------------- | ---------------- | ----------------------- | -------- | --------------- | ------- |
| AC-1      | Full-height, no outer scroll; log region owns scroll          | SC-1                                      | Component + Manual | happy + assertion      | critical | Token-driven CSS: `.page{height:100%;overflow:hidden}`, `.log{flex:1;overflow-y:auto}`. 1024px geometry → S-114 | **Pass** |
| AC-2      | Summary: status pill (effective_status), outcome, run ID, repo, metadata grid | SC-1, SC-2, SC-3, SC-20         | Component        | happy + negative + edge | critical | `buildSummary` derives via `effectiveStatus`; pill/tag/short-id/repo/grid render; no null/NaN; stale running→timed_out | **Pass** |
| AC-3/AC14 | Artifacts as pill links incl. on `failed`, `rel`, `https:` only | SC-4, **SC-5 (AC14)**, SC-14 (SEC-5), SC-15 | Unit + Component | happy + abuse           | critical | PR link renders alongside `failed` pill (component + page-wiring + integration CT-4); `rel=noopener noreferrer`; https-only guard | **Pass** |
| AC-4      | 4-column log grid, `seq` order, level color, step labels      | SC-6, SC-7, SC-16                         | Component        | happy + edge            | major    | 4-col `LogLine` grid; step label title→key, blank on null/unresolvable; 8 KB verbatim no-truncate | **Pass** |
| AC-5      | Bounded 2,000 initial fetch (SD11) + "load earlier"           | SC-8, SC-9, RT-3, CT-2                     | Unit + Integration | happy + boundary + property | major | Boundaries 0/1/2000/2001/2500 exact; RT-3 partition (no gap/dupe); integration 2500→2000 + prior slice live | **Pass** |
| AC-6      | Terminal-state banners (`timed_out`/`failed_to_start`) w/ reaper text | SC-10, SC-11, SC-12, RT-4         | Component + Unit | happy + edge + negative | major    | `selectBanner` total fn (RT-4); §8.3 banner + reaper text; none for non-terminal | **Pass** |
| AC-7      | Messages render inert (no `dangerouslySetInnerHTML`)          | **SC-13 (SEC-6)**, RT-2                    | Component + Unit | abuse                   | critical | `<script>`/`<img onerror>` literal + no injected node (querySelector null); no `dangerouslySetInnerHTML` in surface | **Pass** |
| AC-8      | Log region `aria-live="polite"`                               | SC-17, SC-11                              | Component        | happy + edge            | major    | `role="log" aria-live="polite"` present incl. empty region; page-wiring re-asserts | **Pass** |
| AC-9      | Unknown run id → 404                                           | SC-18, SC-19                              | Route/Component  | negative + abuse        | major    | `getRunById` null → `notFound()` (page-wiring throw); parameterized read → null for random UUID (integration) | **Pass** |

## Contract & data-layer traceability

| Contract | Consumed from | Test Case | Observed Result | Verdict |
| -------- | ------------- | --------- | --------------- | ------- |
| CT-1 `getRunById → VRunRow \| null` | S-104 | SC-1, SC-18 | Seeded run returns view row w/ `effective_status`; absent id → null | **Pass** |
| CT-2 `getRunEvents` SD11 cap under `max_rows=1000` | S-104 | SC-8, SC-9 | 2,500-event run → exactly 2,000 newest, no 1,000 truncation (live) | **Pass** |
| CT-3 `getRunSteps → RunStepRow[]` | S-104 | SC-6 | seq-ascending; `[]` when none (live) | **Pass** |
| CT-4 `getRunArtifacts` incl. `pull_request` on failed | S-104 | SC-5 (AC14) | `pull_request` returned for a `failed` run (live) | **Pass** |
| CT-5 Row-shape conformance (`types.ts`) | S-104 | integration | shapes conform; empty → `[]` never null | **Pass** |
| CT-6 `effectiveStatus` (TS) ≡ `v_runs.effective_status` (SQL) | S-104 parity | SC-2 | summary reads derived status; reuses S-104 parity | **Pass** |

## Mandatory security-negative coverage

| SEC category | Requirement source            | Test Case            | Present? | Observed Result | Verdict |
| ------------ | ----------------------------- | -------------------- | -------- | --------------- | ------- |
| **SEC-5** — artifact URL scheme validation | spec §12 / A10 SSRF/XSS · BR-1 | SC-14 + RT-1         | **YES**  | https-only guard; hostile-scheme matrix + 5,000-string seeded fuzz (no-throw, no false-accept); render → no `<a>` for unsafe | **Pass** |
| **SEC-6** — inert log-message rendering    | spec §12 / A10 XSS · BR-1      | SC-13 + RT-2         | **YES**  | `<script>`/`<img onerror>` literal + injected-node absent; no `dangerouslySetInnerHTML` in surface | **Pass** |

> Both mandatory security-negative categories are mapped before implementation. Completion **MUST NOT** proceed unless
> SEC-5 and SEC-6 are present and passing.

## Randomized-tactic traceability (deterministic replay required)

| RT-ID | Property                                  | Maps to AC | Seed policy         | Observed Result | Verdict |
| ----- | ----------------------------------------- | ---------- | ------------------- | --------------- | ------- |
| RT-1  | `isSafeArtifactUrl` never throws, https-only | AC-3     | fixed seed, logged  | 5,000 strings, seed `0x9e3779b9`; never throws, no false-accept | **Pass** |
| RT-2  | message inert for arbitrary bytes         | AC-7       | fixed seed, logged  | `<script>`/`<img onerror>` render literal, no live node | **Pass** |
| RT-3  | log-window partition (no gap/dupe)        | AC-5       | seeded, minimized   | 0..~6000 + 50 seeded trials; union tiles exactly once | **Pass** |
| RT-4  | banner selection total over `RunStatus`   | AC-6       | exhaustive          | banner only for `timed_out`/`failed_to_start`, incl. unknown-future | **Pass** |

## Coverage assertion

- **9/9 acceptance criteria covered** (AC-1…AC-9, with AC14 tracked under AC-3).
- Every AC has **≥1 positive** and **≥1 negative/edge/abuse** scenario (see `test-plan-S-109.md` §8).
- **Both mandatory security-negative categories present** (SEC-5, SEC-6).
- **Status: `covered`** — no uncovered AC; no blocking gaps at design time.

## Non-goals (recorded so an auditor does not flag them as missing)

- SSE / live tail → **S-110 (#123)**. Log virtualization, steps panel, log filters/search/pagination → **v3**.
- 1024px pixel-geometry check → **S-114** (Playwright; jsdom computes no geometry).
- Host/allowlist filtering of artifact URLs is **out of scope**: S-109 validates **scheme only** (BR-1); the panel
  performs no server-side fetch of artifact URLs (documented in SC-15).
