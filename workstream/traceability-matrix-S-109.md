# Traceability Matrix — S-109 Run Detail (Issue #122)

> **Agent:** `verifier` · **Mode:** Design · **Companion to:** [`test-plan-S-109.md`](test-plan-S-109.md)
> **Source:** [`user-stories-prd-agent-fleet-panel-v2.md`](user-stories-prd-agent-fleet-panel-v2.md) → Story S-109 · Issue [#122](https://github.com/llipe/dev-tasks-agent-fleet/issues/122)
> **Format:** `AC-ID → Test-Case-ID → Observed-Result → Pass/Fail/Drift`
> **Observed-Result** is filled during **Audit Mode** (post-implementation). In Design Mode it reads `pending`.

## AC → Test Case → Result

| AC-ID     | Acceptance Criterion (short)                                   | Test Case(s)                              | Layer            | Type                    | Severity | Observed Result | Verdict |
| --------- | ------------------------------------------------------------- | ----------------------------------------- | ---------------- | ----------------------- | -------- | --------------- | ------- |
| AC-1      | Full-height, no outer scroll; log region owns scroll          | SC-1                                      | Component + Manual | happy + assertion      | critical | pending         | pending |
| AC-2      | Summary: status pill (effective_status), outcome, run ID, repo, metadata grid | SC-1, SC-2, SC-3, SC-20         | Component        | happy + negative + edge | critical | pending         | pending |
| AC-3/AC14 | Artifacts as pill links incl. on `failed`, `rel`, `https:` only | SC-4, **SC-5 (AC14)**, SC-14 (SEC-5), SC-15 | Unit + Component | happy + abuse           | critical | pending         | pending |
| AC-4      | 4-column log grid, `seq` order, level color, step labels      | SC-6, SC-7, SC-16                         | Component        | happy + edge            | major    | pending         | pending |
| AC-5      | Bounded 2,000 initial fetch (SD11) + "load earlier"           | SC-8, SC-9, RT-3, CT-2                     | Unit + Integration | happy + boundary + property | major | pending      | pending |
| AC-6      | Terminal-state banners (`timed_out`/`failed_to_start`) w/ reaper text | SC-10, SC-11, SC-12, RT-4         | Component + Unit | happy + edge + negative | major    | pending         | pending |
| AC-7      | Messages render inert (no `dangerouslySetInnerHTML`)          | **SC-13 (SEC-6)**, RT-2                    | Component + Unit | abuse                   | critical | pending         | pending |
| AC-8      | Log region `aria-live="polite"`                               | SC-17, SC-11                              | Component        | happy + edge            | major    | pending         | pending |
| AC-9      | Unknown run id → 404                                           | SC-18, SC-19                              | Route/Component  | negative + abuse        | major    | pending         | pending |

## Contract & data-layer traceability

| Contract | Consumed from | Test Case | Observed Result | Verdict |
| -------- | ------------- | --------- | --------------- | ------- |
| CT-1 `getRunById → VRunRow \| null` | S-104 | SC-1, SC-18 | pending | pending |
| CT-2 `getRunEvents` SD11 cap under `max_rows=1000` | S-104 | SC-8, SC-9 | pending | pending |
| CT-3 `getRunSteps → RunStepRow[]` | S-104 | SC-6 | pending | pending |
| CT-4 `getRunArtifacts` incl. `pull_request` on failed | S-104 | SC-5 (AC14) | pending | pending |
| CT-5 Row-shape conformance (`types.ts`) | S-104 | integration | pending | pending |
| CT-6 `effectiveStatus` (TS) ≡ `v_runs.effective_status` (SQL) | S-104 parity | SC-2 | pending | pending |

## Mandatory security-negative coverage

| SEC category | Requirement source            | Test Case            | Present? | Observed Result | Verdict |
| ------------ | ----------------------------- | -------------------- | -------- | --------------- | ------- |
| **SEC-5** — artifact URL scheme validation | spec §12 / A10 SSRF/XSS · BR-1 | SC-14 + RT-1         | **YES**  | pending         | pending |
| **SEC-6** — inert log-message rendering    | spec §12 / A10 XSS · BR-1      | SC-13 + RT-2         | **YES**  | pending         | pending |

> Both mandatory security-negative categories are mapped before implementation. Completion **MUST NOT** proceed unless
> SEC-5 and SEC-6 are present and passing.

## Randomized-tactic traceability (deterministic replay required)

| RT-ID | Property                                  | Maps to AC | Seed policy         | Observed Result | Verdict |
| ----- | ----------------------------------------- | ---------- | ------------------- | --------------- | ------- |
| RT-1  | `isSafeArtifactUrl` never throws, https-only | AC-3     | fixed seed, logged  | pending         | pending |
| RT-2  | message inert for arbitrary bytes         | AC-7       | fixed seed, logged  | pending         | pending |
| RT-3  | log-window partition (no gap/dupe)        | AC-5       | seeded, minimized   | pending         | pending |
| RT-4  | banner selection total over `RunStatus`   | AC-6       | exhaustive          | pending         | pending |

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
