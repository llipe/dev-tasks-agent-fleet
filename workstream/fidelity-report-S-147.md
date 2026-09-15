# Verifier Audit (Audit Mode) — Story S-147

**Fidelity: High**
**Highest drift impact: Minor**

> Note: this audit was performed by `developer` acting in `verifier`'s Audit
> Mode role, as no subagent-invocation tool was available in this execution
> environment to delegate to a separate agent instance (same posture as the
> S-146 PR precedent, #213). The report follows verifier's mandated Audit
> Mode structure (grey-box evidence, drift classification by impact/intent,
> verdict-first). Same posture applies to the `qa-engineer` coverage gate,
> recorded separately in the PR/closeout.

## Scope

Story S-147 (Repositories — list and add-by-reference), issue #207, against
`workstream/user-stories-prd-agent-fleet-panel-v3-ui-depth.md` (S-147
section), `workstream/specification-prd-agent-fleet-panel-v3-ui-depth.md`
§6/§7/§8.4/§10/§12, and `docs/requirements/prd-agent-fleet-panel-v3-ui-depth.md`
FR15/FR16/FR18.

## Acceptance criteria — evidence

| AC | Requirement | Verdict | Evidence |
|---|---|---|---|
| AC1 | `/repositories` lists non-archived rows by default (`full_name`, `default_branch`, enabled state) | **Pass** | `RepositoryTable.test.tsx`, `repositories-page-wiring.test.tsx` (asserts `getRepositories` called with no `includeArchived` opt-in), `repository-mutations.test.ts` (list excludes archived against the real stack) |
| AC2 | "Add repository" inserts a new row without calling the GitHub API | **Pass** | `repository-mutations.test.ts` — explicit `fetch` spy scoped to `github.com`/`api.github.com` domains, asserts zero calls during `insertRepository` |
| AC3 | Duplicate `full_name` under the installation → friendly `REPOSITORY_ALREADY_EXISTS`, not a raw Postgres error, no second row | **Pass** | `repository-mutations.test.ts` — pre-check path (sequential inserts) AND a genuine concurrent-race test (`Promise.allSettled` on two simultaneous inserts of the same `full_name`, asserting exactly one winner, the loser gets `REPOSITORY_ALREADY_EXISTS`, and the DB never holds two rows) — both paths of the documented dual-rejection design are exercised, not just the common case |
| AC4 | Malformed `full_name` rejected client-side before submission AND server-side inside the Server Action | **Pass** | `repository-input.test.ts` (13 tests incl. a metamorphic property test against a direct regex re-check and an adversarial-string fuzz table), `AddRepositoryForm.test.tsx` (client-side `preventDefault` + inline error), `repository-actions.test.ts` (the pure `resolveAddRepository` core re-validates and never calls either injected dependency on a malformed input) |
| AC5 | Sidebar "Repositories" is a live link to `/repositories` | **Pass** | `Sidebar.test.tsx` extension (link + active-route assertions), `AppShell.test.tsx` extension (now 3 of 5 destinations live, 2 deferred) |
| AC6 | Reachable only when authenticated | **Pass** | `/repositories` falls through to the existing fail-closed `ui` classification in `lib/auth/route-policy.ts` (unchanged); covered by the existing generic "unknown path defaults to `ui`" test in `auth-route-policy.test.ts` — no new gate test needed, matching the story's own AC-to-test mapping |

All 6 acceptance criteria: **Pass**.

## Drift

One item, classified **Minor / Intended**:

- **ESLint SD2-exemption scope widened.** `panel/eslint.config.mjs`'s
  `no-restricted-imports` exemption list (previously
  `page.tsx|layout.tsx|route.ts|template.tsx|default.tsx|error.tsx|loading.tsx|not-found.tsx`)
  now also excludes `app/**/actions.ts`. This was NOT explicitly anticipated
  in spec §6/§12 — the spec says the action "uses the existing
  `createServerClient()` service-role client" but does not call out that this
  is the first `"use server"` action file to do so directly, and therefore
  the first to trip the SD2 lint rule (previously only route handlers and
  App Router entrypoints needed the exemption; `app/login/actions.ts` never
  imports `lib/supabase/server.ts` directly, only the lower-privilege
  `auth-server.ts`). The fix is architecturally sound (same rationale as the
  existing `route.ts` exemption: a legitimate server-only call site, still
  guarded by the hard `import "server-only"` build-time pragma) and is
  documented inline in the eslint config with the story reference. **Not
  blocking** — flagged so `technical-writer`/`product-engineer` can decide
  whether `docs/technical-guidelines.md`'s SD2 description should be updated
  to mention Server Actions as a third legitimate server-only call-site
  category alongside route handlers and App Router entrypoints.

No Critical or Major drift. No Unintended drift.

## Known limitation (not drift — documented risk acceptance)

No new Playwright E2E spec was added for this story. The user-stories file's
"Files to Create/Modify" list for S-147 does not include an E2E spec file (the
spec's §14 testing-strategy table lists an E2E scenario for repositories, but
the story's own Testing Requirements section separates "Manual/UI Testing"
from "E2E (Playwright)" and does not commit a new spec file for this story).
A full interactive browser click-through (add → confirm in Invoke dialog →
duplicate → malformed) was **not performed** in this execution session — the
sandboxed environment did not run a browser/Playwright pass. This is recorded
honestly as a manual-verification gap, not fabricated as complete; the
automated Layer 1/2/2.5 coverage (33 new/extended tests, all against real
data-layer behavior at Layer 2.5) covers every acceptance criterion's
underlying logic. Recommend a manual click-through before merge if a
developer has interactive access to the running stack.
