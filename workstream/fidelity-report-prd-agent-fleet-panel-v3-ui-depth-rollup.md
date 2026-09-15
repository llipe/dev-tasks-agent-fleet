# Verifier Audit (Audit Mode) — PRD-Level Rollup

## Agent Fleet Control Panel v3: UI Depth (S-142–S-148, FR1–FR18)

**Fidelity: High**
**Highest drift impact present: Minor**
**Scope:** All 7 merged stories (S-142–S-148, issues #202–#208) on
`integration/panel-v3-ui-depth`, audited against the PRD/spec/story trio at
branch tip `8bc29f4` (the commit that also carries the just-completed
`qa-engineer` coverage rollup). This is a **PRD-level** audit — every FR is
traced end-to-end against the shipped code, not re-derived story-by-story —
plus a targeted backfill of the two missing per-story fidelity reports the
coverage rollup flagged.

---

## Human-readable summary (what changed and why)

This PRD made two existing screens more usable at real run volume and
brought two long-parked destinations to life. On the per-agent run history
screen, an operator can now filter by status, repository, and free text, page
through results instead of loading everything at once, and see branch/PR
links without opening each run. On the run-detail screen, a new steps panel
lets an operator click straight to a failing step's log lines and narrow by
log level. A brand-new "All runs" screen shows every agent's activity in one
feed, and a brand-new "Repositories" screen lets an operator register and
retire (archive, not delete) repositories for agent use without touching the
database directly. A small, pre-existing visual bug (queued and running runs
looked identical) was also fixed.

All of this shipped. Every one of the PRD's 18 functional requirements is
present in the delivered code, not just claimed in a story file — I traced
each one to the actual source line, not just to a passing test. The
delivered behavior differs from the literal PRD/story wording in a small
number of places (a free-text search that can't substring-match a raw run
id; a log-level filter that's a threshold rather than an exact match; a
connection indicator that's always "Connected" because there's no reachable
"disconnected" state in the resolved design). Every one of these differences
was found, verified against the real platform constraint that caused it, and
disclosed in-code and in the relevant PR — none of them were silently
introduced. Two of the seven stories (the two largest, most-depended-upon
ones) had never had their own individual audit report written down, even
though they had been informally audited via a PR comment at merge time —
that gap is fixed by this rollup (see below). And the batch as a whole never
delivered any of the browser-level (Playwright) tests that the
pre-implementation test plan called for, even though every layer below that
(unit, component, and live-database integration tests) is unusually
thorough — that is a real, named gap, judged below.

---

## FR1–FR18 traceability (PRD-level, traced against shipped code)

| FR | Requirement | Story | Shipped? | Codebase evidence |
|---|---|---|---|---|
| FR1 | Status segmented control, colored dot + live count, `effective_status`-derived | S-143 | **Yes** | `panel/components/runs/RunFilterBar.tsx`; `panel/lib/supabase/queries.ts::getRunStatusCounts` |
| FR2 | Repository filter chips (repos appearing in agent's runs) | S-143 | **Yes** | `RunFilterBar.tsx` chips + reused `getEnabledRepositories` |
| FR3 | Free-text search (repo/branch/run id) | S-143 | **Yes, narrowed** | `queries.ts::applyRunFilterClauses` — repo-name substring + exact-UUID run-id match only; see Drift #1 |
| FR4 | URL-encoded, server-paginated queries | S-143 | **Yes** | `lib/domain/run-filter.ts` (`parseRunFilter`/`serializeRunFilter`), `getFilteredRuns` |
| FR5 | "X of Y" + "Load more" pagination | S-143 | **Yes** | `app/(panel)/agents/[slug]/page.tsx` lines ~195–223 |
| FR6 | Empty state + CTA | S-143 | **Yes** | `components/runs/RunHistoryTable.tsx` `hasActiveFilter` branch |
| FR7 | Inline branch/PR links | S-144 | **Yes** | `queries.ts::getPullRequestArtifactsForRuns`, `components/runs/RunHistoryRow.tsx`, reuses `isSafeArtifactUrl` |
| FR8 | Connection-state indicator | S-143 | **Yes, narrowed** | `RunFilterBar.tsx` — static "Connected" only, per spec v1.1's resolved design (no reachable disconnected state); documented, not a gap |
| FR9 | Steps panel (dot/name/duration/count) | S-145 | **Yes** | `components/run-detail/StepsPanel.tsx`, `lib/domain/run-detail.ts::buildStepsPanel` |
| FR10 | Click-step filters log; "All steps" clears | S-145 | **Yes** | `lib/domain/log-filter.ts::applyLogFilter`, `components/run-detail/RunDetailLogSection.tsx` |
| FR11 | Log-level coloring/filter, composes with step filter | S-145 | **Yes, implementation-shape decision** | `log-filter.ts` — severity threshold, not exact match; see S-145 fidelity report Drift #1 |
| FR12 | `queued` spin vs. `running` pulse | S-142 | **Yes** | `components/status-meta.ts`, `StatusDot.tsx`/`.module.css` |
| FR13 | All-runs cross-agent feed | S-146 | **Yes** | `app/(panel)/runs/page.tsx` — reuses `getFilteredRuns`/`RunFilterBar`/`RunHistoryTable` verbatim, `agentSlug: null` |
| FR14 | Sidebar "All runs" enabled | S-146 | **Yes** | `components/shell/Sidebar.tsx` — `NavItem href="/runs"` |
| FR15 | Repositories list (excl. archived) | S-147 | **Yes** | `queries.ts::getRepositories`, `app/(panel)/repositories/page.tsx` |
| FR16 | Add repository (manual reference, no GitHub call) | S-147 | **Yes** | `queries.ts::insertRepository`/`REPOSITORY_ALREADY_EXISTS`; `app/(panel)/repositories/actions.ts` |
| FR17 | Archive repository (soft delete) | S-148 | **Yes** | `queries.ts::archiveRepository` — `UPDATE ... SET archived_at`, never `DELETE` |
| FR18 | Sidebar "Repositories" enabled | S-147 | **Yes** | `Sidebar.tsx` — `NavItem href="/repositories"` |

**18 of 18 FRs traced directly to shipped source, not merely to a passing
test file or a story checklist.** Every non-goal in PRD §10 (Settings, System
health, command palette, GitHub App sync, repository edit/rename, restore
UI, responsive <1024px) was checked directly in the codebase and confirmed
absent — `Sidebar.tsx` still renders `DisabledNavItem` for Settings/System
health, `insertRepository` makes no `fetch` to `github.com`, and
`RepositoryTable.tsx` has no restore action.

---

## Integration seams (checked directly, not assumed from the story text)

### 1. S-146 reusing S-143's `RunFilterBar` / `getFilteredRuns`

Read `panel/app/(panel)/runs/page.tsx` directly (not just the story's
Technical Notes). Confirmed it imports and calls the exact same
`getFilteredRuns`/`getRunStatusCounts`/`getPullRequestArtifactsForRuns`/
`getStepProgressForRuns` helpers S-143/S-144 introduced, with
`agentSlug: null`, and introduces no parallel filtering logic.
`app/(panel)/agents/[slug]/page.tsx` still calls both `getAllRunsByAgentSlug`
(agent-header lifetime stats, deliberately unfiltered) and `getFilteredRuns`
(the table) — the documented two-reads shape, not an accidental leftover.
**No seam gap found.**

### 2. S-148 extending S-147's `RepositoryTable`

Read `panel/components/repositories/RepositoryTable.tsx` directly. The
component's list-filtering responsibility stays with `page.tsx`'s
`getRepositories(client)` call (S-147); S-148 only adds the Archive action +
confirm dialog. `tests/integration/repository-mutations.test.ts` is a single
shared file exercising both stories' behavior (insert/duplicate-rejection
from S-147, archive/idempotency/FK-preservation from S-148), confirmed by
direct read of the file — not two parallel, potentially-diverging test
files. **No seam gap found.**

### 3. S-145's step/level filter composing with S-110's live-tail behavior (checked opportunistically)

Confirmed `tests/component/live-log-viewer.test.tsx` has a dedicated
`describe("LiveLogViewer — step/level filter composition with live tail
(Story S-145, AC4)")` block (verified present at line 316), and confirmed in
source that `lib/hooks/useRunStream.ts` carries `step_id` onto
live-appended lines so the filter composes with the SSE tail without
breaking S-110's autoscroll. **No seam gap found.**

### 4. Sidebar — three stories touching one file (S-146, S-147, and the pre-existing Settings/System-health disabled state)

Read `components/shell/Sidebar.tsx` directly: "All runs" and "Repositories"
are both live `NavItem`s; Settings and System health remain
`DisabledNavItem`s. `tests/component/Sidebar.test.tsx` explicitly asserts
both the two newly-enabled links and the continued-disabled state of the two
still-parked destinations in one file. **No seam gap found** — this is the
kind of cross-story regression a single-story audit could plausibly miss,
and it is covered.

---

## Backfilled per-story fidelity reports (this rollup's own remediation)

The coverage rollup flagged that S-143 and S-145 — the two largest (`L`),
highest-priority, most structurally load-bearing stories in the batch — had
no `workstream/fidelity-report-S-*.md` file, despite both having been
informally audited via a PR comment at merge time. I re-audited both against
the delivered code directly (not by transcribing the PR comments, though
they were used as a starting hypothesis) and have written:

- **`workstream/fidelity-report-S-143.md`** — **Fidelity: High**, highest
  drift impact **Minor** (2 items: the FR3 search-scope narrowing, and the
  addition of `getRunStatusCounts` beyond the story's own Technical Notes;
  both root-caused to a real, independently-verified platform constraint or
  an AC-entailed necessity, neither Unintended).
- **`workstream/fidelity-report-S-145.md`** — **Fidelity: High**, highest
  drift impact **Minor** (3 items: the severity-threshold level-filter
  semantics, two files added beyond the story's file list, and a test-path
  convention deviation; all Intended, all disclosed).

Both backfilled reports independently re-verify their AC tables against
source (line-level citations, not test-file citations alone) and against a
live `pnpm --filter panel run validate` run performed in this session (see
below) — they are not a rubber-stamp of the PR comments.

---

## Ground-truth test run (executed live in this audit session)

Ran on `integration/panel-v3-ui-depth` @ `8bc29f4`, Node 22.23.2 (matching CI,
selected explicitly — the ambient shell Node is v26.7.0, which hard-fails
`pnpm install --frozen-lockfile` under `panel/package.json`'s
`"engines": {"node": ">=22 <25"}`), pnpm 10.11.0, local Supabase stack
already running (`supabase status` confirmed `db`/`auth`/`rest`/`kong`/
`realtime`/`storage` healthy):

```
SUPABASE_URL=http://127.0.0.1:54321
SUPABASE_SERVICE_ROLE_KEY=<from `supabase status -o env`>
REQUIRE_LOCAL_DB=1
pnpm --filter panel run validate
```

Result (exit code 0):

```
lint:         PASS
format:check: PASS
typecheck:    PASS
test:         100 test files passed, 1 skipped (101); 1205 tests passed, 4 skipped (1209)
audit:        PASS (no advisories >= high)
```

Every `tests/integration/*.test.ts` file printed
`[integration] local Supabase Postgres reachable` and ran for real — this
includes `tests/integration/filtered-runs.test.ts` (14 tests, S-143/S-144/
S-146) and `tests/integration/repository-mutations.test.ts` (15 tests,
S-147/S-148), both confirmed genuinely executed against live Postgres, not
vacuously skipped. The 4 skipped tests are the pre-existing, unrelated
`RUN_BUNDLE_SECRET_TEST=1`-gated suite. This matches the `qa-engineer`
coverage rollup's own ground-truth run and independently reproduces it.

---

## Drift catalog (PRD-level aggregation)

| # | Item | Impact | Intent | Source |
|---|---|---|---|---|
| 1 | FR3 free-text search narrower than literal PRD/story wording (no partial run-id substring match, no `branch` match) | Minor | Intended | S-143, root-caused to a real PostgREST/Postgres constraint, independently verified |
| 2 | `getRunStatusCounts` added beyond S-143's own Technical Notes | Minor | Intended | S-143, AC1-entailed necessity |
| 3 | FR8 connection indicator is a static "Connected" only (no reachable "disconnected" state) | Minor | Intended | S-143, spec v1.1 resolved this explicitly — the honest ceiling of the presentational design, not a shortfall |
| 4 | FR11 log-level filter implemented as a severity threshold, not exact match | Minor | Intended | S-145, a defensible resolution of a genuinely ambiguous story spec |
| 5 | Two files (`RunDetailLogSection.tsx`, `useRunStream.ts` change) added beyond S-145's file list | Minor | Intended | S-145, AC4-entailed necessity |
| 6 | Test file paths deviate from story-suggested colocated paths to the codebase's actual `tests/unit`/`tests/component` convention | Minor | Intended | S-144 precedent, S-145 |
| 7 | Additive Layer-1 unit tests beyond S-146's stated "none new" scope | Minor | Intended | S-146 (per its own fidelity report) |
| 8 | ESLint SD2-exemption scope widened to cover `app/**/actions.ts` | Minor | Intended | S-147 (per its own fidelity report) |
| 9 | **0 of 11 planned E2E scenarios delivered against the pre-implementation test plan** | **Major (PRD-level aggregate); Minor per individual story** | **Intended, but flagged for follow-up — see explicit judgment below** | All 7 stories, `workstream/test-plan-prd-agent-fleet-panel-v3-ui-depth.md` §3 |

No Critical drift found anywhere in the batch. No Unintended drift found —
every item traces to a verified platform constraint, an AC-entailed
necessity, or a disclosed, defensible implementation-shape decision.

**All drift items are non-blocking to the consolidated PR handoff to `main`,
per standing policy.** They are reported here for `product-engineer`'s
`activity-drift-reconciliation` flow, not applied by `verifier`.

---

## Explicit judgment call: the 0/11 E2E finding

**My verdict: this is Intended drift at the per-story level, but it is a
genuine PRD-level gap that warrants a follow-up recommendation — I am not
treating it as merely "a reasonable, disclosed scope cut repeated 7 times"
and leaving it at that.**

Reasoning:

- Each individual story's own Testing Requirements section explicitly
  scoped Playwright E2E out (substituting Docker-gated Layer 2.5 integration
  tests as the "live behavior" evidence instead), and each story's own PR
  disclosed this honestly. Read in isolation, every single one of these
  seven decisions is defensible — I verified this directly by reading each
  story's Testing Requirements section, not just trusting the aggregate
  claim.
- However, the pre-implementation `workstream/test-plan-prd-agent-fleet-panel-v3-ui-depth.md`
  §3 is itself a `verifier` Design Mode artifact — a compliance test plan
  produced specifically to name the black-box, browser-level scenarios
  (E2E-1 through E2E-11) that would prove FR1–FR18 work end-to-end through
  a real browser, including two brand-new screens (`/runs`, `/repositories`)
  and the panel's first two user-triggered database writes. I confirmed
  directly that `panel/tests/e2e/` contains none of the four new spec files
  the test plan named (`run-history-filters.spec.ts`,
  `run-detail-steps.spec.ts`, `all-runs.spec.ts`, `repositories.spec.ts`)
  and none of the four scenario extensions to the existing specs.
- The reason this crosses from "acceptable per-story cut" to "worth a
  follow-up" is that **no single story's own scope-cut decision was made
  with visibility into the other six.** Each story looked at its own Testing
  Requirements line and made a locally-reasonable call; nobody ever looked
  at the test plan's E2E table as a whole and made an affirmative decision
  that the entire E2E layer was unnecessary for this PRD. That is
  structurally different from a deliberate, PRD-level "we are choosing not
  to build E2E for this scope" decision — it is seven independent local
  optima that happened to sum to zero, which is exactly the class of gap a
  PRD-level rollup exists to catch.
- Two of the seven stories are the panel's first two new screens since Run
  Detail, and the first two user-triggered database writes since Invoke
  (S-112). A missing-write-path or a broken navigation link on either new
  screen is exactly the class of defect a component/unit test suite is
  weakest at catching and a real browser click-through is strongest at
  catching — and the automated coverage, while unusually strong at every
  other layer, has never been exercised through an actual browser for either
  new screen.
- Layer 1/2/2.5 coverage is genuinely strong (1205 passing tests, live
  Postgres-gated integration tests, no vacuous skips) — this is **not** a
  correctness blocker, and I am not recommending it block anything.

**Recommendation:** a small, targeted follow-up story (not a re-opening of
S-142–S-148) to add the highest-value subset of the originally-planned E2E
scenarios — at minimum E2E-9/E2E-10 (the `/repositories` add/duplicate/
malformed/archive round-trip, since it is the first new write-path screen)
and E2E-8 (the `/runs` cross-agent feed navigation), rather than all 11.
This is a scope recommendation for `product-engineer`'s drift-reconciliation
flow, not a mandate — `verifier` reports the judgment, it does not decide
the PRD's roadmap.

---

## Quality gates (PRD-level)

- `coverage_gate: PASS` (aggregate) — reproduced live in this session, matching the `qa-engineer` rollup's own run.
- `lint`/`format:check`/`typecheck`/`test`/`audit`: all PASS, reproduced live.
- No numeric `test:coverage` percentage was pulled in this pass (same caveat the `qa-engineer` rollup noted) — the `validate` run already proves genuine, non-vacuous execution of every test, which was the higher-priority ground-truth question for this audit.

## Recommendations (per drift item)

| Drift # | Recommended next step |
|---|---|
| 1–8 | `product-engineer`'s `activity-drift-reconciliation` — PRD/spec changelog write-back only; no code change needed |
| 9 (E2E) | `product-engineer` to evaluate a small follow-up story for E2E-8/E2E-9/E2E-10 (see judgment above); no action needed on the remaining 8 scenarios given the strength of the lower-layer coverage |

## What was not analyzed, and why

- Numeric `test:coverage` percentage (time-bounded; the `validate` ground-truth run was the higher-priority question this task asked).
- Full Playwright execution of the *existing* 6 pre-existing E2E specs (`auth.spec.ts`, `density.spec.ts`, `edge-cases.spec.ts`, `invoke.spec.ts`, `live-tail.spec.ts`, `stale-and-artifact.spec.ts`) — none of the 7 stories modified them, and the 0/11 gap finding is established by direct file-presence inspection, which does not require executing the unrelated pre-existing suite.
- The second workspace package (`agents/dependency-update/agentcore/cdk`) — out of scope, untouched by this PRD.
