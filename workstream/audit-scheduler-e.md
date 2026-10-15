# Fidelity Audit — Scheduler Wave E (S-161–S-164)

## Header / Verdict

- **Overall fidelity:** High
- **Highest drift impact present:** Minor
- **Scope:** issues #273 #274 #275 #276 · PRD `docs/requirements/prd-agent-scheduler.md` · delivered via integration PR #296 (merged 2026-10-14) · audited read-only on **main @ e5dbbbe**.
- **Mode:** Audit (grey-box). Verified against source on `main`, **not** PR states (several story PRs are CLOSED, not merged; issue checkboxes all unticked — ignored per instruction).

Drift is **non-blocking** to issue/PR completion and does not replace the quality gates.

## Human-readable summary (what changed and why)

Wave E is the operator-facing UI for the agent scheduler. All four screens are present and wired on `main`:

- **#273 /schedules** — a full fleet schedules table (seven columns, state pills with the hollow "paused" dot, blocked/skipped reason chips, and the "PR handled · resume anyway" clear), plus pause/resume/delete server actions and a delete confirmation dialog. The sidebar "Schedules" item is a live nav link.
- **#274 new/edit dialog** — an agent-select → schema-driven param form (reusing the invoke form + Ajv validation), a cadence picker with a live "next 3 runs" preview sourced from the authoritative database RPC, collapsible guardrails, and create/edit actions that re-validate params at save.
- **#275 notifications** — a `/notifications` feed and a top-bar bell with an unread badge; untrusted notification text is rendered as inert text (never markup), links come only from structured ids, and mark-(all)-read works. Reads are server-side with RLS deny-all.
- **#276 agent indicator** — a read-only "N schedules" link on the agent run-history header that lands on `/schedules?agent=<slug>`, with a zero-state.

Everything is backed by unit, component, and Layer-2.5 integration tests, all green on `main` CI (58c1d1c+) and re-confirmed locally for the unit/component layers. The few gaps are test-assertion and documentation nits, not behavioral defects. Production logs (2026-10-15) show schedules firing and the digest running, confirming the end-to-end path is live.

---

## Issue #273 — S-161: /schedules list + CRUD

| AC | Verdict | Evidence |
| --- | --- | --- |
| AC1 — Matches §5.7 + prototype (grid, state pills incl. hollow paused dot, cadence formats, reason chips) | MET | `panel/components/schedules/SchedulesTable.tsx:117-153` (7 columns), `:63-82` hollow paused dot, `:168-178` reason chip; `tests/component/schedules-table.test.tsx:64` column set, `:97,109` pills/reason. Pixel parity is best-effort (not pixel-diffed here). |
| AC2 — CRUD redirects /login (UI) / 401 (API) when unauthenticated (AC14) | MET | `/schedules` is not `public` → `panel/lib/auth/route-policy.ts:42`; `panel/proxy.ts:150,175` 302→/login. Internal fire route fail-closed: `panel/app/api/internal/schedules/[id]/fire/route.ts` via `authorizeInternalRequest`. E2E: `tests/e2e/schedules-crud.spec.ts:106-116` (redirect + 401). |
| AC3 — Delete keeps the schedule's produced runs | MET (minor drift) | Runs link to schedules by `runs.triggered_by='schedule:<uuid>'` text, **no FK** (`supabase/migrations/20261013167000_scheduler_notify_sweep.sql:26`), so a schedule delete cannot touch runs. `deleteSchedule` is a bare `delete` (`panel/lib/supabase/queries.ts:1050`). Drift: the query's doc-comment claims runs are preserved via an "on delete set null" FK — inaccurate (that applies to `notifications.schedule_id`, migration 160000:108; runs have no such column). Outcome is correct; comment is wrong. No test directly asserts run survival post-delete. |
| AC4 — Nav item active on /schedules | MET | `panel/components/shell/Sidebar.tsx:54,92-97` live `NavItem` + `schedulesActive`. |

**Overall verdict #273: CLOSE-WITH-FOLLOW-UP** — all ACs met; one inaccurate code comment + a missing direct delete-keeps-runs assertion.

---

## Issue #274 — S-162: new/edit schedule dialog

| AC | Verdict | Evidence |
| --- | --- | --- |
| AC1 — Matches §5.7.2 | MET | `panel/components/schedules/ScheduleDialog.tsx` — agent select, conditional repo select, schema param grid, cadence picker, preview, collapsible guardrails, footer. No L2 component test (see drift); E2E `tests/e2e/schedule-dialog.spec.ts`. |
| AC2 — Correct param form per agent from params_schema + Ajv validate at save (AC13) | MET | Form built from `buildFieldDescriptors(agent.paramsSchema)` (`ScheduleDialog.tsx:65`); save re-validates via `validateParams(...)` in `panel/lib/domain/schedule-save.ts:263-276`. L2.5: `tests/integration/schedule-mutations.test.ts:77` (persist). |
| AC3 — Preview updates live and agrees with stored next_run_at | MET | Debounced preview via `previewScheduleAction` → `scheduler_preview_next_runs` RPC (`supabase/migrations/20261013169500_...`), same plpgsql math as `compute_next_run_at`/seed trigger that sets `next_run_at` (SD-T6). L2.5: `schedule-mutations.test.ts:110-147`. |
| AC4 — Invalid cadence disables submit | MET | `cadenceValid` gate: `ScheduleDialog.tsx` submit `disabled={pending || !cadenceValid}`; `validateCadence` in `schedule-save.ts:118-160`; unit `tests/unit/cadence.test.ts` + `validateCron`. |
| AC5 — A new agent needs no scheduler-specific code | MET | Dialog is schema-driven off `params_schema`/`default_params` only (`ScheduleDialog.tsx:116-130`), reusing the generic `FieldRow`; no per-agent branches. |

**Overall verdict #274: CLOSE-WITH-FOLLOW-UP** — all ACs met; the planned **L2 `schedule-dialog.test.tsx` (task 14.2) is absent** — dialog behavior is covered only at E2E + L2.5, a layer gap vs. the plan.

---

## Issue #275 — S-163: notifications feed + bell + mark-read

| AC | Verdict | Evidence |
| --- | --- | --- |
| AC1 — Matches §5.8 + prototype | MET | `panel/components/notifications/NotificationsFeed.tsx` (grouped Today/Earlier, kind dots, links, footer) + `panel/components/shell/NotificationBell.tsx` (badge + popover, 5 newest). |
| AC2 — Newest-first + unread treatment + mark-(all)-read (AC11) | MET | `getNotifications` orders `created_at desc` (`queries.ts:1175`); unread edge via `item.unread`; `markNotificationReadAction`/`markAllNotificationsReadAction`. Component `tests/component/notifications-feed.test.tsx:44,65,73`. |
| AC3 — Detail renders inert text only (never markup / metadata-built link) | MET | Rendered as text child (`NotificationsFeed.tsx` `{item.detail}`); links derived only from structured ids (`notification-view.ts:46-50`). Test `notifications-feed.test.tsx:52` asserts `<img onerror>` is textContent, not DOM. |
| AC4 — Reads server-side with RLS deny-all preserved | MET | Reads in server components via service-role `createServerClient` (`notifications/page.tsx`, `(panel)/layout.tsx`). RLS: `tests/integration/rls-deny-all.test.ts` enumerates every base table from information_schema → `notifications`/`schedules` auto-covered (anon reads 0 rows). |
| AC5 — Bell badge reflects the unread count | MET | `getUnreadCount` (`queries.ts:1188`); badge hidden at 0, `99+` cap (`NotificationBell.tsx`). Fed from `(panel)/layout.tsx`. |

**Overall verdict #275: CLOSE** — all five ACs met with code + tests on `main`.

---

## Issue #276 — S-164: agent-page scheduled indicator

| AC | Verdict | Evidence |
| --- | --- | --- |
| AC1 — Matches §5.7.1 | MET | Read-only link in `panel/components/runs/AgentHeader.tsx` meta row; no CRUD on the agent page. |
| AC2 — Count is accurate | MET | `getScheduleCountByAgent` exact head-count (`queries.ts:996-1007`); wired in `agents/[slug]/page.tsx` Promise.all. Component `tests/component/agent-schedule-indicator.test.tsx:33` (3 schedules). |
| AC3 — Link lands on /schedules filtered to the agent | MET | `href={`/schedules?agent=${header.slug}`}` (`AgentHeader.tsx`); target renders the filter chip (`schedules/page.tsx:60-65`). Test `:34` asserts the href. |
| AC4 — Zero schedules renders a 0-state (per prototype) | MET | `scheduleCount === 0 ? "No schedules" : …` still a link (`AgentHeader.tsx`); test `:42` zero-state, `:48` omitted when undefined. |

**Overall verdict #276: CLOSE** — all ACs met with code + tests on `main`.

---

## Drift catalog

| # | Description | Impact | Intent | Source | Note |
| --- | --- | --- | --- | --- | --- |
| D1 | `deleteSchedule` comment says runs are kept via an "on delete set null" FK; runs actually link by `triggered_by` text with no FK. Outcome correct, comment misleading. | Minor | Unintended | `queries.ts:1046-1053` vs migration 167000:26 | Doc-only; non-blocking. |
| D2 | No direct test asserts a schedule's produced runs survive deletion (AC3). Covered architecturally, not by assertion. | Minor | Undetermined | `tests/integration/schedule-mutations.test.ts:77-92` | Add a run-then-delete-schedule integration assertion. |
| D3 | Planned L2 `schedule-dialog.test.tsx` (task 14.2) absent; dialog has only E2E + L2.5 coverage. | Minor | Unintended | plan `tasks-prd-agent-scheduler-plan.md` §14.2 | Layer gap vs. plan, not an AC failure. |

All drift is **non-blocking** to completion.

## Follow-up items

1. **D1** — correct the `deleteSchedule` doc-comment (runs link by `triggered_by` text, not an FK). → `developer`, trivial.
2. **D2** — add an L2.5 assertion: insert schedule → insert a `triggered_by='schedule:<id>'` run → delete schedule → run still present. → `qa-engineer`.
3. **D3** — add the planned L2 `schedule-dialog.test.tsx` (kind switching, preview, guardrail disclosure, submit states). → `qa-engineer`.
4. **Out-of-scope observation (not in S-161–S-164):** the 12:58:21Z digest `UNAUTHORIZED` then `empty_window` at 12:58:23Z belongs to **S-159 (#271)**, the digest endpoint, not Wave E. The route is fail-closed by design (`internal-secret.ts`); a single 401 followed by a successful empty-window call is consistent with a credentialed `pg_cron` retry after a transient/secret miss. Recommend verifying under #271 that the `pg_cron` job presents `X-Scheduler-Secret` correctly; no Wave E action.

## Issue checkbox note

Every issue's acceptance checkboxes are unticked on GitHub despite delivery. This is tracking drift (routes to `product-engineer` / `github-ops` reconciliation), independent of the code fidelity verdicts above.

---

ISSUE #273: CLOSE-WITH-FOLLOW-UP — all ACs met; stale delete comment + missing delete-keeps-runs assertion
ISSUE #274: CLOSE-WITH-FOLLOW-UP — all ACs met; planned L2 dialog test absent
ISSUE #275: CLOSE — all five ACs met with code and tests on main
ISSUE #276: CLOSE — all four ACs met with code and tests on main
