# Test Plan — CI audit gates (#252) and run-detail follow-ups (#245, #244)

**Mode:** Design Mode (pre-implementation)
**Scope:** Planner batch `workstream/tasks-issue-252-245-244-audit-gates-and-run-detail.md`. Issues #252, #245, #244, 18 acceptance criteria.
**Prepared by:** verifier
**Date:** 2026-10-13
**Companion:** `workstream/traceability-matrix-issue-252-245-244.md`

**Coverage status:** all 18 ACs covered (≥1 positive and ≥1 negative/edge each). There are 3 design findings the task list does not yet account for (§2). They are non-blocking, but F-1 changes what "AC3 passes" means for #252.

## Changelog

| Version | Date       | Summary                                                                        | Author   |
| ------- | ---------- | ------------------------------------------------------------------------------ | -------- |
| 1.0     | 2026-10-13 | Initial compliance test plan from the three refinements, the decision log, and the task list | verifier |
| 1.1     | 2026-10-13 | F-1/F-2 folded into the task list (1.5a, 2.6); F-3 resolved to rendered rows (D-12) | planner |

---

## 1. Source Input Summary

- **Refinements:** `workstream/issue-252-fix-deps-audit-gates-refinement.md`, `issue-245-run-detail-unscrollable-summary-refinement.md`, `issue-244-run-detail-refresh-on-terminal-refinement.md` (all v1.0).
- **Decisions:** `workstream/decisions-run-detail-followups-and-audit.md` D-01…D-11.
- **Task list:** `workstream/tasks-issue-252-245-244-audit-gates-and-run-detail.md`, tasks 1.0 (#252), 2.0 (#245), 3.0 (#244), 4.0 (close-out).
- **Test taxonomy** (`TESTING.md`): Layer 1 unit and Layer 2 component (Vitest, jsdom), Layer 2.5 integration (local Supabase), E2E (Playwright, `panel/tests/e2e/`, one worker). Python agents: pytest `unit`/`component` markers. No new layer is introduced.
- **Observed surfaces this plan relies on** (read, not assumed):
  - The SSE relay closes on `isRunTerminal(run, now)`, i.e. the **effective** status, not only the raw one (`app/api/runs/[id]/events/stream/route.ts`). It also emits a `closed` frame with reason `not_found` for a deleted or unknown run.
  - `tests/e2e/fixtures/seed.ts::seedArtifact` inserts `run_id, type, title, url` only. It **cannot seed `metadata`**, so an `audit_report` with findings cannot be seeded today.
  - `tests/component/live-log-viewer.test.tsx` already drives `useRunStream` through an injected `FakeEventSource` factory. `next/navigation` mocks exist in `Sidebar.test.tsx` and related tests.
  - Both agents' `credentials.py` share an identical `jwt.encode({"iat","exp","iss"}, key, algorithm="RS256")` call. The `test_credentials.py` suites **mock the `jwt` module**.
  - There is no property-testing library in the panel (`fast-check` is absent).

## 2. Design Findings (pre-implementation)

| ID | Finding | Affects | Impact | Intent | Recommendation |
| --- | --- | --- | --- | --- | --- |
| F-1 | #252 AC3 ("existing credential tests pass on PyJWT 2.15.1") is **vacuous**: `test_credentials.py` patches `jwt`, so a breaking change in `jwt.encode` would not be detected. | #252 AC3, task 1.5 / 1.11 | Major | Unintended | `developer` adds a real-library test per agent (TC-252-3a): generate an RSA key with `cryptography`, call the real signing path, then `jwt.decode` with the public key and assert header `alg=RS256` plus the `iat`/`exp`/`iss` claims and the 600s window. Add it as a sub-task under 1.5. |
| F-2 | No E2E fixture can seed `audit_report.metadata`. #245 AC1/AC3 and #244 AC1 E2E scenarios depend on one. | #245 task 2.6, #244 task 3.5 | Minor | Unintended | Extend `seedArtifact` with an optional `metadata` JSON param (backward compatible: defaults to `null`). Task 2.6 implies this, but the list of files to touch doesn't include `seed.ts`. |
| F-3 | #245's open/closed threshold "≤10 rows" is ambiguous between `view.rows.length` (rendered rows, ≤ `MAX_ROWS`) and `view.totalFindings` (agent-reported total, which may differ from the rows array). | #245 AC3 | Minor | Undetermined | Treat **rendered rows** (`rows.length`) as the threshold input, because that is what takes up space. EC-245-2 pins the behavior; `product-engineer` confirms during implementation or audit. |

## 3. Acceptance Criteria Extraction

| AC-ID | Issue | Statement (short) |
| --- | --- | --- |
| AC-252-1 | #252 | `pnpm --filter panel run audit` exits 0 under Node 22; there is no high/critical prod advisory; only the two moderate `next` advisories remain |
| AC-252-2 | #252 | `pip-audit . --strict` exits 0 in both agents on 3.13 and 3.14 |
| AC-252-3 | #252 | GitHub App JWT signing (RS256) works on PyJWT 2.15.1 |
| AC-252-4 | #252 | `make validate` passes locally; both CI jobs are green on the PR |
| AC-252-5 | #252 | Panel builds with `sharp` 0.35.5; E2E and auth-gate parser are unaffected |
| AC-252-6 | #252 | Both agents redeployed; a real invocation of each passes GitHub App auth and reaches a terminal status; hash recorded |
| AC-245-1 | #245 | 50 findings at 1280×720: steps panel, toolbar, and viewer visible; viewer scrolls (closed and open) |
| AC-245-2 | #245 | Summary line always visible; mouse/keyboard toggle; native `open` state; `<caption>` and `th[scope=col]` kept |
| AC-245-3 | #245 | ≤10 rows open by default, ≥11 closed; log section ≥240px with the table open |
| AC-245-4 | #245 | Empty state, fallback, and "N more not shown." unchanged apart from the wrapper |
| AC-245-5 | #245 | 50-row component test (default closed, toggle, `open`, all rows in DOM); existing tests pass |
| AC-245-6 | #245 | DESIGN.md §5.3 updated plus changelog row |
| AC-244-1 | #244 | Live run → terminal: pill, outcome, finished, artifacts, findings update within 5s, no reload |
| AC-244-2 | #244 | Already-terminal run: no refresh, no extra server render |
| AC-244-3 | #244 | ≤1 refresh per mount; errors, reconnects, and `authStopped` never trigger it |
| AC-244-4 | #244 | Wiring test: once-only after 500ms; already-terminal; unmount-before-debounce |
| AC-244-5 | #244 | Step/level filter persists across the refresh |
| AC-244-6 | #244 | Existing run-detail / live-log-viewer / use-run-stream / page-wiring tests pass |

**Non-goal boundary (asserted, not just omitted):** `next` stays at 15.5.25 in #252; no change to `MAX_ROWS`, the stream route, or the `closed` frame contract; `RunSummary` stays a server component; no polling.

## 4. E2E Scenarios

Severity: S1 = would ship the reported defect again or a security regression; S2 = AC unmet; S3 = polish.

### #252 — gate and deploy scenarios (pipeline-level, not Playwright)

| ID | Scenario | Expected (observable) | Sev | AC |
| --- | --- | --- | --- | --- |
| SC-252-1 | Run `pnpm --filter panel run audit` on the PR head under Node 22 | Exit 0; JSON lists no `high`/`critical`; the remaining advisories are exactly GHSA-4jqv-mc3x-m676 and GHSA-mcj8-r9mp-w47p | S1 | AC-252-1 |
| SC-252-1N | Revert only the `sharp` override locally and re-run the audit | Exit 1 naming GHSA-wq5f-xc86-pv6w, which proves the gate still bites and the green result is not a soft-pass | S1 | AC-252-1 |
| SC-252-2 | CI `python-quality` matrix (2 agents × 3.13/3.14) on the PR | All 4 "Dependency audit (pip-audit)" steps succeed | S1 | AC-252-2 |
| SC-252-4 | CI on the PR | `python-quality` and `panel-quality` both green; no step `continue-on-error` added | S2 | AC-252-4 |
| SC-252-4N | Inspect the audit step log on the PR | Audit wrapper reports a real verdict, not the transport-failure soft-pass warning (`audit.mjs` soft-passes on registry outages) | S2 | AC-252-4 |
| SC-252-5 | `pnpm --filter panel build` and `Dockerfile.panel` build | Build succeeds; `sharp` resolves 0.35.5 in the lockfile; the E2E job and the `panel-auth-check.mjs` unit test pass | S2 | AC-252-5 |
| SC-252-6 | Post-merge: invoke `dependency-update` and `security-analyst` (`audit_only`) on a real repo after redeploy | Both runs reach a terminal status past GitHub App auth (no `CredentialError`); deployed-state hash changed and recorded on #252 | S1 | AC-252-6 |
| SC-252-6N | Same invocation, examined for auth failure modes | No 401 from `POST /app/installations/{id}/access_tokens` in run events; if one appears, roll back to the previous image (D-10) and reopen | S1 | AC-252-6 |

### #245 — Playwright (`panel/tests/e2e/run-detail-layout.spec.ts`, new; viewport 1280×720)

| ID | Scenario | Expected | Sev | AC |
| --- | --- | --- | --- | --- |
| SC-245-1 | Seed a terminal run with a 50-finding `audit_report` (F-2), open `/runs/<id>` | Findings summary line visible; disclosure closed; steps panel, "Log level" toolbar, and log viewer within the viewport; scrolling the log viewer changes its `scrollTop` | S1 | AC-245-1, AC-245-3 |
| SC-245-1b | Same, then open the disclosure | Table body is scrollable within itself; the log section's bounding box height is ≥240px; the toolbar is still in the viewport; `document.scrollingElement.scrollHeight` equals the viewport height (no outer scroll) | S1 | AC-245-1, AC-245-3 |
| SC-245-2 | Keyboard: Tab to the findings `<summary>`, press Enter, then Space | Toggles open, then closed; focus ring visible; `details[open]` attribute reflects the state | S2 | AC-245-2 |
| SC-245-3 | Seed a run with 3 findings | Disclosure open by default; all 3 rows visible without interaction | S2 | AC-245-3 |
| SC-245-3N | Seed a run with 0 findings | "No findings." text and no `<details>` element | S3 | AC-245-4 |

### #244 — Playwright (extend `panel/tests/e2e/live-tail.spec.ts`)

| ID | Scenario | Expected | Sev | AC |
| --- | --- | --- | --- | --- |
| SC-244-1 | Seed a `running` run, open `/runs/<id>`, wait for the live log, then insert an `audit_report` (3 findings) and a `pull_request` artifact, then set `status=succeeded`, `outcome`, `finished_at` | Within 5s, with no `page.reload()`: pill reads succeeded, outcome tag present, "finished" metadata present, artifact pills present, findings summary line ("3 findings") present | S1 | AC-244-1 |
| SC-244-1b | Same, with a step and "error" level selected before the terminal update | The same filter selections are still applied after the viewer swap | S2 | AC-244-5 |
| SC-244-2 | Open `/runs/<id>` on an already-`succeeded` run; count document/RSC requests for the route over 3s | Exactly the initial render; no RSC refresh request | S2 | AC-244-2 |
| SC-244-3 | Live run, then expire the session (clear auth cookies), then set the run terminal | The live tail stops (S-121 `authStopped`); no automatic refresh or redirect loop; manual navigation goes to `/login` | S1 | AC-244-3 |
| SC-244-4 | Live run with the reaper paused, past `max_runtime + grace` | The relay emits `closed` (effective `timed_out`); the page refreshes once and renders the terminal viewer and the timed_out banner | S2 | AC-244-1 |

**Uncoverable at E2E:** AC-245-6 (doc review), AC-252-2/AC-252-4 (CI-only), AC-244-4/AC-244-6 (test-suite assertions by definition), and the screen-reader announcement in AC-245-2 (manual check, recorded in the PR).

## 5. Contract Validation Scenarios

| ID | Boundary (provider → consumer) | Scenario | Expected | AC |
| --- | --- | --- | --- | --- |
| CT-1 | PyJWT (lib) → agent `credentials.py` → GitHub API | Valid: real `jwt.encode` with an RSA key on 2.15.1 | Compact JWS; header `{"alg":"RS256","typ":"JWT"}`; payload has integer `iat`, `exp`, string `iss`; `exp - iat == 600` | AC-252-3 |
| CT-2 | same | Type: `iss` passed as `str(app_id)` | Still a string claim (PyJWT ≥2.10 rejects a non-string `iss` on decode; GitHub requires a string or int) | AC-252-3 |
| CT-3 | same | Bad key: a malformed PEM | Raises, and the agent classifies it as `CredentialError` (existing #106/#108 behavior), not an unhandled error | AC-252-3 |
| CT-4 | SSE relay → `useRunStream` | `closed` frame with each terminal reason, including `not_found` | `closedReason` is set once; the refresh effect schedules once. For `not_found`, the refresh renders the 404 page (accepted: the run no longer exists) | AC-244-1, AC-244-3 |
| CT-5 | same | Frames after `closed` (late `run`/`event`) | Ignored; no second schedule | AC-244-3 |
| CT-6 | same | Missing field: a `closed` frame with no/empty reason | Still terminal for refresh purposes, or explicitly ignored; the test pins whichever the hook does today, so it is not left undefined | AC-244-3 |
| CT-7 | Agent `audit_report.metadata` → `AuditReportPanel` | Extra unknown fields per finding | Ignored; the row renders | AC-245-4 |
| CT-8 | same | Type mismatch: `findings` is not an array, or `line_start` is a string | Falls back to the key/value view or a null line, with no disclosure crash | AC-245-4 |
| CT-9 | same | Over `MAX_ROWS` (600 findings) | 500 rows in the DOM once opened; "100 more not shown." inside the disclosure body; disclosure closed by default | AC-245-3, AC-245-4 |
| CT-10 | pnpm `audit --json` → `scripts/audit.mjs` | pnpm version unchanged (10.11.0) | The wrapper parses the same shape; no wrapper change in this PR (an assertion of absence) | AC-252-1 |

API versioning: N/A. No versioned endpoint changes. The `closed`-frame contract is explicitly frozen (non-goal).

## 6. Edge-Case Catalog

| ID | Category | Edge case (concrete) | Expected | Risk if missed | AC |
| --- | --- | --- | --- | --- | --- |
| EC-245-1 | Data boundaries | Exactly 10 rows / exactly 11 rows | 10 → `open`; 11 → closed | Off-by-one reintroduces the overflow at 11–~20 rows | AC-245-3 |
| EC-245-2 | Input domain | `totalFindings=50` but `rows.length=8` (agent total ≠ rows) | Open (rendered rows decide, F-3) | Wrong default for partial reports | AC-245-3 |
| EC-245-3 | Data boundaries | Two `audit_report` artifacts on one run (12 and 4 rows) | First closed, second open; each independently toggleable | Shared state or a single-panel assumption | AC-245-3 |
| EC-245-4 | Input domain | Finding `message` is 5,000 characters with no spaces | Wraps (`overflow-wrap: anywhere`) inside the capped body; no horizontal page scroll | Page width blowout | AC-245-1 |
| EC-245-5 | Auth/untrusted input | `message`/`rule_id` containing `<summary>`, `<details open>`, `</table><script>` | Rendered as literal text; the DOM has exactly one `<details>`/`<summary>` per report | Markup injection breaking the disclosure or XSS | AC-245-2 |
| EC-245-6 | Resource exhaustion | 1280×600 viewport (below AC1's 720) with the table open | Log section still ≥240px (the cap yields first) | The documented floor silently fails on short screens | AC-245-3 |
| EC-245-7 | State transitions | User opens a >10-row disclosure, then #244's refresh re-renders the server tree | Open/closed state after refresh is pinned by a test, whether preserved or reset to default; the PR records which | Surprise collapse while reading | AC-244-1, AC-245-3 |
| EC-244-1 | Timing | `closed` arrives, then unmount at 499ms | No refresh | Refresh of a page the user left | AC-244-4 |
| EC-244-2 | Timing | Writer's `finished_at`/artifacts land at 700ms (after the 500ms debounce) | One refresh; stale summary accepted; no retry (D-08) | Retry loop if someone "fixes" it later | AC-244-3 |
| EC-244-3 | Idempotency | Two `closed` frames (reconnect race) 100ms apart | One refresh | Double server render | AC-244-3 |
| EC-244-4 | Auth | 401 on reconnect (`authStopped`), then a `closed` frame is never received | No refresh | Refresh triggers a login redirect mid-read; S-121 regression | AC-244-3 |
| EC-244-5 | State transitions | Page rendered live, but the run was already terminal by connect time (relay emits `closed` immediately) | One refresh, then terminal viewer | Run stuck on the live viewer with an empty tail | AC-244-1 |
| EC-244-6 | Failure modes | Refresh's server render throws (Supabase down) | Next error boundary shows; no further refresh attempts | Refresh storm against a failing backend | AC-244-3 |
| EC-244-7 | Failure modes | `closed` reason `not_found` (run deleted mid-view) | Single refresh, then 404 page | Undefined behavior on deletion | AC-244-1 |
| EC-252-1 | Failure modes | npm registry advisory endpoint unreachable during CI audit | `audit.mjs` soft-passes with a warning; the reviewer must not read that as AC-252-1 met (SC-252-4N) | False green | AC-252-1 |
| EC-252-2 | Idempotency | `pnpm install --frozen-lockfile` in CI after the override change | Succeeds (lockfile committed and consistent with overrides) | CI install fails on lockfile drift | AC-252-4 |
| EC-252-3 | Data boundaries | Override selectors (`sharp@<0.35.5`) must not match and downgrade a future higher version | `pnpm why sharp` shows exactly 0.35.5; no package downgraded vs `main` (lockfile diff review) | Silent downgrade | AC-252-5 |
| EC-252-4 | API versioning | PyJWT 2.15 deprecations emitted as warnings under `-W error` (if pytest config sets it) | No new warnings fail the suite | Gate flips red after merge | AC-252-3 |
| EC-252-5 | Failure modes | Redeploy succeeds but the image still resolves PyJWT 2.13.0 (stale build cache) | `pip show pyjwt` in the built image (or deploy log) shows 2.15.1 before the live invocation | Repo fixed, production still exposed | AC-252-6 |

Categories with no case: none. All 9 categories are represented: input domain, state, timing, idempotency, failure, auth, data boundaries, resource exhaustion (EC-245-6), and API versioning (EC-252-4).

**Security-negative set (mandatory):** EC-245-5 (untrusted metadata in the disclosure), EC-244-4 and SC-244-3 (refresh never bypasses or loops on auth), EC-252-3 (no downgrade via overrides), CT-3 (bad key classified, not leaked), SC-252-6N (no auth failure after redeploy).

## 7. Randomized Tactics and Seed Policy

No new dependency. These use a seeded `mulberry32` PRNG inside Vitest. Adding `fast-check` would need a pinned version and is not justified for three tactics.

**Seed policy:** seed = `Number(process.env.TEST_SEED ?? <fixed default>)`, logged in the test name or failure message. The CI default is fixed for deterministic gating. Replay: `TEST_SEED=<n> pnpm --filter panel exec vitest run <file> -t "<tactic>"`. Shrink: report the minimal failing input by bisecting the generated size or sequence length (described per tactic).

| ID | Type | Target | Generator | Oracle (deterministic) | Default seed | Shrink | AC |
| --- | --- | --- | --- | --- | --- | --- | --- |
| RT-1 | Property | `AuditReportPanel` default state | 200 iterations; row count n ∈ [0, 600], random severities/tools | `details.open === (min(n,500) ≤ 10)` when n > 0; no `<details>` when n = 0; rows in DOM = `min(n,500)`; truncation notice iff n > 500 | 245001 | Binary-search n | AC-245-3, AC-245-4 |
| RT-2 | Fuzz | `AuditReportPanel` untrusted strings | 300 findings with random unicode, HTML fragments, `__proto__`/`constructor` severities | Render does not throw; exactly one `details` and one `summary` per report; no `script` element; text content contains the raw strings | 245002 | Drop findings, then shorten strings | AC-245-2 |
| RT-3 | Stateful random walk | refresh effect + `FakeEventSource` + fake timers | 500 walks of length 1–30 over {line, run-status push, error, reconnect, 401, `closed`(reason), advance(0–1000ms), unmount} | `refresh` calls ≤ 1; = 1 iff a `closed` occurred with no prior 401 or unmount and ≥500ms of mounted time elapsed after it; never called before 500ms | 244001 | Remove steps from the walk while it still fails | AC-244-3, AC-244-4 |

#252 has no randomized surface (pinned versions plus a gate). That is explicitly N/A.

Failure triage follows the verifier workflow: capture the seed, replay ×3, minimize, classify (spec gap / defect / flaky), and report in the fidelity report.

## 8. Execution Checklist

- [ ] F-1: add the real-library JWT test (TC-252-3a) to both agents; it must fail on a deliberately broken signing call before it is trusted
- [ ] F-2: extend `seedArtifact` with `metadata` before writing SC-245-1 and SC-244-1
- [ ] F-3: confirm the threshold input (rendered rows) with `product-engineer` or record it in the PR
- [ ] Write the failing component tests (TC-245-*, TC-244-*) before implementing, per tasks 2.1–2.2 and 3.1–3.3
- [ ] RT-1…RT-3 run in the default `pnpm run test` with fixed seeds
- [ ] E2E SC-245-* and SC-244-* added; `pnpm run test:e2e` green locally against the Supabase stack
- [ ] SC-252-1N negative proof captured in the #252 PR body
- [ ] Manual: screen-reader announcement of the disclosure state (AC-245-2); a real `security-analyst` run watched to completion (AC-244-1)
- [ ] Post-merge: SC-252-6 / 6N plus EC-252-5 evidence recorded on #252
- [ ] Traceability matrix `Result` column filled during Audit Mode
