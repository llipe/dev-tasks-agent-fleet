# Fidelity Report — Batch rollup: CI audit gates (#252) and run-detail follow-ups (#245, #244)

## 1. Header / Verdict

- **Overall fidelity: High**
- **Highest drift impact present: Major** (one Major finding, R-01 — CT-3 is unmet by pre-existing code and masked by a permissive test assertion)
- **Scope:** issues #252 (PR #254), #245 (PR #255), #244 (PR #256) — 18 ACs, one integration branch `integration/run-detail-followups-and-audit` (HEAD `a1d50a5`, planner checkpoint on top of `b84fb0c`), diffed against `origin/main`.
- **Mode:** Audit (grey-box). **Non-blocking:** per the verifier contract, drift does not gate PR/issue completion and does not replace the `test`/`lint`/`format:check`/`typecheck`/`audit` gates.
- **AC coverage:** 18/18 observed. **Pass: 11. Pass with a pending operator/CI/E2E clause: 6. Drift: 1 (AC-252-3 / CT-3).** No AC failed outright.

## 2. Human-readable summary (what changed and why)

Two CI quality gates were red and three run-detail papercuts were open. This batch fixes all five, in order.

- **#252 — the two red "audit" gates are now green.** The Python agents pinned the JWT library (`PyJWT`) up to a version with no known security advisories, and the panel's dependency overrides were raised so the known high-severity advisories in image/transitive packages (`sharp`, `source-map-js`, `fast-uri`) no longer trip the gate. Locally the panel audit now passes and reports only the two remaining lower-severity `next` advisories, which are deliberately left for the separate Next.js 16 upgrade. The agents' security scans pass. A real round-trip test was added so the JWT upgrade can't silently change how the agents sign in to GitHub.
- **#245 — a long findings table no longer hides the log.** A large security report used to push the log panel off the bottom of the screen. The findings table is now inside a collapsible "disclosure": a one-line summary is always visible, the table scrolls inside its own capped area, and the log section can no longer be squeezed to nothing. Small reports (10 rows or fewer) still open automatically.
- **#244 — a finished run now updates itself.** When a live run finishes, the page refreshes its summary (status, outcome, finish time, links, findings) once, automatically, without a manual reload — and only when the run genuinely ends, never when a session expires or the connection merely hiccups.

**The one thing to flag (R-01, Major but non-blocking):** a security-negative test for #252 (what happens with a *bad* GitHub App key) does not actually prove the intended behavior. The code signs the key *outside* its error-handling block, so a malformed key raises a raw library error rather than the agent's own classified "credential error", and the test was written loosely enough to accept any error — so it passes either way. The JWT upgrade itself is sound; this is a pre-existing error-classification gap the batch surfaced but did not close.

## 3. Per-AC result table

See `workstream/traceability-matrix-issue-252-245-244.md` (v2.0) for the full table with positive/negative test-case IDs and detailed observed evidence. Summary:

| AC-ID | Issue | Result | Note |
| --- | --- | --- | --- |
| AC-252-1 | #252 | Pass | panel `audit` exits 0 (Node 22); only the 2 moderate `next` advisories remain; `sharp@0.35.5` in lockfile |
| AC-252-2 | #252 | Pass (pending op) | `pip-audit . --strict` exits 0 both agents on 3.13; 3.14 matrix is CI-only |
| AC-252-3 | #252 | **Drift (CT-3)** | RS256 signing on 2.15.1 verified (TC-252-3a, 2 passed each); malformed-PEM classification unmet — R-01 |
| AC-252-4 | #252 | Pass (pending op) | local gates green; CI jobs run only on the consolidated PR to `main` (D-13) |
| AC-252-5 | #252 | Pass (pending op) | no `sharp` downgrade (EC-252-3); `next build`/Docker/E2E not run locally |
| AC-252-6 | #252 | Pending op | post-merge, approval-gated `infra-engineer` redeploy + live invocation (D-10) — not run |
| AC-245-1 | #245 | Pass (pending op) | 40vh body cap + 240px floor + `overflow-wrap` in CSS; viewport geometry is E2E |
| AC-245-2 | #245 | Pass (minor drift) | toggle/semantics/focus-ring/escaping verified; native marker suppressed — R-02 |
| AC-245-3 | #245 | Pass | rendered-row threshold (D-12); EC-245-1/2, RT-1, CT-9 covered |
| AC-245-4 | #245 | Pass | empty/fallback/truncation render with no `<details>`; CT-7/CT-8 covered |
| AC-245-5 | #245 | Pass | 50-row test green; 69 component tests pass |
| AC-245-6 | #245 | Pass | DESIGN.md §5.3 + changelog row 1.11; no new token/variant |
| AC-244-1 | #244 | Pass (pending op) | refresh wiring + EC-245-7 + CT-6 pinned; E2E + manual real-run pending |
| AC-244-2 | #244 | Pass | already-terminal run mounts no refresh effect |
| AC-244-3 | #244 | Pass | ≤1 refresh; errors/reconnects/`authStopped` never trigger; RT-3 (seed 244001) |
| AC-244-4 | #244 | Pass | once at ≥500ms, not at 499ms; unmount-before-debounce clears the timer |
| AC-244-5 | #244 | Pass | step/level filter persists across the viewer swap (D-03) |
| AC-244-6 | #244 | Pass | 4 changed suites green; stream route + `closed`-frame contract untouched by the diff |

**Evidence environment:** Python 3.13.0 local; Node 22.23.2 via nvm (the repo pins `engines: >=22 <25`, and the local default Node 26 is correctly refused by pnpm — itself confirmation of the AC-252-1 "run under Node 22" clause). Local Supabase/Docker not available → all Playwright E2E and the Docker image build are **pending**, consistent with the task list's own "E2E NOT RUN" notes (tasks 2.15, 3.12).

## 4. Drift catalog

Every item below is **non-blocking** to PR/issue completion.

### R-01 — CT-3: malformed PEM is not classified as `CredentialError` (and the test does not require it)

- **AC / contract:** AC-252-3, contract CT-3 ("a malformed PEM raises, and the agent classifies it as `CredentialError`, not an unhandled error"), and the test plan's mandatory security-negative set.
- **Evidence (codebase):** in both agents' `credentials.py`, `mint_installation_token()` calls `jwt.encode(..., pem, algorithm="RS256")` **before** and **outside** the `try/except requests.RequestException` block. A malformed PEM therefore raises a raw `cryptography`/PyJWT exception that is never mapped to `CredentialError`. (The `CredentialError` wrapping in this module covers Secrets Manager and transport failures, not the signing call.)
- **Evidence (test):** `tests/unit/test_credentials_real_jwt.py::test_malformed_pem_is_classified_or_raises` asserts `pytest.raises((CredentialError, Exception))` — i.e. it accepts *any* exception, so it passes whether or not classification happens. The docstring says "classified CredentialError **or** the library error", so the test as written does not bite on the CT-3 intent.
- **Impact: Major.** CT-3 is a declared security-negative contract; it is currently vacuously satisfied, mirroring the exact F-1 failure mode (a security-relevant assertion that cannot fail). Note the *runtime* blast radius is limited: a malformed PEM still fails the run (it raises), and upstream entrypoints classify broadly — but the specific "classified, not leaked/unhandled" contract is unproven, and PySEC-era advisories around key handling are exactly where you want this pinned.
- **Intent: Unintended.** Pre-existing code structure (not introduced by this batch); the batch added the test that was *supposed* to pin it but wrote the assertion too loosely.
- **Route:** `developer` — either (a) wrap the `jwt.encode` call in `mint_installation_token` so a bad key becomes a classified `CredentialError`, then tighten the test to `pytest.raises(CredentialError)`; or (b) if "raise raw, classify upstream" is the accepted design, change CT-3's wording and the test to assert the actual upstream classification path. `product-engineer` to confirm which is the intended contract (spec-level ambiguity) via `activity-drift-reconciliation`.

### R-02 — `<summary>` `display:flex` suppresses the native disclosure triangle

- **AC / contract:** AC-245-2 (mouse/keyboard toggle, visible affordance).
- **Evidence (codebase):** `AuditReportPanel.module.css` `.summary { display: flex; ... }`. Setting a `<summary>` to `display:flex` removes the UA-rendered `::marker`/disclosure triangle in Chromium/WebKit, so there is no built-in open/closed caret. No custom marker (e.g. a rotated chevron via `.summary::before` or `list-style`/`::-webkit-details-marker`) is added back.
- **Impact: Minor.** Toggle still works by click and by keyboard (Enter/Space on the focused `<summary>`), the `:focus-visible` ring is present, and `details[open]` reflects state — so the control is operable and accessible. What's missing is the *visual* "this is expandable" affordance; a user may not realize the summary is clickable.
- **Intent: Unintended** (a common CSS side effect of `display:flex` on `<summary>`), explicitly flagged by the planner.
- **Route:** `developer` — re-introduce a visible marker without reverting the flex layout (e.g. a token-only `::before` chevron that rotates on `[open]`, or `.summary { list-style-position: inside }` kept with an explicit marker). `ux-engineer`/DESIGN §5.3 to confirm the chosen affordance. Low effort, polish-only.

### R-03 — semgrep 1.177.0 → 1.180.0 bump validated only by the (post-main) live invocation

- **AC / contract:** AC-252-2 (both agents' `pip-audit` green) and the implicit "the scanner still runs" expectation for `security-analyst`.
- **Evidence:** `security-analyst/pyproject.toml` bumps `semgrep` to `1.180.0` (forced: semgrep ≤1.178.0 pins `pyjwt~=2.13.0`, blocking the 2.15.1 security pin; 1.179.0+ relaxes to `>=2.15.0,<3`). The pin resolves cleanly (`pip-audit` green locally) and does not fail import/metadata resolution. **But** semgrep is a *scan binary*: whether 1.180.0 still produces the finding shape the agent's parser expects is only exercised by a real `audit_only`/`fix` invocation — which is the post-merge, operator-run step (D-10, AC-252-6), not run here. The repo's own standing lesson (`security-analyst/README.md`) is precisely that "mocked-subprocess tests cannot see real binary output shapes".
- **Impact: Minor.** The dependency-resolution and security objective of the bump is met and verified; the behavioral risk is bounded to the semgrep output contract, and the post-main live invocation (AC-252-6) is the designed gate for exactly that.
- **Intent: Intended** (a necessary transitive consequence of the PyJWT security pin, documented in `pyproject.toml` and D-06).
- **Route:** No code action. `infra-engineer`/operator — the post-merge `security-analyst` live invocation (AC-252-6, task 1.17) **must** be a semgrep-exercising run (an `audit_only` run that produces semgrep findings), and the deployed-state hash + run id recorded on #252, before #252 closes.

### Cross-story interaction checks (requested item 3)

- **EC-245-7 — #245 disclosure under #244 refresh:** **No drift.** Pinned by `AuditReportPanel.test.tsx` ("preserves a user-opened >10-row disclosure across a server-tree reconcile", passes). `router.refresh()` reconciles the server output into the existing client tree; because `open={rows.length<=10}` is unchanged across the refresh, React does not re-write the native `open` attribute, so a user's manual expand survives. The #244 E2E (`live-tail.spec.ts`) deliberately asserts the findings **summary line** ("3 findings"), not table rows, so it is agnostic to disclosure state — the correct choice. Documented in `docs/technical-guidelines.md` changelog 1.47.
- **seed.ts changes from both stories coexisting:** **No drift.** `tests/e2e/fixtures/seed.ts` carries both additions cleanly: `setRunTerminal()` (#244 — drives a live run terminal in place) and `seedArtifact()`'s optional `metadata` param (#245, verifier F-2, default `null`, `coalesce($5::jsonb,'{}'::jsonb)` so existing callers are unchanged). They are independent functions with no shared mutable state; both are used together by SC-244-1 (seed artifact, then set terminal). Backward compatibility of `seedArtifact` is preserved by the default argument.

## 5. Edge-case and randomized test outcomes

The Design-Mode plan's randomized tactics ran green locally (Node 22) with their fixed default seeds:

- **RT-1** (`AuditReportPanel` default-open/row-count property, seed **245001**) — passed over n ∈ [0,600].
- **RT-2** (hostile-markup fuzz, seed **245002**) — passed; renders as text, one `details`/`summary` per report (part of the 33-test AuditReportPanel run).
- **RT-3** (refresh-effect stateful random walk, seed **244001**) — passed; `refresh ≤ 1 per mount`, `= 1` iff a non-auth `closed` + ≥500ms before unmount.

Replay: `TEST_SEED=<n> pnpm --filter panel exec vitest run <file> -t "<tactic>"` (run under Node 22). No randomized failure occurred, so the failure-triage/retry-budget workflow was not exercised.

**Not run locally (marked pending, not passed), per requested item 6:**

- All Playwright E2E — `run-detail-layout.spec.ts` (SC-245-1/1b/2/3/3N) and `live-tail.spec.ts` SC-244-1/1b/2/3/4 — Docker/local Supabase unavailable.
- `Dockerfile.panel` image build and `next build` (AC-252-5).
- `pip-audit` on the **Python 3.14** matrix cells (AC-252-2) — CI-only.
- The agent **redeploy + live invocation** (AC-252-6, tasks 1.16/1.17) and the semgrep-exercising live run (R-03) — post-merge, approval-gated `infra-engineer` steps.
- The screen-reader announcement of the disclosure state (AC-245-2 manual clause).

## 6. Roadmap-mismatch check (requested item 5)

**Confirmed — the planner's choice of `In progress` (not `Done`) is correct, and the current roadmap row is stale.**

- `docs/roadmap.md` "Issue batches (no PRD)" row **"CI audit gates + run-detail follow-ups"** currently reads **Status: `Not started`** with "What's missing: Entire scope". That is now stale: all three stories are merged into the integration branch (PRs #254/#255/#256) with their quality work complete.
- It should **not** be set to `Done` while **AC-252-6 (task 1.17, redeploy + live invocation) is unmet** — that step is post-merge and gates #252's closure (D-10). So `In progress` is the accurate status.
- **Advisory to `product-engineer` (roadmap write-back, planner owns the consolidated-PR update):** set the row to **`In progress`**; Issues/PRs = `#252/PR #254, #245/PR #255, #244/PR #256`; **What's missing** = "Post-merge, approval-gated redeploy of both agents with PyJWT 2.15.1 + a live invocation of each (semgrep-exercising for `security-analyst`), per #252 tasks 1.16/1.17 (D-10); then close #252." The `#217` row remains `Not started`. (verifier reports only; it does not edit the roadmap.)

## 7. Recommendations (next step per item)

| Finding | Impact | Route | Suggested action |
| --- | --- | --- | --- |
| R-01 (CT-3 unmet + loose test) | Major | `developer` + `product-engineer` | Decide the intended contract (wrap-and-classify vs raise-and-classify-upstream); then make the code and test agree so the security-negative actually bites. Non-blocking to this batch. |
| R-02 (missing disclosure marker) | Minor | `developer` + `ux-engineer` | Re-add a token-only visible open/closed affordance to `.summary` without reverting the flex layout; confirm against DESIGN §5.3. |
| R-03 (semgrep bump behavioral validation) | Minor | `infra-engineer`/operator | Make the post-merge AC-252-6 `security-analyst` live run a semgrep-finding-producing `audit_only` run; record hash + run id on #252. No code change. |
| Roadmap row stale | Minor | `product-engineer`/planner | Set the batch row to `In progress` with PRs filled and the redeploy as what's missing (per §6). |

No action needed for the cross-story interactions (EC-245-7, seed.ts coexistence) — both verified clean.

## 8. Output contract

- **Mode / phase:** Audit Mode, Phase 4 (reporting & publication) complete.
- **Source artifacts used:** the three refinements, `decisions-run-detail-followups-and-audit.md` (D-01..D-13), `tasks-issue-252-245-244-audit-gates-and-run-detail.md`, `test-plan-issue-252-245-244.md`, `traceability-matrix-issue-252-245-244.md`, `docs/roadmap.md`, and the integration-branch diff vs `origin/main` (codebase, tests, DESIGN.md, docs/technical-guidelines.md).
- **Output files:** `workstream/fidelity-report-issue-252-245-244-rollup.md` (this file); `workstream/traceability-matrix-issue-252-245-244.md` (Result column filled, changelog → v2.0).
- **AC coverage:** 18/18 covered; 11 Pass, 6 Pass-with-pending-op clause, 1 Drift (AC-252-3/CT-3). None uncovered.
- **Overall fidelity verdict:** High. **Highest drift impact:** Major (R-01).
- **GitHub issue publication:** this report is committed to the integration branch under `workstream/` and should be linked from issues #252/#245/#244 (and the consolidated PR) by `github-ops`/planner, with R-01 called out on #252. (verifier does not open/merge PRs or push to `main`.)
- **Blocking gaps:** none to completion (audit is additive/non-blocking). Pending operator/CI/E2E items are enumerated in §5 and tracked on #252 for AC-252-6.
