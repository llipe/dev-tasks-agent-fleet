# Fidelity Report — Issue #78 (Compliance Test Plan Reconciliation)

## 1. Header / Verdict

- **Overall fidelity: HIGH**
- **Highest drift impact present: Minor**
- **Scope:** issue #78 (documentation / governance) · branch `issue/78-compliance-test-plan-reconciliation` · PR #179 · repo `llipe/dev-tasks-agent-fleet`
- **Mode:** Audit (grey-box) · **Gate:** additive, non-blocking

The delivered documentation accurately describes the shipped test suite. All five audited
ground-truth claims hold. Two Minor drift items were found — one factual (a module count off by
one) and one presentational (asymmetric "live half" accounting) — neither of which produces a false
coverage claim. Nothing blocks completion.

## 2. Human-Readable Summary (what changed and why)

Issue #78 asked a governance question: *does the dependency-update agent's compliance test plan
honestly describe the tests that actually exist?* The original v1.0 plan was written in design mode
and advertised "82 cases / 100% coverage" across four layers (end-to-end, contract, edge-case, and
randomized/fuzz). In reality the agent ships only two runnable test layers — unit and component —
and the "end-to-end" and "randomized" layers were never built as runnable tests.

This change is documentation-only (five Markdown files). It rewrites the two compliance documents so
they state the measured truth: the agent has a large, green automated suite (460 tests) that
genuinely covers 30 of the 36 acceptance criteria; the remaining 6 criteria need real cloud
infrastructure (a real deployment, a real pull request, a real GitHub token exchange, the reaper
timing) and are handled by written operator procedures rather than automated tests — a deliberate,
documented decision made with the user, not a hidden gap. The old aspirational "100%" figures are
kept only in clearly-labelled "superseded" sections for history, and every corrected document now
points at the same authoritative per-criterion table.

The audit confirms the rewrite is truthful: the tests it cites really exist, the runbooks it
references really exist, the suite really is green at the stated count, and no misleading
"everything is automated" claim survives without a caveat. The one substantive nit is that the docs
repeatedly say "17 unit modules" when there are actually 18 — an undercount that slightly
*understates* the real coverage, so it errs on the conservative side.

## 3. Per-AC / Per-Claim Result Table

The "acceptance criteria" for this documentation issue are the five fidelity claims stated in the
audit request. Each is checked against ground truth read directly from the repository.

| Claim | Description | Codebase evidence | Test/Doc evidence | Result |
|-------|-------------|-------------------|-------------------|--------|
| C1 | Suite has only `unit`+`component` markers, no `e2e`/`fuzz`, `hypothesis` not a dep — so the 36 E2E + 6 randomized cases are genuinely not runnable pytest layers | `pyproject.toml` `[tool.pytest.ini_options] markers` = `unit`, `component` only; `dependencies`/`dev` extras contain no `hypothesis`; `grep hypothesis tests/ *.toml` → none; no `tests/fuzz/` dir | Docs §0/§7/§8 state exactly this with the `-m e2e`/`-m fuzz` "do not exist" caveat | **Pass** |
| C2 | New "AC → Real Test Mapping" rows cite tests that actually exist (spot-check AC-9, AC-23, AC-30, AC-31, AC-33 + AC-3, AC-28, AC-32) | All cited `test_*` functions found verbatim: eligibility rows 1–4, mandate `test_caret_major_bump`/`test_new_dep_added`/`test_dep_removed`, scrubber (13), payload-contract 5 fns, AC-33 step-closure 2 fns, AC-3, AC-28 (4 fns), AC-32 (4 fns) | Matrix "AC → Real Test Mapping"; counts corroborated: eligibility 34 (`4 rows +30`), classifier 27, scrubber 13 | **Pass** |
| C3 | Measured summary "30 automated / 6 deferred (AC-1,2,12-live,28-live,33-seq,36) / 0 unaccounted" is internally consistent and matches the per-AC table | 36 rows partition cleanly into 30 automated + 6 carrying a deferred component; arithmetic sound, every AC appears once | Matrix "Measured totals" + Coverage Summary + TESTING.md note all agree on 30/6/0 | **Pass** (see D2) |
| C4 | AC-36 claimed already-verified in `docs/runbooks/issue-94-reaper-verification.md` — reference is real | File exists (42 KB); contains `maxLifetime`/`3600`/`reaped_by`/synthetic-interlock §4 content | Matrix AC-36 row + §0 cite it; `issue-77-deployment-e2e.md` also exists (14 KB) | **Pass** |
| C5 | No false claim remains — "82/82", "100%", phantom runnable `-m e2e`/`-m fuzz` — without the reality caveat | Only `100%` hits are in the changelog (correcting) + "v1.0 … superseded by v1.1 above" sections; only `-m e2e`/`-m fuzz` hit is the §8 "do not exist" caveat; RT-* replay cmds live under the "Design catalog preserved verbatim / not implemented" banner | Docs §0, §7, §8, matrix v1.1 tables | **Pass** |

Supporting fact: **`make`/pytest run → 460 passed** (12.1 s), exactly matching the documented
collected count; suite is green.

## 4. Drift Catalog

> All drift below is **non-blocking** to PR/issue completion.

### D1 — Unit-module count stated as 17, actual is 18 (Minor / Unintended)

- **Description:** The reconciliation repeatedly describes the suite as "**17** unit + 3 component
  modules" (test-plan §0 table intro and changelog v1.1; matrix Coverage Summary "17 unit + 3
  component"; echoed context in TESTING.md). The repository actually contains **18** unit test
  modules under `tests/unit/test_*.py` (`test_agent_reporter_start, test_audit, test_classifier,
  test_clock_invariant, test_credentials, test_eligibility, test_fix_tools, test_heartbeat,
  test_mandate_check, test_outcome_mapping, test_payload_contract_fixture, test_pr_body,
  test_safe_path, test_scrubber, test_signal_backstop, test_toolchain, test_updater, test_validator`).
- **Impact class: Minor.** The `460 tests / 450 test functions / 3 component modules` figures are all
  correct; only the unit-module tally is off by one, and it *understates* rather than overstates
  coverage. No per-AC mapping row is affected.
- **Intent class: Unintended.** Nothing in the scope decisions calls for a 17 count; it reads as a
  transcription slip.
- **Evidence source(s):** `agents/dependency-update/app/dependencyUpdate/tests/unit/` (18 files) vs.
  the "17 unit" phrasing in the two workstream docs and TESTING.md.
- **Recommendation:** `developer` — one-word correction ("17" → "18") in the three occurrences.

### D2 — "Live half" accounting is asymmetric between hybrid ACs (Minor / Intended)

- **Description:** Four ACs carry an "(a) … / (c) live half" class tag in the measured mapping:
  **AC-12, AC-13, AC-28, AC-34**. The measured-totals sentence enumerates the 6 deferred items as
  "AC-1, AC-2, **AC-12 live, AC-28 live**, AC-33 sequencing, AC-36" — surfacing the live halves of
  AC-12 and AC-28 as distinct deferred entries, but not the equally-live-half AC-13 and AC-34, which
  are counted purely in the "30 automated" bucket.
- **Impact class: Minor.** The headline arithmetic is sound and honest: counting is done at
  AC granularity, each AC's automatable logic *is* genuinely tested (`test_pr_opened_with_major` for
  AC-13; transport-failure classification + `*_never_raises*` for AC-34), and the 30 + 6 = 36 / 0
  unaccounted partition holds with every AC in exactly one bucket. The "6 deferred" set is the set of
  ACs whose *headline behavior* is real-infra; AC-13/AC-34 have automated headline coverage plus a
  live confirmation step. The asymmetry is a presentational precision issue, not a miscount.
- **Intent class: Intended.** This is a defensible bucketing choice (AC-level, not half-level), and
  the per-row `(c) live half` tags are individually accurate — a reader inspecting the table sees the
  live halves of all four ACs. Only the one-line summary compresses it asymmetrically.
- **Evidence source(s):** matrix rows AC-12/AC-13/AC-28/AC-34 vs. the "Measured totals" line and the
  Coverage Summary "deferred-to-runbook" cell.
- **Recommendation:** `product-engineer` (optional) — a half-sentence clarifying that AC-13/AC-34
  also have runbook-confirmed live halves but are counted automated because their headline logic is
  tested, would remove the only remaining ambiguity. No action strictly required.

## 5. Edge-Case & Randomized Test Outcomes

Not applicable to this delivery in the runnable sense — and that is precisely the point the
reconciliation makes. The randomized/fuzz tactics (RT-1–RT-6) are **not implemented** (`hypothesis`
absent, no `-m fuzz` marker), which the documents now state plainly. The audit confirms no fuzz/E2E
layer is presented as runnable. Property-style tests that *do* exist without `hypothesis`
(`test_heartbeat.py` random-duration / random-arrangement cases) are correctly cited as the
substitute rationale.

## 6. Recommendations

| Item | Recommended next step | Owner |
|------|-----------------------|-------|
| D1 (17→18 module count) | Correct the three occurrences; trivial, improves the exact metric this doc exists to state | `developer` |
| D2 (live-half asymmetry) | Optional one-line clarification in the summary; per-row tags already accurate | `product-engineer` |
| Overall | Merge is not gated by this audit; both items are cosmetic. `coverage_gate` was legitimately `SKIPPED(documentation-only)` — consistent with a docs-only PR with an unchanged, green suite | — |

**Verdict restated: HIGH fidelity, highest drift Minor, non-blocking.** The reconciled documents are
an accurate, well-caveated description of the shipped suite; the scope decisions (skip fuzz, keep
E2E in the runbook, no backfill) are recorded and honored; the suite is green at the stated 460.
