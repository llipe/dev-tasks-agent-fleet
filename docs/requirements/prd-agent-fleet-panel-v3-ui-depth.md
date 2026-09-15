# PRD — Agent Fleet Control Panel v3: UI Depth

## Changelog

| Version | Date       | Summary                                                                 | Author           |
| ------- | ---------- | ----------------------------------------------------------------------- | ---------------- |
| 0.1     | 2026-08-27 | Initial draft. Captured `/DESIGN.md`-specified UI behaviors and the four deferred sidebar destinations that were scoped out of [`prd-agent-fleet-panel-v2.md`](prd-agent-fleet-panel-v2.md) v2.1. Not refined — placeholder for a later `activity-refine` pass. | product-engineer |
| 1.0     | 2026-09-15 | **Refined from the DRAFT placeholder.** Re-audited every C1–C24 candidate against the codebase as it stands after Phase 2 shipped through S-123 (2026-09-11): C10, C12, C13, C14, C15, C24 are already delivered and are removed from scope (recorded in §10 as Done, not requirements). Scoped into this PRD: Run History depth (C1–C7), the Run Detail steps panel (C8–C9), the two remaining Run Detail gaps (C11 log-level coloring/filtering, C16 the queued-vs-running animation defect), and — reversing the v2.1 §10 non-goal — the **All runs** and **Repositories** sidebar destinations, with Repositories redefined per user decision as a manually-managed reference list (add-by-reference, soft-delete/archive) rather than GitHub App repo sync. Settings, System health, and the command palette (C21–C22) stay parked (unmet preconditions / no demonstrated need yet). Responsive behavior below 1024px (C23) is declined permanently, not deferred. Filter state (C1–C4) resolved to URL-encoded, server-paginated queries. Also flagged and fixed an unrelated accidental regression discovered during this refinement: commit `9f8cbad` had truncated `/DESIGN.md` from 720 to 233 lines while adding unrelated `.claude/` tooling; it was restored (user-confirmed) before this refinement was written, so the section references below are valid again. | product-engineer |

---

## 1. Executive Summary

[`prd-agent-fleet-panel-v2.md`](prd-agent-fleet-panel-v2.md) v2.1 scoped Phase 2 to four screens (App Shell, Agents Dashboard, Agent Run History, Run Detail) plus the Invoke dialog, and explicitly moved **All runs**, **Repositories**, **Settings**, and **System health** to Non-Goals pending their preconditions. Phase 2 has since shipped all four core screens plus authentication (S-106 through S-123). This PRD is the second UI-depth iteration: it takes the run history and run detail screens from "reads `v_runs` correctly" to "usable for triage across a growing run volume," and it brings two of the four deferred sidebar destinations back into scope now that their preconditions are met well enough to ship a first version.

## 2. Feature Overview

Four capability groups, each independently shippable:

1. **Run History depth** — status/repo/search filtering, pagination, an empty state, and inline branch/PR links on the existing `/agents/[slug]` screen.
2. **Run Detail depth** — a steps panel that filters the log viewer, log-level coloring and filtering, and a fix to the queued-status animation.
3. **All runs** — a new cross-agent run feed at `/runs`, reusing the Run History table and filter bar with an agent column added.
4. **Repositories** — a new `/repositories` screen: list, add-by-reference, and archive (soft delete) against the existing `repositories` table. This is **not** GitHub App repo sync — adding a repository here only inserts a row the panel and agents can reference; it does not call GitHub to create, fork, or verify anything.

## 3. Goals & Objectives

1. Make the Run History screen usable once run volume exceeds what fits unfiltered on one page (today: unfiltered, unpaginated, per v2.1 FR11).
2. Make failure triage in Run Detail faster by letting an operator jump straight to the failing step's log lines instead of scrolling the full tail.
3. Give the operator one place to see activity across every agent (`/runs`), not just per-agent (`/agents/[slug]`) — a natural companion to onboarding a second agent, brought forward now by user request rather than gated on that onboarding.
4. Let the operator register a repository for agent use without an AWS console or a manual `INSERT` — closing the gap the v2.1 backlog flagged ("repo sync from the GitHub App... without sync this is a read-only view of a manually seeded table") with a manual-reference version that ships now instead of waiting on GitHub App sync.
5. Fix two visible defects against the design contract already in the codebase (queued spin animation, `N/A`-adjacent log-level coloring) while the surrounding screens are being touched anyway.

## 4. Affected Repositories

| Repo | Role / Impact |
|---|---|
| This repo (`dev-tasks-agent-fleet`, `panel/` workspace) | All work is front-end (`panel/app`, `panel/components`, `panel/lib`) plus two new Server Actions for repository add/archive. No AgentCore, no infra, no new migration. |

## 5. Target Users

Same as the rest of the panel — see `product-context.md` §3. Primary user: the project author, as operator of the agent fleet. No new persona.

## 6. User Stories

1. As the operator, I want to filter the run history by status so I can find every `failed` run for an agent without scrolling.
2. As the operator, I want to filter by repository so I can see how one repo's runs have gone across invocations.
3. As the operator, I want to search runs by free text so I can find a specific run without knowing its status or repo.
4. As the operator, I want pagination so a history of hundreds of runs doesn't load or render as one unbounded list.
5. As the operator, I want an empty state with a clear next action when a filter matches nothing, so I know whether to relax the filter or that there really is nothing there.
6. As the operator, I want to see branch and PR links directly in the run history table so I don't have to open each run to check them.
7. As the operator, I want a steps panel on Run Detail so I can see which step failed at a glance and click straight to its log lines.
8. As the operator, I want log lines colored and filterable by level so I can isolate warnings/errors in a noisy log.
9. As the operator, I want to see every agent's runs in one feed so I don't have to check each agent's history in turn.
10. As the operator, I want to register a new repository for agent use from the panel, without touching Supabase or GitHub directly.
11. As the operator, I want to archive a repository I no longer use so it stops appearing as an active target, without losing its run history.

## 7. Functional Requirements

### Run History depth (`/agents/[slug]`)

1. **FR1.** The Run History filter bar **MUST** offer a status segmented control (`queued`/`running`/`succeeded`/`failed`/`timed_out`/`failed_to_start`/all) built on `effective_status` (v2.1 FR11a — never raw `runs.status`), each option showing a colored dot and a live count for the current filter set.
2. **FR2.** The filter bar **MUST** offer repository filter chips populated from the repositories that actually appear in that agent's runs (not the full `repositories` table).
3. **FR3.** The filter bar **MUST** offer a free-text search box matching against repository name, branch, and run ID.
4. **FR4.** Status, repo, and search filters **MUST** be encoded in the URL query string (shareable/bookmarkable) and **MUST** drive a server-side, paginated Supabase query — not a client-side filter over an already-loaded array. This is a deliberate reversal of the "unfiltered, unpaginated" v2.1 FR11 scope.
5. **FR5.** Pagination **MUST** render as "`X of Y`" plus a "Load more" button (never numbered pages), consistent with `/DESIGN.md` §5.2/§7.3.
6. **FR6.** An empty result set **MUST** show an explanatory message plus at least one CTA (e.g., "Clear filters").
7. **FR7.** The repository column **MUST** render the branch and, when present, a PR link inline — no need to open the row to see them.
8. **FR8.** The filter bar **MUST** show a connection-state indicator reflecting whether the underlying Realtime-backed live list (if newly-arrived runs are inserted live under a filter — see Open Questions §18) is currently connected.

### Run Detail depth (`/runs/[id]`)

9. **FR9.** Run Detail **MUST** render a steps panel: a vertical list of the run's `run_steps`, each with a colored status dot, mono step name, duration, and event count.
10. **FR10.** Clicking a step **MUST** filter the log viewer to that step's events only (via `run_events.step_id`); a visible "All steps" control **MUST** clear the filter back to the full tail.
11. **FR11.** The log viewer **MUST** color each line by `run_events.level` and **MUST** offer a level filter (e.g., warn/error only) independent of the step filter in FR10 — both filters **MUST** be able to apply together.
12. **FR12.** The `queued` status dot **MUST** use the `spin 0.9s` animation per `/DESIGN.md` §6.1, distinct from the `running` dot's `pulse 1.6s` — fixing the current defect where `components/status-meta.ts` marks both `queued` and `running` as `pulse: true`.

### All runs (`/runs`)

13. **FR13.** A new `/runs` screen **MUST** show every run across every enabled agent, newest-first, reusing the Run History table and the FR1–FR8 filter bar, with an added Agent column (name + slug) and an added agent filter alongside the repo filter.
14. **FR14.** The sidebar "All runs" item (`/DESIGN.md` §10, currently rendered disabled per v2.1 §10) **MUST** become a live link to `/runs`.

### Repositories (`/repositories`)

15. **FR15.** A new `/repositories` screen **MUST** list rows from the existing `repositories` table (excluding archived rows by default), showing `full_name`, `default_branch`, enabled state, and archived state.
16. **FR16.** The screen **MUST** offer an "Add repository" action that inserts a new `repositories` row (`full_name`, `default_branch`, defaulting `is_enabled = true`) against the single seeded `github_installations` row. This action **MUST NOT** call the GitHub API to create, verify, or fork anything — it is a manually-entered reference only, matching the existing `uq_repositories_full_name` constraint (duplicate `full_name` under the same installation is rejected with a friendly error, not a raw constraint violation).
17. **FR17.** The screen **MUST** offer an "Archive" action per repository that sets `archived_at = now()` (soft delete) rather than deleting the row, preserving referential integrity for `runs.repository_id`. Archived repositories **MUST NOT** appear in the Repositories list's default view or in Invoke-dialog repository selectors, but existing runs against them **MUST** continue to display their repository name unchanged.
18. **FR18.** The sidebar "Repositories" item (currently rendered disabled) **MUST** become a live link to `/repositories`.

## 8. Business Rules

- Filter and pagination state for both `/agents/[slug]` and `/runs` lives in the URL query string, never in `localStorage` or component state alone — this is a deliberate divergence from the Agents Dashboard's `localStorage`-persisted density toggle (v2.1 D17), because run-list filters are a query a user reasonably wants to share or bookmark, while a density preference is not.
- Every status shown anywhere in this PRD's scope (FR1's segmented control, the connection-indicator-adjacent run rows, the All-runs feed) **MUST** derive from `effective_status` (`v_runs`), never raw `runs.status`, per the standing FR11a rule (SD4 `lib/domain/status.ts`) — this PRD introduces no new status-derivation logic, it only adds a filter/UI layer on top of the existing one.
- Adding a repository is intentionally **not** validated against the live GitHub API in this iteration — the only server-side validation is shape (`owner/repo` format) and the existing DB uniqueness constraint. A repository that does not actually exist on GitHub can be added; the resulting run invocation against it fails normally at the GitHub-App-auth or clone step, the same way any other misconfiguration would.
- Archiving a repository is reversible only by a direct DB action in v1 — there is no "restore" affordance in this PRD's scope (see Open Questions §18).

## 9. Data Requirements

**No schema migration is required.** Every requirement in this PRD reads or writes columns that already exist:

| Entity | Used for | New column/migration? |
|---|---|---|
| `run_events.level`, `run_events.step_id` | FR11 log-level coloring/filter, FR10 step-click filter | No — both columns exist in `20260902200101_initial_schema.sql` |
| `run_steps` (`key`, `title`, `status`, `started_at`, `finished_at`) | FR9 steps panel | No |
| `repositories` (`full_name`, `default_branch`, `is_enabled`, `archived_at`) | FR15–FR17 | No — `archived_at` already exists and is exactly the soft-delete column FR17 needs |
| `v_runs` | FR1–FR8, FR13 (already the FR11a-mandated read source) | No |

**New write path.** FR16/FR17 are the panel's first user-triggered write to a business table via a Next.js Server Action (the only prior user-triggered write is the FR14 `runs` insert from Invoke, v2.1). The mutation **MUST** follow the same server-only pattern as every existing read (SD2): a service-role client, never exposed to the browser, invoked from a `"use server"` action, with input validated before the write (not after, and not relying on the DB constraint alone for the user-facing error message).

## 10. Non-Goals (Out of Scope)

- **Already delivered — not requirements of this PRD, listed here so they are not re-scoped:** terminal-state banners (C10, `StateBanner.tsx`), live-tail pause/resume/autoscroll (C12), log-viewport windowing (C13, `selectRecentWindow`), Realtime-reconnect backfill (C14, the SSE relay), artifact links including on failed runs (C15, `ArtifactLinks.tsx`), Phosphor icons repo-wide (C24, S-105).
- **Command palette and ledger keyboard shortcuts (C21–C22).** `Cmd+K` is shown in `/DESIGN.md` §6.5 but has no backing behavior and no demonstrated operator need yet; parked for a future PRD.
- **Settings (C19).** Nothing is currently user-configurable (per-agent `max_runtime_seconds`, log level, retention policy); needs a real configuration surface designed before it is a screen.
- **System health (C20).** `last_heartbeat_at` exists in the schema but is unused for detection (v2.1 §9); needs the heartbeat backlog item first.
- **GitHub App repository sync.** FR16 is a manual reference add, not sync — verifying a repo actually exists on GitHub, importing its metadata, or reacting to GitHub App installation changes are all out of scope.
- **Repository edit/rename, or per-agent repository enablement (`agent_repository_settings`).** Both remain backlog items per `product-context.md` §6; FR15–FR18 touch only the `repositories` table, not a per-agent join.
- **Restoring an archived repository from the UI.** See Open Questions §18.
- **Responsive/mobile layout below 1024px (C23) — declined permanently, not deferred.** `/DESIGN.md` §9 already leans this way for a single-operator tool; this PRD makes it an explicit decision so it stops recurring as an open question in future refinements.
- **User authentication changes.** Out of scope; already shipped and stable (S-116–S-123).
- **Any change to the data model beyond the write path noted in §9.** Every candidate here reads or writes existing tables/columns.

## 11. Design Considerations

- `/DESIGN.md` §5.2 (Agent Run History) and §5.3 (Run Detail) already specify the filter bar, table columns, steps panel, and log-viewer layout this PRD implements — no new visual language is introduced. FR13 (All runs) reuses the same table and filter bar; its only new visual element is an Agent column, which should follow the existing dashboard's agent-identity treatment (slug in accent-400 mono, per §2.3).
- FR15–FR17 (Repositories) is the first genuinely new screen since Run Detail (S-109). It needs `/DESIGN.md` coverage before implementation: a new §5.6 documenting the list layout (reuse the existing table component family), the Add-repository form (reuse the Invoke dialog's field-row pattern, §5.4), and the Archive confirmation (a destructive action — needs a confirm step, unlike anything else currently in the panel).
- `/DESIGN.md` §9 (Responsive Behavior) should be updated from "undefined — acceptable" to an explicit "declined" statement now that this PRD makes that decision formal, so it stops reading as an open gap.
- **This feature has UI scope.** Per the standing `product-engineer` recommendation, `ux-engineer` (lite mode) should generate screen sketches for the two new screens (`/runs`, `/repositories`) and the two modified screens' new elements (filter bar, steps panel) before this PRD moves to spec.

## 12. Technical Considerations

- FR4's URL-encoded, server-paginated filters are a deliberate architecture change from every prior read screen in the panel (Dashboard's `AgentFilter` is transient client-only, per S-107; Run History today is a single unbounded `.range()`-paged fetch with no filter). The spec must define the Supabase query shape (`.eq`/`.in`/`.ilike` combinations against `v_runs`) and confirm it still pages correctly below the PostgREST `max_rows = 1000` ceiling (SD11) under a filtered result set.
- FR13 (All runs) reads `v_runs` without an agent filter — confirm the existing view's indexes support an unfiltered, paginated, newest-first scan at the current and near-term run volume without a new index.
- FR16/FR17 need a new `lib/supabase/mutations.ts` (or equivalent) alongside the existing read-only `lib/supabase/queries.ts` — the first mutation surface in that layer. It must be reachable only from Server Actions, never from a client component directly (SD2's `no-restricted-imports` boundary already covers `app/**`/`components/**`; confirm it also covers wherever this new module lives).
- FR8's connection-state indicator needs a decision in spec: does `/runs`/`/agents/[slug]` gain a Realtime subscription for live row insertion under a filter (new complexity — a filtered list must reconcile inserts against the current filter, matching the same class of problem the v2.1 FR11a risk register (§17) flagged for the dashboard), or is the indicator purely presentational (reflecting the existing per-run SSE connection state on Run Detail, not a new list-level subscription)? Recorded as Open Question §18.
- No new dependency is anticipated — steps panel, log filtering, and the two new screens are compositions of the existing Nocturne primitive set (`components/*`) plus the existing `lib/domain/status.ts`/`lib/format.ts` layers.

## 13. Acceptance Criteria

1. *(FR1)* Filtering Run History to `failed` shows only runs whose `effective_status` is `failed`, with a count matching the filtered set — verified against a `v_runs` fixture that includes a stale `running` row past its timeout threshold (must count as `timed_out`, not `running`).
2. *(FR2, FR3)* Combining a repository chip with free-text search narrows to the intersection, not the union, of both filters.
3. *(FR4)* Reloading a Run History URL that carries `?status=failed&repo=org/repo` reproduces the same filtered, server-side-queried result — not a client-side re-filter of an unfiltered fetch.
4. *(FR5)* "Load more" on a filtered result set fetches the next page under the current filter, not the next page of the unfiltered list.
5. *(FR6)* A filter combination matching zero runs renders the empty state with a working "Clear filters" CTA that returns to the unfiltered list.
6. *(FR7)* A run row with a `pull_request` artifact shows a clickable PR link inline in the repository column without opening the row.
7. *(FR9, FR10)* Clicking a `failed` step in the steps panel filters the log viewer to that step's events only; clicking "All steps" restores the full tail.
8. *(FR11)* Filtering the log viewer to `error`-level lines while a step filter is active shows only lines matching both.
9. *(FR12)* A `queued` run's status dot visibly uses the `spin` animation, distinct from a `running` run's `pulse` animation, in the same screen.
10. *(FR13)* `/runs` shows runs from at least two different agents newest-first, each row correctly attributed to its agent.
11. *(FR15, FR16)* Adding a repository with a `full_name` that already exists (case-sensitive exact match) under the installation shows a friendly duplicate error, not a raw Postgres constraint error, and does not insert a second row.
12. *(FR17)* Archiving a repository removes it from the default Repositories list and from the Invoke-dialog repository selector, while a pre-existing run against that repository still displays its `full_name` correctly on Run Detail and Run History.

## 14. Success Metrics

1. The operator can locate a specific failed run for a specific repository via Run History filters, without scrolling an unfiltered list, in a fixture with 100+ runs.
2. The operator can register a repository for agent use end-to-end from the panel (no Supabase Studio, no `psql`) in under 30 seconds.
3. Zero new database migrations are required to ship this PRD's scope (per §9 — a build-vs-plan-drift check for the spec phase).

## 15. Assumptions

- The single seeded `github_installations` row (per `product-context.md` §11 — "a single GitHub organization... is sufficient for v1") is assumed for FR16; the Add-repository form does not need an installation picker.
- Run and repository volume stays low enough (per `product-context.md` §11) that FR4/FR13's server-side paginated queries do not need a new index beyond what `v_runs` already provides — flagged as a technical consideration (§12), not assumed away entirely.
- The steps panel (FR9) and log-level filter (FR11) are read-only presentational work over existing `run_steps`/`run_events` rows; no agent-side (`agent_reporter.py`) change is required.

## 16. Constraints & Dependencies

- Depends on Phase 2's existing `v_runs`-based read layer (FR11a) and `lib/domain/status.ts` (SD4) — this PRD adds no new status-derivation logic, only filters and screens over the existing derivation.
- FR16/FR17 depend on the existing `repositories` table shape and its `uq_repositories_full_name` constraint being adequate for uniqueness checking; no dependency on the GitHub App beyond what already exists (`github_installations`).
- No AWS, AgentCore, or infra dependency — this is entirely a `panel/` front-end + Server Action change.

## 17. Security & Compliance

- FR16/FR17 are gated behind the existing auth boundary (S-116–S-123) exactly like every other panel screen — no new authorization tier is introduced (single authenticated operator, same as the rest of the panel).
- The new mutation surface (§9, §12) **MUST** preserve RLS deny-all (D11) and the service-role/SD2 server-only boundary — the Server Action, not a browser client, performs the write, identical in shape to the existing Invoke write path.
- FR16's deliberate non-verification of GitHub existence (§8) is a recorded, accepted risk, not an oversight: a misconfigured `full_name` fails safely and visibly at invocation time rather than being silently rejected at add-time, which would require a live GitHub API call this iteration does not want to take on.

## 18. Open Questions

- **FR8 connection indicator scope** — **RESOLVED in spec v1.0/v1.1** (§17 OQ1): presentational reuse only, no new Realtime/list-level subscription; the indicator renders a static "connected" state in v1 (a server-fetch failure hits the Next.js error boundary before it could ever render "disconnected" — the honest ceiling of this resolution, not a gap). Shipped as documented in Story S-143 / `docs/technical-guidelines.md` row 1.36 and `DESIGN.md` v1.6. ~~is it a new list-level Realtime subscription (inserting new runs live into a filtered list), or a presentational reuse of the existing per-run SSE connection state? This determines whether FR8 inherits the v2.1 FR11a "filtered list + live insert" risk class. Needs a decision in spec before FR8 is estimated.~~
- **Repository restore** — **RESOLVED, decided against for v1** (Story S-148 / issue #208): no restore affordance was built; reversal requires a direct DB action, an explicit confirmed v1 limitation, not an oversight (`DESIGN.md` §5.6, `docs/technical-guidelines.md` row 1.41). ~~FR17 ships archive with no restore UI. Is that acceptable for v1, or does archiving need to be reversible from `/repositories` itself rather than requiring a direct DB action?~~
- **All-runs pagination at scale:** FR13 is unfiltered by default across every agent. At what run count does an unfiltered `/runs` load become slow enough to warrant a default filter (e.g., "last 7 days") rather than "all, newest-first, paginated"? Not blocking for v1 given current volume (`product-context.md` §11), but worth a note in spec. **Still open** — flagged, not fixed, in the shipped code (spec §11/§17, `docs/technical-guidelines.md` row 1.39).
- **Priority order within this PRD** — **MOOT: all 7 stories (S-142–S-148) have since shipped**, so no further sequencing decision is needed. All four FR groups (Run History, Run Detail, All runs, Repositories) were independently shippable. ~~The natural first cut is Run History depth (FR1–FR8) plus the FR12 one-line animation fix, since Repositories (FR15–FR18) is the largest single addition (new screen + new write path) — but this is a sequencing suggestion for the plan phase, not a decision made here.~~
