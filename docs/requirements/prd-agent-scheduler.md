# PRD — Agent Scheduler

> Scheduled, unattended invocation of fleet agents on a configurable cadence, with
> firing guardrails and a table-first notification system (in-panel feed + daily SES
> email digest). Phase 4 of the Agent Fleet Control Plane.

## Changelog

| Version | Date       | Summary                                                                 | Author           |
| ------- | ---------- | ----------------------------------------------------------------------- | ---------------- |
| 1.0     | 2026-10-13 | Initial PRD. Produced from the `activity-refine` grill (A1 trigger architecture, C1 cadence model, G1–G5 guardrails, table-first notifications with daily SES digest, `/schedules` CRUD surface). | product-engineer |

---

## 1. Overview

Today every agent run is triggered **manually** from the panel's invoke form. The
data model has always anticipated scheduled execution — `runs.trigger_type` is an
enum of `('manual', 'schedule', 'webhook')` and `schedule` is unused — and
`product-context.md` §4 names "schedules" as an explicit extensibility goal of the
foundation. This PRD delivers the `schedule` branch: operators define a schedule
(agent + repository + validated params + cadence), and the system invokes the agent
unattended on that cadence, with guardrails that keep an unattended loop from
stacking redundant runs or hammering a broken agent, and a notification system that
surfaces notable outcomes without the operator watching the panel.

The feature is delivered **entirely within the existing stack** — no new AWS
orchestration infrastructure (the project deliberately tore out EventBridge/Lambda
in the reset; `product-context.md` §2/§5). Scheduling runs on the **`pg_cron`
extension already deployed for the reaper**, and execution reuses the **existing
panel invoke path** (`POST /api/agents/[slug]/invoke` → `InvokeAgentRuntime` over
Fly OIDC). This honors the "minimal cost and operational surface" constraint
(`product-context.md` §9).

This is Phase 4, following Phase 1 (backend + `dependency-update` agent), Phase 2
(panel UI, deployed public behind login), and Phase 3 (`security-analyst` agent).

## 2. Problem Statement

An operator who wants an agent to run on a recurring basis — e.g. `dependency-update`
in `audit_only` mode every morning, or `security-analyst` weekly — must open the
panel and click Invoke every time. There is no way to say "run this agent on this
repo every Monday at 4am" and walk away. For a personal control plane whose whole
point is low-friction operation of a small agent fleet across ~20 repos, manual-only
invocation is a recurring chore and an easy thing to forget.

Two secondary problems compound this once execution becomes unattended:

1. **No one is watching when an unattended run happens.** A manual run is observed by
   the operator who triggered it; a scheduled run at 4am is not. Failures,
   auto-opened PRs, and misbehaving schedules can go unnoticed. The system needs to
   **tell the operator** what happened.
2. **An unattended loop can misbehave at scale.** Without guardrails, a daily
   fix-mode schedule can open a new PR every day on top of an unreviewed one; a
   schedule pointed at a broken runtime can fail every minute forever; a burst of
   simultaneously-due schedules can fan out into many concurrent (costly) AgentCore
   invocations. Unattended automation must be **safe by default**.

## 3. Goals

1. **Configurable recurring invocation.** An operator can create a schedule binding an
   agent + repository + validated params to a recurring cadence, and the system
   invokes the agent on that cadence with no human in the loop.
2. **Human-friendly cadence, correct underneath.** The UI speaks in presets ("daily at
   7pm", "every Monday at 4am", "every N hours"), with a raw-cron escape hatch for
   power cases, and schedules fire at the correct wall-clock time in the operator's
   timezone across DST boundaries.
3. **Safe unattended execution.** Guardrails prevent run stacking (overlap + open-PR
   backoff), prevent infinite failure loops (auto-pause circuit breaker), and bound
   concurrent fan-out (global in-flight cap). Every skip/block/pause is **recorded with
   a visible reason**, never silent (upholds `technical-guidelines.md` §10
   "explicitness over inference").
4. **Notifications the operator actually sees.** Notable scheduled-run events are
   recorded in a durable, channel-agnostic `notifications` table (the system of
   record), surfaced in an in-panel feed in real-ish time and delivered as a once-a-day
   SES email digest — never one email per run.
5. **Zero per-agent scheduler code.** A new agent is schedulable the moment its row
   exists in `agents` (its `params_schema` drives the schedule's param form), the same
   way manual invocation needs no per-agent front-end work (v1 acceptance criterion #5,
   `product-context.md` §7).
6. **No new orchestration infrastructure and no static credentials.** Scheduling runs
   on the deployed `pg_cron`; execution and email reuse the Fly OIDC → STS credential
   path (no static AWS keys, D12); the login boundary (ADR-007) is preserved for all
   human surfaces.

## 4. Non-Goals (v1)

- **Automatic GitHub PR-state polling (G5-b).** v1 blocks a schedule when a prior run
  left an unresolved PR and lets the operator clear the block manually; it does **not**
  automatically detect that the PR was merged/closed on GitHub. Automatic polling is a
  documented fast-follow (§11) because it requires GitHub-App integration **on the
  panel**, which the panel does not have today (only *agents* mint installation tokens).
- **Slack / other notification channels.** The `notifications` table is channel-agnostic
  by design, but v1 ships only two consumers: the panel feed and the daily SES digest.
  Slack is an explicitly planned fast-follow (§11).
- **Webhook triggers.** The `trigger_type` enum includes `webhook`; event-driven
  triggering is a separate backlog item (`product-context.md` §6) and is out of scope.
- **Per-repository agent enablement.** Enabling/disabling an agent per repository is a
  separate backlog item; a schedule simply references an existing enabled agent + repo.
- **Per-successful-run notifications or an all-runs activity report.** The digest
  summarizes **notable events only**; the system does not write a notification row per
  successful run.
- **Multiple recipients / per-schedule recipient lists.** v1 has a single configured
  sender and recipient (single-tenant, `product-context.md` §3).
- **Run cancellation of a scheduled run.** The panel still cannot kill a running
  AgentCore container (`product-context.md` §9); schedules can be paused/deleted, which
  stops *future* firings, not an in-flight run.

## 5. Target Users

The project author / operator (single-tenant, `product-context.md` §3/§10). The
scheduler is operated through the authenticated panel; its notifications are addressed
to the single configured operator email.

## 6. User Stories (narrative)

- *As the operator,* I create a schedule that runs `dependency-update` on
  `llipe/memo-cli` in `audit_only` mode **every day at 08:00 my time**, so I get a
  fresh audit each morning without touching the panel.
- *As the operator,* I create a schedule that runs `security-analyst` on a repo
  **every Monday at 04:00**, and because 90-minute scans can overlap, I trust that a
  still-running scan is **not** double-fired.
- *As the operator,* when a scheduled `fix`-mode run opens a PR, I want the schedule to
  **stop re-firing** until I've merged or discarded that PR, so I don't wake up to five
  stacked dependency PRs.
- *As the operator,* when a schedule's runs keep failing, I want it **auto-paused** and
  to be **told**, rather than discovering weeks later that it has been failing every day.
- *As the operator,* I want a **single morning email** summarizing everything notable
  that happened overnight (failures, auto-pauses, PRs opened), not an inbox full of
  per-run mail — and I want the **full detail in the panel** whenever I open it.
- *As the operator,* I want to **pause, resume, edit, and delete** schedules from one
  place, and see which agents have schedules attached.

## 7. Functional Requirements

### 7.1 Scheduling & cadence

- **FR1.** The system SHALL store schedules in a `schedules` table. A schedule binds:
  an agent, a repository (when the agent `requires_repository`), a set of params
  validated against the agent's `params_schema`, a structured cadence spec, a
  timezone, an enabled/paused state, and bookkeeping for the guardrails and
  notifications.
- **FR2.** The cadence spec SHALL be a **structured** value (the source of truth), not
  a raw cron string. Supported preset kinds: `hourly`, `daily` (at `HH:MM`), `weekly`
  (on a weekday at `HH:MM`), `every_n_hours` (N configurable), plus an `advanced` kind
  carrying a raw 5-field cron expression. The panel derives the human label and the
  firing times from the structured spec.
- **FR3.** Each schedule SHALL carry a **timezone** (IANA, e.g. `America/Santiago`),
  defaulting to the operator's configured local timezone. Due-ness SHALL be evaluated
  in that timezone so a preset like "daily at 07:00" fires at 07:00 local **including
  across DST transitions** — a single static cron string is insufficient and MUST NOT
  be the stored source of truth for preset kinds.
- **FR4.** A single `pg_cron` job running every minute (`* * * * *`, mirroring the
  reaper pattern) SHALL evaluate all enabled, non-paused schedules for due-ness and
  trigger firing for those that are due and not blocked by a guardrail.

### 7.2 Trigger architecture (A1)

- **FR5.** For each schedule that is due and clear of guardrails, the `pg_cron` job
  SHALL make an HTTP request via the `pg_net` extension to an internal panel endpoint
  `POST /api/internal/schedules/{id}/fire`. Postgres decides *when*; the panel performs
  the invocation (it is the only component holding AWS credentials).
- **FR6.** The fire endpoint SHALL reuse the **existing manual-invocation path** —
  resolve agent/repository, Ajv-validate params against `params_schema`, generate the
  `run_id`, insert the `queued` run (D1), then `InvokeAgentRuntime` over the Fly OIDC
  credential path — so a scheduled invocation that never starts is a visible
  `failed_to_start` row, identical to a manual one.
- **FR7.** Runs produced by a schedule SHALL carry `trigger_type = 'schedule'` and
  `triggered_by = 'schedule:<schedule_id>'`. This requires parameterizing the current
  `buildRunInsert`, which hardcodes `manual`/`panel`.
- **FR8.** The `/api/internal/**` route class SHALL authenticate via a shared secret
  (`SCHEDULER_TRIGGER_SECRET`) sent as a request header, compared in **constant time**,
  **fail-closed** (missing/wrong/unreadable secret → `401`, never a fallthrough to a
  successful response). The secret SHALL be stored in Supabase Vault (Postgres side)
  and `fly secrets` (panel side), and MUST NOT be logged. This route class is **neither**
  the `ui` (302-redirect) **nor** the session-gated `api` class; it bypasses the session
  check (the caller is Postgres, not a logged-in human) but is never public.

### 7.3 Guardrails

- **FR9 (G1 — overlap suppression).** A schedule SHALL NOT fire if a prior run for the
  **same (agent, repository)** is still non-terminal, evaluated by `effective_status`
  (so a stale `running` run that the reaper will mark `timed_out` does not block
  forever). A suppressed firing SHALL record a visible skip reason.
- **FR10 (G2 — missed-tick).** If a schedule's due time passed without firing (panel or
  `pg_net` unavailable), the system SHALL **not** catch up the missed occurrence; it
  SHALL skip to the next scheduled time and record the miss. No backlog of unattended
  runs is replayed.
- **FR11 (G3 — circuit breaker).** A schedule SHALL be **auto-paused** after N
  consecutive **failed firings** (default N = 3, configurable per schedule), set to a
  `paused` state carrying the reason, surfaced in the UI, and recorded as a notification
  event. A "failed firing" counts a run that reached a terminal failure
  (`failed`/`failed_to_start`/`timed_out`) or an invocation that errored at the fire
  endpoint. A successful firing resets the consecutive-failure counter.
- **FR12 (G4 — concurrency cap).** The system SHALL enforce a **global cap** on the
  number of scheduled runs in-flight (non-terminal) at once (default K = 3,
  configurable). When more schedules are due than the cap allows, the excess SHALL be
  **skipped this tick** (not queued) with a recorded reason, and re-evaluated on the
  next tick.
- **FR13 (G5 — open-PR backoff).** A schedule SHALL NOT fire while a prior run of the
  **same (agent, repository)** has produced a `pull_request` artifact that is still
  **unresolved**. In v1, "resolved" is determined by:
  - **FR13a (G5-c).** The operator manually clears the block from the panel ("PR
    handled — resume schedule").
  - **FR13b (G5-a).** A later **manual** run of the same (agent, repository) supersedes
    the block (the operator has evidently moved on).
  - v1 does **not** automatically detect PR merge/close on GitHub (that is FR-FF1, §11).
- **FR14 (unified blocked/skipped state).** G1 overlap and G5 open-PR backoff SHALL be
  modeled as reasons under **one** "blocked / skipped — here's why" mechanism, so the
  UI shows a single clear reason a schedule did not fire. G2 miss and G4 cap-skip are
  additional reasons under the same mechanism.

### 7.4 Notifications

- **FR15 (table is the system of record).** The system SHALL record every **notable**
  scheduled-run event as a row in a `notifications` table carrying full detail: event
  type, schedule id, agent, repository, associated `run_id` (when applicable), status
  or reason, timestamp, a read marker, and a digest-delivery marker. The table is the
  durable truth; delivery channels are consumers of it.
- **FR16 (notable event set).** The following events SHALL be recorded, with the stated
  default policy:
  - scheduled-run terminal failure (`failed` / `failed_to_start` / `timed_out`) — always;
  - schedule auto-paused by G3 — always;
  - scheduled run opened a PR (`pull_request` artifact created) — always;
  - scheduled run succeeded — **opt-in per schedule** (off by default).
  The system SHALL NOT write a notification row per successful run unless that
  schedule's success-notification opt-in is enabled.
- **FR17 (durable recording).** Notification rows SHALL be written such that recording
  does **not** depend on the panel having observed the state transition. Terminal
  failures materialized by the reaper (inside Postgres) SHALL still produce a
  notification via a `pg_cron` notify-sweep tick that finds newly-terminal scheduled
  runs not yet notified and records them (and/or calls a shared-secret panel notify
  endpoint). Each notable event SHALL be recorded **exactly once** (idempotent marker).
- **FR18 (panel feed — channel 1).** The panel SHALL present an in-app notifications
  feed reading the `notifications` table, newest-first, with an unread indicator and a
  mark-as-read affordance. This is net-new UI (**DESIGN.md impact**).
- **FR19 (daily email digest — channel 2).** The system SHALL send **one** SES email per
  day summarizing the window's notable notifications, at a configurable hour (default
  08:00 in the operator timezone), triggered by a daily `pg_cron` tick calling a
  shared-secret internal endpoint (`POST /api/internal/notifications/digest`). The
  digest SHALL be sent panel-side over the Fly OIDC → STS credential path (SES
  permission added to the IAM role; no static keys). If the window contains **zero**
  notable notifications, **no email SHALL be sent** (no empty "all quiet" mail). Each
  notification row SHALL be included in **exactly one** digest (delivery marker).
- **FR20 (channel-agnostic extensibility).** Adding a future channel (Slack, FR-FF2)
  SHALL require only a new consumer of the `notifications` table, with **no change** to
  how notifications are recorded.
- **FR21 (sender/recipient config).** The SES sender address (`NOTIFICATION_SENDER`,
  verified in SES) and the single recipient (`NOTIFICATION_RECIPIENT`) SHALL be
  configured via secrets, not per-schedule.

### 7.5 Management UI & boundary (S1/S2/S3)

- **FR22 (fleet-wide CRUD surface).** The panel SHALL provide a fleet-wide `/schedules`
  surface (flipping one of the currently-disabled sidebar nav items to a live link)
  listing all schedules across agents and supporting **create, edit, pause, resume, and
  delete**. This is net-new UI (**DESIGN.md impact — new screen spec + nav-state
  change**).
- **FR23 (per-agent indicator).** The `/agents/[slug]` screen SHALL surface a read-only
  indicator that the agent has one or more schedules attached (and a link to manage
  them).
- **FR24 (schema-driven schedule form).** Schedule create/edit SHALL reuse the existing
  `params_schema`-driven form and Ajv validation used by manual invoke, extended with a
  **cadence/timezone picker** (the preset builder + advanced-cron option). A schedule's
  params SHALL be validated against `agents.params_schema` at save time, exactly like a
  manual invoke. A new agent SHALL be schedulable with no scheduler-specific code (Goal 5).
- **FR25 (auth boundary split).** Schedule CRUD endpoints SHALL be ordinary authenticated
  routes behind the ADR-007 login boundary (`ui`/`api` classes). **Only** the
  Postgres-triggered fire/notify/digest endpoints (`/api/internal/**`) SHALL use the
  shared-secret class. No human-facing schedule operation SHALL be reachable without
  login.
- **FR26 (release-gate assertion).** The auth release gate
  (`panel-auth-check.mjs` / `verify-panel-auth.sh`) SHALL gain a check that an
  unauthenticated or wrong-secret request to an `/api/internal/**` endpoint is
  **rejected** (`401`), mechanically asserting that the scheduler path is not an open
  invoke hole — the same way the gate asserts SSE returns `401`.

## 8. Acceptance Criteria

- **AC1.** A schedule created as "daily at 07:00 `America/Santiago`" fires exactly once
  per day at 07:00 local, verified across a DST transition (fires at 07:00 local both
  sides, i.e. the underlying UTC instant shifts).
- **AC2.** A scheduled firing produces a `runs` row with `trigger_type='schedule'` and
  `triggered_by='schedule:<id>'`, created via the same insert-then-invoke path as a
  manual run (an invocation that never starts shows `failed_to_start`, not stuck
  `queued`).
- **AC3.** An unauthenticated request to `POST /api/internal/schedules/{id}/fire`
  returns `401`; a request with a wrong secret returns `401`; only a correct-secret
  request fires. The secret never appears in logs. The release gate asserts this.
- **AC4 (G1).** While a prior run for the same (agent, repository) is non-terminal (by
  `effective_status`), the next due firing is skipped with a recorded reason, and
  resumes once that run reaches a terminal state.
- **AC5 (G2).** A due time that passes while the fire path is unavailable does not
  produce a catch-up run when the path recovers; the miss is recorded and the schedule
  proceeds at its next due time.
- **AC6 (G3).** After 3 consecutive failed firings, the schedule flips to `paused` with
  a reason, stops firing, and a notification row is recorded; a manual resume clears it,
  and one subsequent success resets the counter.
- **AC7 (G4).** With the cap at K=3 and 5 schedules simultaneously due, exactly 3 fire
  this tick and 2 are skipped with a recorded reason; the skipped ones are re-evaluated
  next tick.
- **AC8 (G5).** After a scheduled run opens a PR, subsequent due firings of that
  (agent, repository) schedule are blocked with a visible reason until the operator
  clears the block (or a later manual run supersedes it); then firing resumes.
- **AC9 (notifications table).** A scheduled-run terminal failure, a G3 auto-pause, and
  a PR-opened event each produce exactly one `notifications` row with full detail; a
  successful run produces a row **only** when that schedule's success opt-in is on.
- **AC10 (reaper-materialized failure still notifies).** A scheduled run marked
  `timed_out` by the reaper (no panel involvement) still produces exactly one
  notification row via the notify-sweep tick.
- **AC11 (panel feed).** The notifications feed renders the table newest-first with an
  unread indicator and mark-as-read, reading server-side (SD2 preserved, RLS deny-all).
- **AC12 (daily digest).** On a day with notable events, exactly one SES email is sent at
  the configured hour summarizing them, and each included row is marked delivered so it
  is not re-sent; on a day with zero notable events, no email is sent.
- **AC13 (schema-driven form).** Creating a schedule for each existing agent renders the
  correct param form from that agent's `params_schema`, validates params with Ajv at
  save time, and requires no agent-specific scheduler code.
- **AC14 (CRUD behind login).** Every schedule CRUD operation redirects to `/login`
  (UI) or returns `401` (API) when unauthenticated; only the `/api/internal/**` fire,
  notify, and digest endpoints use the shared secret instead.
- **AC15 (no static keys).** The deployed scheduler fires agents and sends email with no
  static AWS keys in `fly secrets` (OIDC → STS for both `InvokeAgentRuntime` and
  `ses:SendEmail`), consistent with D12/AC8 of the panel.

## 9. Dependencies & Touchpoints

- **Enabled extensions:** `pg_cron` (already enabled for the reaper), **`pg_net`**
  (new — for the Postgres→panel HTTP call), **Supabase Vault** (new — for
  `SCHEDULER_TRIGGER_SECRET`).
- **New migrations:** `schedules` table, `notifications` table, the scheduler `pg_cron`
  jobs (due-evaluation tick, notify-sweep tick, daily-digest tick), and any supporting
  indexes/view.
- **Code refactor:** parameterize `panel/lib/domain/run-insert.ts` `buildRunInsert`
  (currently hardcodes `trigger_type:'manual'` / `triggered_by:'panel'`).
- **New panel surfaces:** `/schedules` CRUD screens + feed; `/api/internal/schedules/[id]/fire`,
  `/api/internal/notifications/digest` (and any notify endpoint); middleware
  `/api/internal/**` route class; a server-side SES sender module reusing
  `panel/lib/aws/credentials.ts`.
- **New dependency:** `@aws-sdk/client-ses` in `panel/package.json` (pinned, audit-clean).
- **IAM:** the panel's AgentCore role gains `ses:SendEmail` scoped to the verified
  sender identity (never `*`).
- **New secrets:** `SCHEDULER_TRIGGER_SECRET`, `NOTIFICATION_SENDER`,
  `NOTIFICATION_RECIPIENT` (+ Vault copy of the trigger secret).
- **DESIGN.md:** new `/schedules` screen spec, the notifications feed, the cadence/timezone
  picker, and the sidebar nav-state change (a disabled item flips live).
- **Operator runbook:** a deploy/verification runbook is required in the same PR as the
  new `pg_cron` jobs and the SES/IAM change (per `AGENTS.md` FR-49a) — enabling `pg_net`
  + Vault, setting the secrets, SES sender verification, and the scheduler/digest
  verification procedure.

## 10. Risks & Mitigations

| Risk | Mitigation |
| --- | --- |
| **R-S1 — `/api/internal/**` is an invoke hole if the secret leaks or the gate regresses.** | Shared secret, constant-time compare, fail-closed, never logged (FR8); release-gate assertion (FR26); secret in Vault + `fly secrets`, rotatable. |
| **R-S2 — `pg_net` call fails silently; schedules never fire.** | The due-tick records a fire attempt and its HTTP outcome; a schedule that never fires is visible (last-fired / last-error columns). Firing is best-effort per tick and retried next minute (no backlog, G2). |
| **R-S3 — DST / timezone math is wrong; runs fire at the wrong hour.** | Structured cadence + per-schedule timezone evaluated per-tick in plpgsql (FR3), not a static cron string; AC1 verifies across a DST boundary. |
| **R-S4 — Unattended fix-mode schedule stacks redundant PRs.** | G5 open-PR backoff (FR13); G1 overlap suppression (FR9). |
| **R-S5 — Broken schedule fires and fails forever.** | G3 circuit breaker auto-pause (FR11). |
| **R-S6 — Burst of due schedules fans out into costly concurrent invocations.** | G4 global in-flight cap (FR12). |
| **R-S7 — Notification spam.** | Table-first recording + daily digest, not per-event email (FR19); notable-events-only (FR16); empty-window digests suppressed. |
| **R-S8 — G5 manual-clear is forgotten; a schedule stays blocked indefinitely.** | Accepted v1 trade-off (degrades to "schedule waits for the operator"); the block is visible in the UI and the open PR is itself a notification. Full automation is FR-FF1. |
| **R-S9 — SES send fails; digest lost.** | Delivery marker is set only on confirmed send, so a failed digest tick retries the same rows next day rather than dropping them; failures logged (no secret/content leak). |

## 11. Open Questions & Fast-Follows

- **FR-FF1 (fast-follow) — Automatic GitHub PR-state polling (G5-b).** Replace the
  manual G5 clear with automatic detection of PR merge/close via the GitHub App. Requires
  bringing GitHub-App installation-token handling **onto the panel** (today only agents
  hold it). Tracked as the planned upgrade path for FR13.
- **FR-FF2 (fast-follow) — Slack (and other) notification channels.** A new consumer of
  the `notifications` table; no change to recording (FR20).
- **OQ1 — G4 cap and G3 threshold defaults.** K=3 / N=3 are starting defaults; both are
  configurable. Revisit once real scheduled volume is observed.
- **OQ2 — Digest timezone source.** v1 uses a single operator timezone (default
  `America/Santiago`) for both schedule defaults and the digest hour. If per-schedule
  timezones diverge widely, revisit whether the digest hour should be independently
  configurable (it already is a separate setting; this is about defaults).
- **OQ3 — Schedule history / audit.** v1 keeps last-fired / last-skip-reason bookkeeping
  on the `schedules` row. Whether to add a full per-firing audit log (beyond the `runs`
  the schedule produces and the `notifications` it emits) is deferred — the `runs` table
  with `trigger_type='schedule'` + `triggered_by='schedule:<id>'` already provides the
  firing history.
- **OQ4 — `notifications` retention.** Like `run_events` (R3), the `notifications` table
  grows unbounded. v1 does not set a retention policy; revisit alongside the `run_events`
  retention question.

## 12. Delivery Note

This PRD proceeds to a technical specification (`activity-generate-spec`), which must
settle the HOW-level details grounded in the current code: the exact `schedules` /
`notifications` schema and indexes, the plpgsql due-evaluation + DST algorithm, the
`pg_net` call shape and secret handling, the `buildRunInsert` parameterization, the SES
sender module and IAM change, the middleware route-class change, the DESIGN.md screen
specs, and the test strategy (including Layer 2.5 integration tests against the local
Supabase stack for the `pg_cron` ticks and guardrail logic, mirroring the reaper's
integration-test precedent).
