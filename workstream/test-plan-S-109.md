# Compliance Test Plan — S-109 Run Detail (Issue #122)

> **Agent:** `verifier` · **Mode:** Design · **Phase:** Test Design (Phase 3)
> **Source artifact:** [`workstream/user-stories-prd-agent-fleet-panel-v2.md`](user-stories-prd-agent-fleet-panel-v2.md) → Story **S-109** · Input type: `story`
> **Companion artifact:** [`workstream/traceability-matrix-S-109.md`](traceability-matrix-S-109.md)
> **Repository:** `llipe/dev-tasks-agent-fleet` · **Issue:** [#122](https://github.com/llipe/dev-tasks-agent-fleet/issues/122)
> **Scope:** read-only Next.js screen at `/runs/[id]` — no schema/data/API change (documented migration opt-out).
> **Status:** `covered` — every AC maps to ≥1 positive and ≥1 negative/edge scenario. **Two mandatory security-negative categories are present (SEC-5 URL scheme, SEC-6 inert render).**

---

## 1. Source Input Summary

S-109 delivers the static half of **FR12** plus **AC14**: a single read-only page that shows everything a run
did — status, timings, artifacts, and its full log — so an operator can diagnose without opening the AWS console.

Grounding read directly from the repository during design:

- Data layer already exists (S-104): `getRunById`, `getRunSteps`, `getRunEvents` (paged, honors SD11 2,000-cap
  under PostgREST `max_rows=1000`), `getRunArtifacts` in `panel/lib/supabase/queries.ts`;
  `RUN_EVENTS_READ_LIMIT = 2000` confirmed. Runs are read through `v_runs`, so `effective_status` (SD4) is present.
- `effectiveStatus` TS mirror of `v_runs.effective_status` exists in `panel/lib/domain/status.ts`.
- DESIGN grounding: §4.2 (full-height, no outer scroll layout), §5.3 (Run Detail spec), §7.5 (log word-wrap, never
  truncate), §8.1 (status→visual), §8.3 (terminal-state banners for `timed_out` / `failed_to_start`).
- Security context: agent-authored `run_events.message` and `run_artifacts.url` are **untrusted input**
  (spec §12, A10 SSRF/XSS). This drives the two mandatory security-negative categories.

### Testing approach

Black-box, behavior-first. All assertions are on observable output (rendered DOM, HTTP status, link presence/scheme,
returned row shapes) — never on internal call structure. Because S-109 is a server-rendered read-only screen with a
pure domain layer, the compliance surface is:

- **Layer 1 (unit):** pure domain modules — `artifact-url.ts` (SEC-5), `log-window.ts` (SD11 windowing), banner selection.
- **Layer 2 (component):** rendered summary / artifacts / log viewer / banner, incl. SEC-6 inert render and `aria-live`.
- **Layer 2.5 (integration, Docker-gated):** seeded run against local Supabase; 2,500-event bounded read.
- **Manual/UI:** read-only comparison against `docs/prototype/`, full-height scroll behavior, SD11 sizing note.

---

## 2. Acceptance Criteria Extraction

Numbered from the story's Acceptance Criteria list. **AC-3** carries the highlighted **AC14** obligation
(artifacts surface on `failed` runs) as an inseparable sub-clause, tracked as **AC-3/AC14**.

| ID          | Acceptance Criterion (observable behavior)                                                                                                                   |
| ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **AC-1**    | `/runs/[id]` renders full-height with no outer scroll; the log region owns the scroll (DESIGN §4.2).                                                          |
| **AC-2**    | Summary shows status pill (from `effective_status`), outcome tag, run ID (short uppercase mono), repository, and metadata grid (queued/started/finished/duration/branch). |
| **AC-3**    | `run_artifacts` render as pill links, **including on `failed` runs (AC14)**, with `rel="noopener noreferrer"`, and only when the URL scheme is `https:`.      |
| **AC-4**    | Log viewer renders `run_events` as a 4-column grid (time/level/step/message) ordered by `seq`, with level coloring and hover highlight; step names label lines via `run_steps`. |
| **AC-5**    | Initial fetch is bounded at the most recent 2,000 events (SD11); if earlier events exist, a "load earlier" control fetches the prior window.                  |
| **AC-6**    | Terminal-state banners render for `timed_out` and `failed_to_start` (DESIGN §8.3), carrying the reaper's explanatory event text.                              |
| **AC-7**    | Log messages render as inert text — never `dangerouslySetInnerHTML`; HTML or script content in a message displays literally.                                 |
| **AC-8**    | The log region is `aria-live="polite"` so appended lines are announced.                                                                                       |
| **AC-9**    | Unknown run id renders a 404.                                                                                                                                  |

### Business rules & constraints (design inputs, not separately numbered)

- **BR-1** Agent-authored `message` and `run_artifacts.url` are untrusted (spec §12, A10). Scheme validation before linking is mandatory. → SEC-5, SEC-6.
- **BR-2** Steps *panel* deferred to v3; `run_steps` read only to label log lines.
- **BR-3** Virtualization deferred to v3. The 2,000 bound is a bound, not a capacity estimate.
- **BR-4** Message column is `pre-wrap` + `word-break: break-word`, never truncated (DESIGN §7.5).
- **BR-5** Query newest 2,000 by `seq desc`, then reverse for display — the bound is on the recent end.
- **BR-6** `force-dynamic`; no caching of run data (a run's derived status changes second-to-second).
- **BR-7** Keep a stable SSE mount point in the markup so S-110 (#123) attaches without restructuring.

### Non-goals (explicitly out of scope for S-109)

- SSE / live tail (S-110). Steps panel (v3). Log virtualization (v3). Filters/search/pagination on log (v3).
- 1024px pixel-geometry Playwright check (S-114 — jsdom computes no geometry).

---

## 3. E2E / Black-Box Scenarios

> Severity reflects business impact: `critical` = security or core-diagnosis failure; `major` = a stated AC is
> observably wrong; `minor` = cosmetic/degradation.

### SC-1: Render run detail for a succeeded run (full-height, no outer scroll)

| Field               | Value                                                                                                       |
| ------------------- | ----------------------------------------------------------------------------------------------------------- |
| **AC(s)**           | AC-1, AC-2                                                                                                   |
| **Type**            | happy-path                                                                                                  |
| **Severity**        | critical                                                                                                    |
| **Preconditions**   | A `succeeded` run exists with `outcome`, repository, timings, and ≥1 event.                                  |
| **Steps**           | 1. Navigate to `/runs/{id}`. 2. Observe layout and summary panel.                                            |
| **Expected Result** | Page fills content area; the log region scrolls, the page itself does not. Summary shows the green status pill (from `effective_status`), outcome tag, short uppercase mono run ID, repository, and the metadata grid. |
| **Pass Criteria**   | HTTP 200. No outer/body scrollbar; log region is the scroll owner (`overflow-y:auto`). All summary fields present with correct values. |

### SC-2: Summary status derives from `effective_status`, not raw `runs.status`

| Field               | Value                                                                                                       |
| ------------------- | ----------------------------------------------------------------------------------------------------------- |
| **AC(s)**           | AC-2                                                                                                        |
| **Type**            | negative-path                                                                                               |
| **Severity**        | critical                                                                                                    |
| **Preconditions**   | A run whose raw `status = 'running'` but is past its timeout threshold, so `v_runs.effective_status = 'timed_out'`. |
| **Steps**           | 1. Navigate to `/runs/{id}`. 2. Read the status pill.                                                        |
| **Expected Result** | Pill reads `timed_out` (amber), never `running` — the derived status wins (SD4).                             |
| **Pass Criteria**   | Pill reflects `effective_status`; a stale `running` is never displayed for a timed-out run.                  |

### SC-3: Metadata grid on a run with no repository and null `finished_at`

| Field               | Value                                                                                                       |
| ------------------- | ----------------------------------------------------------------------------------------------------------- |
| **AC(s)**           | AC-2                                                                                                        |
| **Type**            | edge-case                                                                                                   |
| **Preconditions**   | A terminal run with `repository_full_name = null` and `finished_at = null`.                                 |
| **Steps**           | 1. Navigate to `/runs/{id}`. 2. Inspect the repository and finished/duration cells.                          |
| **Expected Result** | Repository cell renders a neutral placeholder (no crash, no "null"); finished/duration render a dash rather than `NaN`. |
| **Pass Criteria**   | No thrown error; no literal `null`/`NaN`/`Invalid Date` in the DOM.                                          |

### SC-4: Artifact pill links render with safe scheme and hardened rel

| Field               | Value                                                                                                       |
| ------------------- | ----------------------------------------------------------------------------------------------------------- |
| **AC(s)**           | AC-3                                                                                                        |
| **Type**            | happy-path                                                                                                  |
| **Preconditions**   | A run with a `pull_request` artifact whose `url` is `https://github.com/...`.                                |
| **Steps**           | 1. Navigate to `/runs/{id}`. 2. Inspect the artifact pill.                                                   |
| **Expected Result** | Pill renders as an anchor to the `https:` URL with `rel="noopener noreferrer"`.                              |
| **Pass Criteria**   | `<a href="https://...">` present; `rel` contains both `noopener` and `noreferrer`; `target` does not leak an unhardened reference. |

### SC-5: Artifact link surfaces on a FAILED run (AC14 — the highlighted risk)

| Field               | Value                                                                                                       |
| ------------------- | ----------------------------------------------------------------------------------------------------------- |
| **AC(s)**           | AC-3 / **AC14**                                                                                              |
| **Type**            | happy-path (high-risk-of-omission)                                                                          |
| **Severity**        | critical                                                                                                    |
| **Preconditions**   | A run with `effective_status = 'failed'` that nonetheless carries a `pull_request` artifact.                 |
| **Steps**           | 1. Navigate to `/runs/{id}`. 2. Confirm the red status pill. 3. Confirm the artifact pill is present.        |
| **Expected Result** | The artifact link appears **alongside the red `failed` pill**, not hidden behind the failure state.          |
| **Pass Criteria**   | The `pull_request` anchor is present and clickable on a `failed` run. This is the criterion most likely to be missed. |

### SC-6: Log viewer 4-column grid ordered by `seq`, step-labeled, level-colored

| Field               | Value                                                                                                       |
| ------------------- | ----------------------------------------------------------------------------------------------------------- |
| **AC(s)**           | AC-4                                                                                                        |
| **Type**            | happy-path                                                                                                  |
| **Preconditions**   | A run with events at varied levels (`debug`/`info`/`error`), some carrying `step_id`, inserted out of `seq` order. |
| **Steps**           | 1. Navigate to `/runs/{id}`. 2. Inspect the log rows and columns.                                            |
| **Expected Result** | Four columns (time/level/step/message); rows are ordered by `seq` ascending regardless of arrival order; each level has its color; lines with a `step_id` show the step name from `run_steps`. |
| **Pass Criteria**   | DOM order matches `seq` ascending; level classes applied; step-labeled rows show the resolved step name.     |

### SC-7: Log message with a null `step_id`

| Field               | Value                                                                                                       |
| ------------------- | ----------------------------------------------------------------------------------------------------------- |
| **AC(s)**           | AC-4                                                                                                        |
| **Type**            | edge-case                                                                                                   |
| **Preconditions**   | A run with an event whose `step_id` is null.                                                                 |
| **Steps**           | 1. Navigate to `/runs/{id}`. 2. Inspect the step column of that row.                                         |
| **Expected Result** | Step column is empty/neutral; no crash, no "undefined".                                                      |
| **Pass Criteria**   | Row renders; step cell is blank; no thrown error.                                                            |

### SC-8: Initial fetch bounded at most-recent 2,000 (SD11)

| Field               | Value                                                                                                       |
| ------------------- | ----------------------------------------------------------------------------------------------------------- |
| **AC(s)**           | AC-5                                                                                                        |
| **Type**            | happy-path                                                                                                  |
| **Preconditions**   | A run with exactly 2,500 events.                                                                             |
| **Steps**           | 1. Load `/runs/{id}`. 2. Count rendered log rows in the initial window.                                      |
| **Expected Result** | Exactly the most-recent 2,000 events render, in `seq` order (queried `seq desc`, reversed for display).      |
| **Pass Criteria**   | Initial window = 2,000 rows; they are the newest 2,000 by `seq`; a "load earlier" control is present because earlier events exist. |

### SC-9: "Load earlier" fetches the prior window without gaps or duplicates

| Field               | Value                                                                                                       |
| ------------------- | ----------------------------------------------------------------------------------------------------------- |
| **AC(s)**           | AC-5                                                                                                        |
| **Type**            | happy-path                                                                                                  |
| **Preconditions**   | The 2,500-event run from SC-8, initial window rendered.                                                      |
| **Steps**           | 1. Activate "load earlier". 2. Inspect the newly prepended rows.                                             |
| **Expected Result** | The prior 500 events (seq 1–500) are prepended in `seq` order; no event appears twice; no `seq` gap at the boundary. |
| **Pass Criteria**   | Union of windows is contiguous by `seq`, no duplicate `seq`, no missing `seq` at the join.                   |

### SC-10: Terminal-state banner for `timed_out` carries reaper explanatory text

| Field               | Value                                                                                                       |
| ------------------- | ----------------------------------------------------------------------------------------------------------- |
| **AC(s)**           | AC-6                                                                                                        |
| **Type**            | happy-path                                                                                                  |
| **Preconditions**   | A `timed_out` run whose reaper `run_event` carries the explanatory `data.reason` / message.                 |
| **Steps**           | 1. Navigate to `/runs/{id}`. 2. Observe the banner above the log viewer.                                     |
| **Expected Result** | A §8.3 banner (amber border/tint) is shown above the log viewer with the reaper's explanatory text.          |
| **Pass Criteria**   | Banner present for `timed_out`; contains the explanatory text; positioned above the log region.              |

### SC-11: `failed_to_start` run with no steps and no events (banner only)

| Field               | Value                                                                                                       |
| ------------------- | ----------------------------------------------------------------------------------------------------------- |
| **AC(s)**           | AC-6, AC-4                                                                                                  |
| **Type**            | edge-case                                                                                                   |
| **Preconditions**   | A `failed_to_start` run with zero `run_steps` and zero `run_events`.                                         |
| **Steps**           | 1. Navigate to `/runs/{id}`. 2. Observe banner and empty log region.                                         |
| **Expected Result** | The `failed_to_start` banner renders with reaper text; the log region renders an empty (non-broken) state; no crash. |
| **Pass Criteria**   | Banner present; empty log region handled gracefully; no thrown error on zero events/steps.                   |

### SC-12: A run that is NOT terminal shows no banner

| Field               | Value                                                                                                       |
| ------------------- | ----------------------------------------------------------------------------------------------------------- |
| **AC(s)**           | AC-6                                                                                                        |
| **Type**            | negative-path                                                                                               |
| **Preconditions**   | A `running` or `succeeded` run.                                                                             |
| **Steps**           | 1. Navigate to `/runs/{id}`. 2. Confirm no terminal-state banner is present.                                 |
| **Expected Result** | No `timed_out` / `failed_to_start` banner is rendered.                                                       |
| **Pass Criteria**   | Banner absent for non-`timed_out`/non-`failed_to_start` statuses (banner selection is exact).                |

### SC-13 (SEC-6): Log message containing `<script>` renders as inert literal text

| Field               | Value                                                                                                       |
| ------------------- | ----------------------------------------------------------------------------------------------------------- |
| **AC(s)**           | AC-7 · **BR-1 (spec §12 / A10)**                                                                            |
| **Type**            | abuse-case — **MANDATORY security-negative #6**                                                             |
| **Severity**        | critical                                                                                                    |
| **Preconditions**   | A run with an event whose `message` = `<script>alert(1)</script>` and a second whose message contains `<img src=x onerror=alert(1)>`. |
| **Steps**           | 1. Navigate to `/runs/{id}`. 2. Inspect the DOM for the message cell.                                        |
| **Expected Result** | The message displays **literally** as text; no `<script>` element is created, no `onerror` handler fires, no `dangerouslySetInnerHTML` is used. |
| **Pass Criteria**   | The message text node equals the raw string; `document.querySelector('script')` finds no injected node; no JS executes; markup is escaped/inert. |

### SC-14 (SEC-5): Artifact URL with a dangerous scheme is not linked

| Field               | Value                                                                                                       |
| ------------------- | ----------------------------------------------------------------------------------------------------------- |
| **AC(s)**           | AC-3 · **BR-1 (spec §12 / A10 SSRF/XSS)**                                                                   |
| **Type**            | abuse-case — **MANDATORY security-negative #5**                                                             |
| **Severity**        | critical                                                                                                    |
| **Preconditions**   | Artifacts whose `url` values are, respectively: `javascript:alert(1)`, `data:text/html,...`, `http://x`, a relative path, empty string, whitespace-padded, and mixed-case `HTTPS:`. |
| **Steps**           | 1. Render the artifact list (component) / call `isSafeArtifactUrl` (unit) for each vector.                   |
| **Expected Result** | Only well-formed `https:` URLs become anchors. `javascript:`, `data:`, `http:`, relative, empty, and whitespace-padded values render as **inert text**, not links. Mixed-case scheme is normalized correctly. The validator returns "unsafe" rather than throwing on malformed input. |
| **Pass Criteria**   | No `<a href>` for any non-`https:` vector; no `javascript:`/`data:` URL ever reaches an `href`; validator never throws. |

### SC-15 (SEC-5 sibling): SSRF-shaped `https:` host is still linked but hardened

| Field               | Value                                                                                                       |
| ------------------- | ----------------------------------------------------------------------------------------------------------- |
| **AC(s)**           | AC-3 · BR-1                                                                                                 |
| **Type**            | abuse-case                                                                                                  |
| **Severity**        | major                                                                                                       |
| **Preconditions**   | An `https:` artifact URL pointing at an internal-looking host (e.g. `https://169.254.169.254/...`).          |
| **Steps**           | 1. Render the artifact pill.                                                                                 |
| **Expected Result** | Scope note: S-109 validates **scheme only** (per BR-1); the link renders as `https:` with `rel="noopener noreferrer"`. The panel performs no server-side fetch of artifact URLs, so no SSRF is triggered by rendering. Document that host/allowlist filtering is **not** in S-109 scope. |
| **Pass Criteria**   | Link renders (scheme is valid); no server-side fetch occurs; the scheme-only boundary is recorded so a reviewer does not mistake it for a host-allowlist gap. |

### SC-16: 8 KB message wraps without breaking layout

| Field               | Value                                                                                                       |
| ------------------- | ----------------------------------------------------------------------------------------------------------- |
| **AC(s)**           | AC-4 · BR-4 (DESIGN §7.5)                                                                                   |
| **Type**            | edge-case                                                                                                   |
| **Preconditions**   | A run with one event carrying a full 8 KB message (no whitespace break).                                     |
| **Steps**           | 1. Navigate to `/runs/{id}`. 2. Inspect the message cell.                                                    |
| **Expected Result** | Message wraps (`pre-wrap` + `word-break: break-word`); it is never truncated; the grid layout does not overflow horizontally. |
| **Pass Criteria**   | Full text present (not truncated); no horizontal grid break; wrap styles applied.                            |

### SC-17: Log region is `aria-live="polite"`

| Field               | Value                                                                                                       |
| ------------------- | ----------------------------------------------------------------------------------------------------------- |
| **AC(s)**           | AC-8                                                                                                        |
| **Type**            | happy-path                                                                                                  |
| **Preconditions**   | Any run with a log region rendered.                                                                          |
| **Steps**           | 1. Navigate to `/runs/{id}`. 2. Inspect the log region element.                                              |
| **Expected Result** | The log region carries `aria-live="polite"`.                                                                 |
| **Pass Criteria**   | Attribute `aria-live="polite"` present on the log container.                                                 |

### SC-18: Unknown run id renders 404

| Field               | Value                                                                                                       |
| ------------------- | ----------------------------------------------------------------------------------------------------------- |
| **AC(s)**           | AC-9                                                                                                        |
| **Type**            | negative-path                                                                                               |
| **Severity**        | major                                                                                                       |
| **Preconditions**   | No run exists for the requested id (`getRunById` returns null).                                              |
| **Steps**           | 1. Navigate to `/runs/{random-uuid}`.                                                                        |
| **Expected Result** | The route calls `notFound()`; a 404 is rendered.                                                             |
| **Pass Criteria**   | HTTP 404 / Next.js not-found UI; no crash, no empty summary shell.                                           |

### SC-19: Malformed / non-UUID run id in the path

| Field               | Value                                                                                                       |
| ------------------- | ----------------------------------------------------------------------------------------------------------- |
| **AC(s)**           | AC-9                                                                                                        |
| **Type**            | abuse-case                                                                                                  |
| **Severity**        | major                                                                                                       |
| **Preconditions**   | Path segment is not a valid UUID (e.g. `/runs/' OR 1=1--` or `/runs/..%2F..`).                               |
| **Steps**           | 1. Navigate with the malformed id.                                                                          |
| **Expected Result** | The read is parameterized (Supabase client), so no injection occurs; the lookup returns null → 404. No SQL/PostgREST error is surfaced to the client. |
| **Pass Criteria**   | 404 (or clean not-found); no database error leaked; no injection side effect.                                |

### SC-20: `force-dynamic` — no stale cached run data

| Field               | Value                                                                                                       |
| ------------------- | ----------------------------------------------------------------------------------------------------------- |
| **AC(s)**           | AC-2 · BR-6                                                                                                 |
| **Type**            | negative-path                                                                                               |
| **Severity**        | major                                                                                                       |
| **Preconditions**   | A run whose derived status changes between two loads (e.g. crosses the timeout threshold).                   |
| **Steps**           | 1. Load `/runs/{id}`. 2. After the threshold, reload.                                                        |
| **Expected Result** | The second load reflects the new `effective_status` — the route declares `dynamic="force-dynamic"`, `revalidate=0`, `fetchCache="force-no-store"` **inline** (Next.js ignores re-exported segment config, §12 convention). |
| **Pass Criteria**   | No stale render; segment config is inline; reload reflects current derived status.                           |

---

## 4. Contract Validation Scenarios

S-109 exposes **no new HTTP/API contract** (the SSE endpoint is S-110). The contract surface it consumes is the
**data-layer read contract** from S-104 and the **DB read shapes**. Contract checks:

| CT-ID    | Contract                                                                                                     | Check                                                                                                   |
| -------- | ----------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| **CT-1** | `getRunById` returns `VRunRow \| null` including `effective_status`.                                        | Integration: seeded run returns the view row with `effective_status` populated; absent id → `null`.     |
| **CT-2** | `getRunEvents` honors the SD11 2,000 cap under PostgREST `max_rows=1000` (paged `.range()`).                 | Integration: 2,500-event run returns exactly 2,000 rows, newest by `seq`, no silent 1,000 truncation.   |
| **CT-3** | `getRunSteps` returns `seq`-ascending `RunStepRow[]`, `[]` when none.                                        | Integration: step names resolvable for log-line labeling; empty run → `[]`, never `null`.               |
| **CT-4** | `getRunArtifacts` returns artifact rows including `pull_request` on a `failed` run.                          | Integration: failed-run-with-artifact returns the artifact (feeds AC14 / SC-5).                          |
| **CT-5** | Row shapes match `panel/lib/supabase/types.ts` (`VRunRow`, `RunStepRow`, event/artifact rows).              | Integration: no field is `undefined` where the type declares non-optional; `effective_status` is a valid `RunStatus`. |
| **CT-6** | `effectiveStatus` (TS) stays consistent with `v_runs.effective_status` (SQL) — the presentation must not re-derive differently. | Reuse S-104's parity test as evidence; S-109 asserts the summary pill reads the view column, not a local recompute. |

> **RLS note:** the panel reads server-side with `service_role` (§5/D15). No new RLS surface is added; the existing
> deny-all (D11) and the S-104 anon deny-all integration test remain the guard. S-109 introduces no browser Supabase
> client and no `NEXT_PUBLIC_*` — verified by absence (SEC bundle check inherited from S-104; re-assert if a new client module is added, which it is not).

---

## 5. Edge-Case Catalog (categorized)

| Category            | Case                                                                 | Scenario / Test        | Expected                                             |
| ------------------- | -------------------------------------------------------------------- | ---------------------- | ---------------------------------------------------- |
| **Input domain**    | Zero events                                                          | SC-11, unit log-window | Empty log region, no crash                           |
| Input domain        | Exactly 1 event                                                      | unit log-window        | Single row, no "load earlier"                        |
| Input domain        | Exactly 2,000 events                                                 | SC-8, unit log-window  | Full window, no "load earlier" (boundary)            |
| Input domain        | 2,001 / 2,500 events                                                 | SC-8/SC-9, CT-2        | 2,000 shown + "load earlier"                         |
| Input domain        | Event with null `step_id`                                            | SC-7                   | Blank step cell, no crash                            |
| Input domain        | Run with no repository                                               | SC-3                   | Neutral placeholder                                  |
| Input domain        | 8 KB single-line message                                            | SC-16                  | Wraps, never truncated, no layout break              |
| **State transition**| Non-terminal → no banner; terminal → banner                          | SC-10/11/12            | Banner selection exact by status                     |
| State transition    | Raw `running` but derived `timed_out`                                | SC-2                   | Derived status wins (SD4)                            |
| **Timing**          | `force-dynamic`, status changes between loads                        | SC-20                  | No stale cache                                       |
| Timing              | null `finished_at` on a terminal run                                 | SC-3                   | Duration dash, not `NaN`                             |
| **Failure modes**   | Unknown run id                                                       | SC-18                  | 404                                                  |
| Failure modes       | Malformed/non-UUID id (injection-shaped)                             | SC-19                  | 404, parameterized, no leak                          |
| Failure modes       | `failed_to_start` with no steps/events                               | SC-11                  | Banner only, graceful empty log                      |
| **Auth/permissions**| Server-side `service_role` read only; no browser client             | CT (RLS note)          | No `NEXT_PUBLIC_*`, no anon read                     |
| **Data boundaries** | "load earlier" window join                                           | SC-9                   | No gap, no duplicate `seq`                           |
| Data boundaries     | Mixed-case `HTTPS:` scheme                                           | SC-14                  | Normalized → linked                                  |
| **Security (SEC-5)**| `javascript:` / `data:` / `http:` / relative / empty / whitespace URL | SC-14                  | Inert text, never an `href`                          |
| **Security (SEC-6)**| `<script>` / `onerror` in message                                    | SC-13                  | Literal inert text, no execution                     |
| Security            | SSRF-shaped `https:` host                                            | SC-15                  | Scheme-only gate (documented boundary), no fetch     |

---

## 6. Randomized / Property-Based Tactics

Deterministic replay is mandatory — every randomized case **MUST** log its seed and a one-line replay command.

| RT-ID    | Property                                                                                                       | Generator / seed policy                                                                        |
| -------- | ------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| **RT-1** | `isSafeArtifactUrl` **never throws** for any string input and returns a link only for well-formed `https:`.   | Fuzz random strings + a curated dangerous-scheme corpus (`javascript:`, `data:`, `vbscript:`, `file:`, control chars, unicode-escaped colons, embedded newlines). Fixed seed; record seed + failing vector on any throw or false-positive `https:` acceptance. |
| **RT-2** | Message rendering is **inert for arbitrary bytes** — no generated message ever produces an executing node.    | Fuzz messages from an XSS payload corpus + random bytes (incl. `</script>`, nested tags, encoded entities). Assert no `<script>` node and no event-handler execution. Seed-logged. |
| **RT-3** | `log-window` selection is a **partition**: across the initial window + all "load earlier" windows, every event appears exactly once, ordering is `seq`-monotonic, and the union has no gap. | Property test over random event counts `0..3000` and random `seq` sets. Assert bijection between selected rows and source rows; seed-logged, minimized on failure. |
| **RT-4** | Banner selection is a **total function** of status: exactly one banner for `timed_out`/`failed_to_start`, none otherwise, for every `RunStatus`. | Enumerate the full `RunStatus` set (exhaustive, not random) + one unknown-future value; assert exact selection. |

**Failure triage (per verifier spec):** on a randomized failure — capture seed + input vector; re-run with the seed to
confirm deterministic reproduction; minimize to the smallest triggering vector; classify (spec gap → `product-engineer`;
implementation defect → `developer`; non-reproducing → `inconclusive`); retry budget **3**, then mark `inconclusive`.

---

## 7. Execution Checklist

Canonical `pnpm` scripts (JS/TS branch of `make validate`). Run from repo root or `panel/`.

- [ ] **Layer 1 (unit)** — `pnpm run test:unit`
  - [ ] `artifact-url.test.ts` — SEC-5 scheme matrix (SC-14) + RT-1 fuzz (no-throw, https-only)
  - [ ] `log-window.test.ts` — SD11 windowing at 0/1/2000/2001/2500 (SC-8/9) + RT-3 partition property
  - [ ] banner-selection unit — RT-4 total-function over `RunStatus`
- [ ] **Layer 2 (component)** — `pnpm run test` (jsdom)
  - [ ] summary status/outcome pairs incl. derived-status pill (SC-1/2/3)
  - [ ] **AC14** artifact pill on a `failed` run (SC-5)
  - [ ] **SEC-6** `<script>`/`onerror` inert render (SC-13) + RT-2 fuzz
  - [ ] 4-column log grid, `seq` order, step labels, level colors (SC-6/7)
  - [ ] 8 KB wrap, never truncated (SC-16)
  - [ ] terminal-state banners + non-terminal no-banner (SC-10/11/12)
  - [ ] `aria-live="polite"` on log region (SC-17)
- [ ] **Layer 2.5 (integration, Docker-gated)** — `pnpm run test:integration`
  - [ ] seeded run w/ steps + events + `pull_request` artifact returns expected shapes (CT-1/3/4/5)
  - [ ] 2,500-event run returns exactly the newest 2,000 in `seq` order (CT-2 / SC-8)
  - [ ] record `SKIPPED(<reason>)` if Docker unavailable
- [ ] **404 route** — SC-18/19 (component/route test)
- [ ] **Manual/UI** — `pnpm --filter panel dev`
  - [ ] open a real Phase 1 run (read-only), compare against `docs/prototype/`
  - [ ] confirm log region scrolls while page does not (AC1 / SC-1)
  - [ ] record observed events-per-run for the **SD11 sizing note** (BR-3)
- [ ] **Quality gates** — `pnpm run lint`, `pnpm run format:check`, `pnpm run typecheck`, `pnpm run audit`, then `make validate` (both branches)
- [ ] **Mandatory security-negative gate** — SEC-5 **and** SEC-6 present and passing before completion

### Coverage expectations

- `lib/domain/artifact-url.ts` and `lib/domain/log-window.ts` are pure — target 100% stmt/branch (`coverage_gate` PASS).
- Run-detail components covered by Layer 2; report `coverage_gate` via `qa-engineer` at implement time.

---

## 8. AC Coverage Summary

| AC        | Positive             | Negative / edge / abuse          | Status  |
| --------- | -------------------- | -------------------------------- | ------- |
| AC-1      | SC-1                 | SC-1 (no-outer-scroll assertion) | covered |
| AC-2      | SC-1                 | SC-2, SC-3, SC-20                | covered |
| AC-3/AC14 | SC-4, SC-5           | SC-14 (SEC-5), SC-15             | covered |
| AC-4      | SC-6                 | SC-7, SC-16                      | covered |
| AC-5      | SC-8, SC-9           | SC-8 (2,000 boundary), RT-3      | covered |
| AC-6      | SC-10                | SC-11, SC-12, RT-4               | covered |
| AC-7      | —                    | SC-13 (SEC-6), RT-2              | covered |
| AC-8      | SC-17                | SC-11 (empty region has aria-live) | covered |
| AC-9      | —                    | SC-18, SC-19                     | covered |

**Every AC has ≥1 positive and ≥1 negative/edge/abuse scenario.** Both mandatory security-negative categories are present:
**SEC-5** (artifact URL scheme, SC-14 + RT-1) and **SEC-6** (inert message render, SC-13 + RT-2). No AC is uncovered.

---

## 9. Handoff

- **Next step:** `developer` implements S-109 test-first against this plan and the companion traceability matrix.
- **After implementation:** run `verifier` in **Audit Mode** against the delivered PR to confirm fidelity; drift routes
  to `product-engineer` (`activity-drift-reconciliation`). The audit is additive and non-blocking.
- **Watch item for the audit:** AC14 (SC-5) is the highest-risk-of-omission criterion; confirm it explicitly.
