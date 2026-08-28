# PRD — Agent Fleet Control Panel v3: UI Depth (DRAFT — not refined)

## Changelog

| Version | Date       | Summary                                                                 | Author           |
| ------- | ---------- | ----------------------------------------------------------------------- | ---------------- |
| 0.1     | 2026-08-27 | Initial draft. Captures `/DESIGN.md`-specified UI behaviors and the four deferred sidebar destinations that were scoped out of [`prd-agent-fleet-panel-v2.md`](prd-agent-fleet-panel-v2.md) v2.1. **Not refined — placeholder for a later `activity-refine` pass.** | product-engineer |

> **Status: DRAFT placeholder.** This document exists so that requirements derived from
> `/DESIGN.md` and the prototype are not lost when Phase 2 ships a narrower scope. It has
> **not** been through refinement: there are no agreed acceptance criteria, no sizing, and
> no priority order. Do not generate a specification from this document until it has been
> refined.

---

## 1. Purpose

[`prd-agent-fleet-panel-v2.md`](prd-agent-fleet-panel-v2.md) v2.1 scoped Phase 2 to four screens: App Shell, Agents Dashboard, Agent Run History, and Run Detail (plus the Invoke dialog). The prototype at `/docs/prototype/` and [`/DESIGN.md`](/DESIGN.md) specify additional behavior and additional destinations that Phase 2 does not deliver.

This document is the holding pen for that scope. Each item below records **what `/DESIGN.md` already specifies**, so a future refinement pass starts from a design contract rather than a blank page.

## 2. Relationship to Phase 2

Phase 2 (v2.1) is a precondition for everything here. Nothing in this document is independently deliverable — every item extends a screen that Phase 2 builds.

| This document assumes Phase 2 delivered | Reference |
|---|---|
| App Shell with sidebar + content region | v2.1 §11, `/DESIGN.md` §4.1 |
| Agents Dashboard with density toggle | v2.1 FR17 / D17 |
| Agent Run History table | v2.1 FR11 |
| Run Detail with log viewer | v2.1 FR12 |
| Reads routed through `v_runs` | v2.1 FR11a |

---

## 3. Candidate Requirements — Run History Depth

Sourced from `/DESIGN.md` §5.2. Phase 2 ships an unfiltered, unpaginated newest-first list.

| ID | Candidate requirement | `/DESIGN.md` reference |
|---|---|---|
| C1 | Status segmented control with a colored dot and a live count per status | §5.2 filter bar, §8.1 status mapping |
| C2 | Repository filter chips | §5.2 |
| C3 | Free-text search across the run list | §5.2 |
| C4 | Pagination as "X of Y" plus a "Load more" button (not numbered pages) | §5.2, §7.3 (`8 of 82`) |
| C5 | Empty state with explanatory message and CTA buttons | §5.2 |
| C6 | Connection-state live indicator in the filter bar | §5.2, §6.1 (`pulse` 2s slow) |
| C7 | Branch and PR links rendered inline in the repository column | §5.2 table columns |

**Open for refinement:** whether filters are URL-encoded (shareable/bookmarkable) or ephemeral client state. Affects whether filtering is a server query or a client-side array filter, which in turn affects whether C4 pagination can coexist with C1–C3 correctly.

---

## 4. Candidate Requirements — Run Detail Depth

Sourced from `/DESIGN.md` §5.3, §8.3, §11.3.

| ID | Candidate requirement | `/DESIGN.md` reference |
|---|---|---|
| C8 | Steps panel: vertical list with colored dot, mono name, duration, event count | §5.3 |
| C9 | Clicking a step filters the log viewer to that step's events | §5.3 |
| C10 | Terminal-state banners for `timed_out` and `failed_to_start`, with colored border, background tint, explanation, action buttons, and metadata | §8.3 |
| C11 | Log level coloring and level-based filtering | §5.3, §3.6 |
| C12 | Live-tail pause/resume: auto-scroll within 24px of bottom, scroll-up pauses, clicking "live tail" resumes | §6.6, §11.3 |
| C13 | Log viewport bounding — windowing or virtualization so the viewer does not attempt an unbounded `run_events` fetch | §5.3; risk R3 in v2.1 §17 |
| C14 | Realtime reconnect backfill: on subscription recovery, fetch events above the last-seen `seq` so no event is silently dropped | §11.3; v2.1 §12 deferred-decisions table |
| C15 | Artifact links rendered as pills, including on `failed` runs carrying a `pull_request` artifact | §5.3, v2.1 §11 |
| C16 | Queued-state spinner (`spin` 0.9s) distinct from the running pulse | §6.1, §8.1 |

> **Note on C13 and C14:** v2.1 §12 requires the Phase 2 spec to make a minimal decision on
> both (an initial fetch size, and not silently losing events on reconnect). What is deferred
> here is the *full* treatment — virtualization for large runs, and a reconciliation strategy
> that survives long disconnects. Phase 2 must not ship an unbounded fetch or a silent gap.

---

## 5. Candidate Requirements — Deferred Sidebar Destinations

The prototype's sidebar (`/DESIGN.md` §10) shows four destinations that v2.1 §10 declares out of scope. Each needs its own refinement before it becomes a screen.

| ID | Destination | What it would need to exist first |
|---|---|---|
| C17 | **All runs** — cross-agent run feed | Only becomes useful at fleet size > 1. Needs a decision on whether it is a distinct query or the Run History with the agent filter removed |
| C18 | **Repositories** | Repo sync from the GitHub App (v2.1 §10 backlog). Without sync this is a read-only view of a manually seeded table |
| C19 | **Settings** | Nothing is currently user-configurable. Needs a real configuration surface to exist — candidate: per-agent `max_runtime_seconds`, `AGENT_LOG_LEVEL`, retention policy |
| C20 | **System health** | Needs a health signal. `last_heartbeat_at` exists in the schema but is unused for detection (v2.1 §9). Depends on the heartbeat backlog item |

---

## 6. Candidate Requirements — Cross-Cutting

| ID | Candidate requirement | `/DESIGN.md` reference |
|---|---|---|
| C21 | Command palette (`Cmd+K`) | §6.5 — shown in the prototype UI but has no backing behavior |
| C22 | Ledger-view keyboard navigation (`Up`/`Down`, `Enter` to run, `/` to focus filter) | §6.5, §5.1 variant 1c |
| C23 | Responsive behavior below 1024px | §9 — explicitly undefined in the prototype; acceptable for a single-operator tool, so this may be permanently declined rather than deferred |
| C24 | Phosphor Icons replacing the prototype's Unicode glyph stand-ins | §10 |

> C24 is a plausible candidate for pulling *into* Phase 2 — it is a dependency addition and a
> glyph swap, not a behavior change. Flagged for the refinement pass to reconsider.

---

## 7. Non-Goals

- User authentication remains out of scope here as well. It is tracked as the Supabase Auth backlog item in v2.1 §10, not as a UI-depth concern.
- Nothing in this document changes the data model. Every candidate reads existing tables. If refinement surfaces a schema need, it belongs in a separate PRD.

## 8. Open Questions

- Priority order across C1–C24 is undetermined. The likely first cut is C10 + C15 (terminal-state banners and artifact surfacing), because they make failure states legible, and failure legibility is the original problem statement.
- Is C23 (responsive) deferred or declined? `/DESIGN.md` §9 leans toward declined.
- Does C17 (All runs) become necessary only when a second agent ships, making it a natural companion to onboarding agent #2 rather than a standalone item?
- Several candidates (C1–C4) interact: filtering plus pagination plus Realtime insertion into a filtered list is a known-fiddly combination. Should they be refined as one story rather than four?
