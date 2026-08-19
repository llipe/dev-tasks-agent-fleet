# Compliance Test Plan — Agent Control Plane v1

## Changelog

| Version | Date       | Summary                                          | Author   |
| ------- | ---------- | ------------------------------------------------ | -------- |
| 1.0     | 2026-08-19 | Initial test plan — Design Mode, pre-implementation | verifier |

---

## Source Input Summary

| Artifact | Version | Path |
| --- | --- | --- |
| PRD | 1.3 | `docs/requirements/PRD-agent-control-plane-v1-en.md` |
| Specification | 1.2 | `workstream/specification-agent-control-plane-v1.md` |
| User stories | 1.0 | `workstream/user-stories-agent-control-plane-v1.md` |
| Design contract | 1.1 | `DESIGN.md` |

---

## Acceptance Criteria Extraction

Numbered from PRD §13, augmented with behavioural requirements from §7, §8, and §17:

| AC-ID | Acceptance Criterion |
| --- | --- |
| AC-1 | Agents list shows all agents with `agent:managed=true`, with name, domain, last run, status, active repos, and 30-day estimated cost. |
| AC-2 | Agent detail view has Runs and Repos tabs; runs table is filterable by status and date range. |
| AC-3 | Repos view shows all subjects with agents covering them, last activity, and status. |
| AC-4 | Run panel opens from any table row without unmounting the table; shows metadata, span timeline, and logs. |
| AC-5 | Toggling `enabled` for a repository/agent pair writes to DynamoDB and reflects in the UI within the current session. |
| AC-6 | Adding a repository to an agent's scope via the UI is a sub-30-second operation with zero deploys. |
| AC-7 | `params` editor validates JSON before saving; invalid JSON never reaches DynamoDB. |
| AC-8 | The app validates `Cf-Access-Jwt-Assertion` against the team JWKS on every request; a missing or invalid token returns denial. |
| AC-9 | The origin is locked down (Tunnel or IP allowlist); direct access to `.fly.dev` is blocked. |
| AC-10 | Estimated cost renders as labeled estimate; an unknown `model_id` shows "unknown", never `$0.00`. A partially priced run is marked as incomplete. |
| AC-11 | `incomplete` status is derived at read time when `last_status = running` and elapsed > the agent's `maxLifetime` + 5 min grace. |
| AC-12 | Monthly infrastructure cost of the control plane stays under USD 10. |
| AC-13 | Session ID is unique per run, ≥33 characters, deterministic for a given scheduled occurrence. |
| AC-14 | Write separation enforced: agent cannot `PutItem`, cannot write `enabled`/`params`; control plane cannot `InvokeAgentRuntime`. |
| AC-15 | Agent emits four `llipe.*` root-span attributes on every run (including failures). |
| AC-16 | JSON logs with `session_id` on every line; no secrets logged. |
| AC-17 | Agent entrypoint returns immediately; pipeline runs on background thread reporting `HealthyBusy`. |
| AC-18 | Orchestrator reads scope from DynamoDB, not env var; partial failures isolated per repo. |
| AC-19 | Discovery by tag: an untagged agent is invisible; `agent:name` matches `AGENT#` key exactly. |

---

## E2E Black-Box Scenarios

### SC-1: Agents list renders all managed agents

| Field | Value |
| --- | --- |
| **AC(s)** | AC-1, AC-19 |
| **Type** | happy-path |
| **Severity** | critical |
| **Preconditions** | ≥1 agent tagged `agent:managed=true` exists; ≥1 agent exists without the tag. |
| **Steps** | 1. Navigate to `/agents`. |
| **Expected Result** | Table shows one row per tagged agent with name, domain, last run (relative), status badge, active repo count, and 30-day estimated cost. Untagged agent absent. |
| **Pass Criteria** | All tagged agents present; untagged absent; all columns populated. |

### SC-2: Untagged agent excluded from inventory

| Field | Value |
| --- | --- |
| **AC(s)** | AC-19 |
| **Type** | negative-path |
| **Severity** | critical |
| **Preconditions** | An agent runtime exists without `agent:managed=true`. |
| **Steps** | 1. Navigate to `/agents`. |
| **Expected Result** | The untagged agent does not appear. |
| **Pass Criteria** | No row with the untagged agent's name. |

### SC-3: Runs tab with status and date-range filter

| Field | Value |
| --- | --- |
| **AC(s)** | AC-2 |
| **Type** | happy-path |
| **Severity** | critical |
| **Preconditions** | Agent has runs across `success`, `failed`, `running`, and `incomplete` statuses. |
| **Steps** | 1. Navigate to `/agents/dep-updater?tab=runs`. 2. Filter by status=`failed`. 3. Set date range to last 7 days. |
| **Expected Result** | Only failed runs within 7 days shown; URL params reflect `status=failed&from=…&to=…`. Reload restores the same view. |
| **Pass Criteria** | Rows are exclusively `failed`; all within date range; URL round-trips. |

### SC-4: Repos view lists all subjects

| Field | Value |
| --- | --- |
| **AC(s)** | AC-3 |
| **Type** | happy-path |
| **Severity** | critical |
| **Preconditions** | ≥2 subjects exist in DynamoDB with `META` items. |
| **Steps** | 1. Navigate to `/repos`. |
| **Expected Result** | Table shows one row per subject with repo name, agent coverage count, last activity, and status. |
| **Pass Criteria** | All seeded subjects present; coverage counts match DynamoDB. |

### SC-5: Run panel opens without unmounting table

| Field | Value |
| --- | --- |
| **AC(s)** | AC-4 |
| **Type** | happy-path |
| **Severity** | critical |
| **Preconditions** | Runs table is visible; user has scrolled to the middle. |
| **Steps** | 1. Click a run row. 2. Observe panel opens. 3. Verify table scroll position unchanged. 4. Close panel. |
| **Expected Result** | Panel shows metadata, span timeline, and logs. Table stays mounted, scroll preserved. Focus returns to the row on close. |
| **Pass Criteria** | Scroll offset identical before/after; panel content matches the run; focus restoration. |

### SC-6: Toggle `enabled` optimistically with rollback on failure

| Field | Value |
| --- | --- |
| **AC(s)** | AC-5 |
| **Type** | happy-path + negative-path |
| **Severity** | critical |
| **Preconditions** | A repo is `enabled=true` for an agent. |
| **Steps** | 1. Toggle the switch → observe immediate visual flip. 2. Simulate DynamoDB write failure. 3. Observe revert and error message. |
| **Expected Result** | On success: toggle reflects new state. On failure: reverts to original state with error naming the repo. |
| **Pass Criteria** | Optimistic state change visible <200 ms; failure reverts and shows error. |

### SC-7: Add repository completes under 30 seconds

| Field | Value |
| --- | --- |
| **AC(s)** | AC-6 |
| **Type** | happy-path |
| **Severity** | critical |
| **Preconditions** | Agent detail repos tab open. Repo name not yet in scope. |
| **Steps** | 1. Enter repository name in the add form. 2. Submit. 3. Observe repo appears in table. |
| **Expected Result** | Repo appears within 30 seconds, enabled=true. No deploy triggered. |
| **Pass Criteria** | Total time < 30 s; new row visible; no CI/CD activity. |

### SC-8: `params` editor rejects invalid JSON and unknown keys

| Field | Value |
| --- | --- |
| **AC(s)** | AC-7 |
| **Type** | negative-path |
| **Severity** | critical |
| **Preconditions** | Repo has existing valid params. |
| **Steps** | 1. Open params editor. 2. Enter `{invalid json`. 3. Observe save disabled. 4. Enter `{"unknown_key": true}`. 5. Submit. |
| **Expected Result** | Malformed JSON prevents save client-side. Unknown key is rejected server-side with error naming the key. Neither reaches DynamoDB. |
| **Pass Criteria** | No DynamoDB write occurs; error messages are specific. |

### SC-9: Missing JWT denies access

| Field | Value |
| --- | --- |
| **AC(s)** | AC-8 |
| **Type** | negative-path |
| **Severity** | critical |
| **Preconditions** | App is deployed and reachable. |
| **Steps** | 1. Send GET `/agents` without `Cf-Access-Jwt-Assertion` header. |
| **Expected Result** | 403 or redirect to login. No data returned. |
| **Pass Criteria** | HTTP response is not 200; no agent data in body. |

### SC-10: Expired JWT denies access

| Field | Value |
| --- | --- |
| **AC(s)** | AC-8 |
| **Type** | negative-path |
| **Severity** | critical |
| **Preconditions** | A signed JWT with `exp` in the past. |
| **Steps** | 1. Send GET `/agents` with the expired token. |
| **Expected Result** | Denied. |
| **Pass Criteria** | HTTP 403. |

### SC-11: JWKS unreachable → fail closed

| Field | Value |
| --- | --- |
| **AC(s)** | AC-8 |
| **Type** | abuse-case |
| **Severity** | critical |
| **Preconditions** | JWKS endpoint unreachable (DNS failure or timeout). Valid token presented. |
| **Steps** | 1. Send GET `/agents` with a valid token while JWKS is unavailable. |
| **Expected Result** | Denied. The system does not fall back to allowing the request. |
| **Pass Criteria** | HTTP 403 even with a structurally valid token. |

### SC-12: Direct origin access blocked

| Field | Value |
| --- | --- |
| **AC(s)** | AC-9 |
| **Type** | abuse-case |
| **Severity** | critical |
| **Preconditions** | App deployed at `<app>.fly.dev`. |
| **Steps** | 1. Attempt direct HTTPS connection to the `.fly.dev` hostname. |
| **Expected Result** | Connection refused or returns a non-200 error. |
| **Pass Criteria** | No data returned. Request does not reach the app. |

### SC-13: Unknown `model_id` shows "unknown", never $0.00

| Field | Value |
| --- | --- |
| **AC(s)** | AC-10 |
| **Type** | negative-path |
| **Severity** | major |
| **Preconditions** | A run used a model not present in `pricing-v1.json`. |
| **Steps** | 1. Navigate to the run list containing that run. |
| **Expected Result** | Cost column shows "unknown", not `$0.00`. |
| **Pass Criteria** | Text content is "unknown" or equivalent marker; no zero dollar rendering. |

### SC-14: Partially priced run shows ≥ marker

| Field | Value |
| --- | --- |
| **AC(s)** | AC-10 |
| **Type** | happy-path |
| **Severity** | major |
| **Preconditions** | A run used two models; one is priced, one is not. |
| **Steps** | 1. View the run's cost. |
| **Expected Result** | Displays `≥ $X.XX` with an incomplete marker and the unpriced model in a tooltip. |
| **Pass Criteria** | `≥` prefix present; tooltip names the unpriced model. |

### SC-15: `incomplete` status derived correctly

| Field | Value |
| --- | --- |
| **AC(s)** | AC-11 |
| **Type** | happy-path |
| **Severity** | critical |
| **Preconditions** | A run row in DynamoDB: `last_status=running`, `last_run_at` older than `maxLifetime + 5 min`. |
| **Steps** | 1. Navigate to the runs list. |
| **Expected Result** | The run shows as `incomplete` (amber badge), not `running`. |
| **Pass Criteria** | `StatusBadge` renders `incomplete`; colour is amber; badge is not red (not `failed`). |

### SC-16: A genuinely running run is NOT marked incomplete

| Field | Value |
| --- | --- |
| **AC(s)** | AC-11 |
| **Type** | negative-path |
| **Severity** | critical |
| **Preconditions** | A run started 2 minutes ago; `last_status=running`; agent `maxLifetime=3600`. |
| **Steps** | 1. Navigate to runs list. |
| **Expected Result** | Run shows as `running` (blue), not `incomplete`. |
| **Pass Criteria** | `StatusBadge` renders `running`. |

### SC-17: ≤3 clicks from run list to logs of a failed run

| Field | Value |
| --- | --- |
| **AC(s)** | AC-4 |
| **Type** | happy-path |
| **Severity** | critical |
| **Preconditions** | A failed run exists in the list. |
| **Steps** | 1. Starting from `/agents/dep-updater?tab=runs`, click the failed run row. 2. Count clicks until logs are visible. |
| **Expected Result** | Logs visible in ≤3 clicks (1 click: the row). |
| **Pass Criteria** | Click count ≤ 3; log content visible and filtered to that run's `session_id`. |

### SC-18: `params` injection — shell metacharacters in params value

| Field | Value |
| --- | --- |
| **AC(s)** | AC-7 |
| **Type** | abuse-case |
| **Severity** | critical |
| **Preconditions** | Params editor open. |
| **Steps** | 1. Enter `{"allow_fixes": true, "max_fix_attempts": 3}` but also attempt to include a key `"; rm -rf /; echo "` via direct API call. |
| **Expected Result** | Server rejects unknown key. No shell execution occurs. |
| **Pass Criteria** | HTTP error; DynamoDB unchanged; no evidence of shell activity. |

### SC-19: Filter state survives reload

| Field | Value |
| --- | --- |
| **AC(s)** | AC-2 |
| **Type** | happy-path |
| **Severity** | major |
| **Preconditions** | Filters applied: status=failed, from=7d ago, to=now. |
| **Steps** | 1. Note the URL. 2. Hard reload. 3. Compare displayed state. |
| **Expected Result** | Same filters applied, same rows shown. |
| **Pass Criteria** | URL params unchanged; displayed content identical. |

---

## Contract Validation Scenarios

### CT-1: Emission contract — valid root span with all `llipe.*` attributes

| Field | Value |
| --- | --- |
| **AC(s)** | AC-15 |
| **Contract type** | provider-driven |
| **Boundary** | Agent root span → CloudWatch Logs (spans destination) |
| **Direction** | event-payload |
| **Input** | Root span with `llipe.subject.id`, `llipe.run.status`, `llipe.outcome.type`, `llipe.outcome.url` all present |
| **Expected Result** | Span ingested and queryable; control plane mapper produces a complete `Run` row |
| **Pass Criteria** | Logs Insights query returns the span with all four attributes populated |

### CT-2: Emission contract — missing `llipe.subject.id`

| Field | Value |
| --- | --- |
| **AC(s)** | AC-15 |
| **Contract type** | schema-compat |
| **Boundary** | Agent root span → control plane mapper |
| **Direction** | event-payload |
| **Input** | Span with `llipe.subject.id` absent |
| **Expected Result** | Run is either excluded from the repository view or mapped with an explicit marker; no silent data corruption |
| **Pass Criteria** | Mapper skips or flags the span; no entry with a null/empty subject appears in the repos view |

### CT-3: DynamoDB item schema — valid `SubjectAgentItem`

| Field | Value |
| --- | --- |
| **AC(s)** | AC-5, AC-14 |
| **Contract type** | schema-compat |
| **Boundary** | DynamoDB table ↔ `packages/shared` schema |
| **Direction** | read (control plane reads what others write) |
| **Input** | Item: `pk=SUBJECT#myorg/repo, sk=AGENT#dep-updater, enabled=true, params={}, last_session_id=..., last_run_at=2026-..., last_status=success, last_outcome_url=https://...` |
| **Expected Result** | Item validates against `SubjectAgentItem` Zod schema |
| **Pass Criteria** | `SubjectAgentItem.parse(item)` succeeds; all fields typed correctly |

### CT-4: DynamoDB — agent writes only two attributes

| Field | Value |
| --- | --- |
| **AC(s)** | AC-14 |
| **Contract type** | consumer-driven |
| **Boundary** | Agent → DynamoDB (via `agent-exec-role`) |
| **Direction** | request |
| **Input** | `UpdateItem` expression setting `last_status` and `last_outcome_url` |
| **Expected Result** | Write succeeds; `enabled` and `params` are unchanged |
| **Pass Criteria** | Post-write: `enabled` and `params` values identical to pre-write snapshot |

### CT-5: DynamoDB — agent `PutItem` denied

| Field | Value |
| --- | --- |
| **AC(s)** | AC-14 |
| **Contract type** | consumer-driven |
| **Boundary** | Agent → DynamoDB (via `agent-exec-role`) |
| **Direction** | request |
| **Input** | `PutItem` with `pk=SUBJECT#repo, sk=AGENT#dep-updater, ...` |
| **Expected Result** | IAM denies the request |
| **Pass Criteria** | `AccessDeniedException`; item unchanged |

### CT-6: DynamoDB — agent `UpdateItem` on `enabled` denied

| Field | Value |
| --- | --- |
| **AC(s)** | AC-14 |
| **Contract type** | consumer-driven |
| **Boundary** | Agent → DynamoDB (via `agent-exec-role`) |
| **Direction** | request |
| **Input** | `UpdateItem SET enabled = :val` |
| **Expected Result** | IAM denies the request |
| **Pass Criteria** | `AccessDeniedException` |

### CT-7: Control plane — `InvokeAgentRuntime` denied

| Field | Value |
| --- | --- |
| **AC(s)** | AC-14 |
| **Contract type** | consumer-driven |
| **Boundary** | Control plane → AgentCore (via `control-plane-role`) |
| **Direction** | request |
| **Input** | `InvokeAgentRuntime` call |
| **Expected Result** | IAM denies the request |
| **Pass Criteria** | `AccessDeniedException` |

### CT-8: Orchestrator payload envelope — valid

| Field | Value |
| --- | --- |
| **AC(s)** | AC-13, AC-18 |
| **Contract type** | consumer-driven |
| **Boundary** | Orchestrator → Agent (via `InvokeAgentRuntime`) |
| **Direction** | request |
| **Input** | `{"session_id": "dep-updater-myorg-repo-20260824-060000", "repo": "myorg/repo", "params": {"allow_fixes": true}}` |
| **Expected Result** | Agent accepts payload; pipeline starts |
| **Pass Criteria** | No `KeyError`; agent logs show the session_id |

### CT-9: Orchestrator payload — missing `session_id`

| Field | Value |
| --- | --- |
| **AC(s)** | AC-13 |
| **Contract type** | consumer-driven |
| **Boundary** | Orchestrator → Agent |
| **Direction** | request |
| **Input** | `{"repo": "myorg/repo", "params": {}}` — no `session_id` |
| **Expected Result** | Agent fails fast with a clear logged error |
| **Pass Criteria** | Error logged with "missing session_id"; no silent corruption |

### CT-10: Orchestrator payload — unknown `params` key rejected

| Field | Value |
| --- | --- |
| **AC(s)** | AC-7 |
| **Contract type** | schema-compat |
| **Boundary** | Orchestrator → Agent |
| **Direction** | request |
| **Input** | `{"session_id": "...", "repo": "...", "params": {"allow_fixes": true, "evil_key": true}}` |
| **Expected Result** | Agent rejects the unknown key on re-validation |
| **Pass Criteria** | Error logged naming `evil_key`; pipeline does not proceed with unvalidated input |

### CT-11: `session_id` presence on span

| Field | Value |
| --- | --- |
| **AC(s)** | AC-13, AC-15 |
| **Contract type** | provider-driven |
| **Boundary** | AgentCore ADOT → span destination |
| **Direction** | event-payload |
| **Input** | A completed run's root span |
| **Expected Result** | Span carries a `session.id` (or equivalent) attribute matching the orchestrator-generated value |
| **Pass Criteria** | Attribute present; value equals the `last_session_id` stored in DynamoDB for that run |

### CT-12: Generated Python module matches TypeScript source

| Field | Value |
| --- | --- |
| **AC(s)** | AC-15 (contract integrity) |
| **Contract type** | schema-compat |
| **Boundary** | `packages/shared` (TS) → `generated/shared_contract.py` |
| **Direction** | build artifact |
| **Input** | Current TypeScript source |
| **Expected Result** | Running codegen produces byte-identical output to the committed artifact |
| **Pass Criteria** | `diff` between fresh codegen output and committed file is empty |

### CT-13: Server Action — `setSubjectEnabled` with invalid input

| Field | Value |
| --- | --- |
| **AC(s)** | AC-5, AC-8 |
| **Contract type** | consumer-driven |
| **Boundary** | Browser → Server Action |
| **Direction** | request |
| **Input** | `{ repo: 123, agent: "dep-updater", enabled: "not-bool" }` |
| **Expected Result** | Validation error returned; no DynamoDB write |
| **Pass Criteria** | Response `{ ok: false, error: { kind: 'validation', ... } }`; DB unchanged |

### CT-14: Server Action re-verifies JWT

| Field | Value |
| --- | --- |
| **AC(s)** | AC-8 |
| **Contract type** | consumer-driven |
| **Boundary** | Browser → Server Action |
| **Direction** | request |
| **Input** | Valid form data but expired/missing JWT (middleware bypass simulation) |
| **Expected Result** | Action rejects with `unauthorized` |
| **Pass Criteria** | `{ ok: false, error: { kind: 'unauthorized' } }`; no DB write |

---

## Edge-Case Catalog

### EC-1: `session_id` shorter than 33 characters for a short agent+repo pair

| Field | Value |
| --- | --- |
| **AC(s)** | AC-13 |
| **Category** | Input Domain |
| **Input / Setup** | Agent `ci`, repo `web` → base is `ci-web-20260824-060000` (26 chars) |
| **Expected Result** | `buildSessionId` pads to ≥33 characters |
| **Risk if Missed** | `InvokeAgentRuntime` rejects the call per-repo, intermittently, with no obvious cause |

### EC-2: `deriveStatus` at exactly `maxLifetime + grace` boundary

| Field | Value |
| --- | --- |
| **AC(s)** | AC-11 |
| **Category** | Data Boundaries |
| **Input / Setup** | `now - last_run_at` == `maxLifetimeMs + TERMINATION_GRACE_MS` exactly |
| **Expected Result** | Returns `incomplete` (at the boundary, not one ms before) |
| **Risk if Missed** | Off-by-one causes false positives or false negatives at the transition point |

### EC-3: `deriveStatus` with absent `maxLifetime`

| Field | Value |
| --- | --- |
| **AC(s)** | AC-11 |
| **Category** | Failure Modes |
| **Input / Setup** | `GetAgentRuntime` response has no `lifecycleConfiguration` field |
| **Expected Result** | Falls back to `DEFAULT_MAX_LIFETIME_MS` (28800000) |
| **Risk if Missed** | TypeError or NaN comparison; runs never transition to `incomplete` |

### EC-4: Concurrent toggle — two users flip the same repo simultaneously

| Field | Value |
| --- | --- |
| **AC(s)** | AC-5 |
| **Category** | Timing & Concurrency |
| **Input / Setup** | Two `setSubjectEnabled` calls for the same repo arrive within 50 ms |
| **Expected Result** | Last write wins; no data corruption; both callers get a coherent response |
| **Risk if Missed** | `enabled` oscillates or conditional check fails with an unexpected error |

### EC-5: Add a repository that already exists

| Field | Value |
| --- | --- |
| **AC(s)** | AC-6 |
| **Category** | Idempotency |
| **Input / Setup** | Call `addSubjectToAgent` for a pair that is already in DynamoDB |
| **Expected Result** | Returns `conflict` error; existing item unchanged |
| **Risk if Missed** | Silent overwrite; `enabled` and `params` reset to defaults, losing operator config |

### EC-6: `normalizeSubjectId` with SSH remote format

| Field | Value |
| --- | --- |
| **AC(s)** | AC-15 (subject ID consistency) |
| **Category** | Input Domain |
| **Input / Setup** | `git@github.com:myorg/repo.git` |
| **Expected Result** | Normalizes to `myorg/repo` |
| **Risk if Missed** | Agent emits a subject ID that doesn't match the DynamoDB key; run invisible in repos view |

### EC-7: `params` with valid key but wrong type (`max_fix_attempts: "three"`)

| Field | Value |
| --- | --- |
| **AC(s)** | AC-7 |
| **Category** | Input Domain |
| **Input / Setup** | `{"max_fix_attempts": "three"}` |
| **Expected Result** | Rejected with type mismatch error naming the field |
| **Risk if Missed** | Agent receives a string where it expects an int; runtime `TypeError` mid-pipeline |

### EC-8: Run with zero model invocations (deterministic happy path)

| Field | Value |
| --- | --- |
| **AC(s)** | AC-10, AC-15 |
| **Category** | Data Boundaries |
| **Input / Setup** | Agent runs pnpm update, no changes found → pipeline completes without invoking Claude |
| **Expected Result** | `tokens_in=0, tokens_out=0, estimated_cost={usd:0, complete:true}`. NOT "unknown". |
| **Risk if Missed** | Zero tokens conflated with "model not priced"; healthy runs show "unknown" cost |

### EC-9: Logs Insights query times out

| Field | Value |
| --- | --- |
| **AC(s)** | AC-2, AC-4 |
| **Category** | Failure Modes |
| **Input / Setup** | Wide date range (30 days) on a busy log group; query exceeds 25 s deadline |
| **Expected Result** | UI shows "timed out" state distinct from "no runs", with suggestion to narrow range |
| **Risk if Missed** | Operator sees empty list during an incident and concludes nothing ran |

### EC-10: Container restart clears cache — first request after restart

| Field | Value |
| --- | --- |
| **AC(s)** | AC-1 |
| **Category** | Failure Modes |
| **Input / Setup** | Container just started; cache empty; cold request |
| **Expected Result** | Page renders correctly after a few seconds (cold Insights query); shows loading skeleton during. No error. |
| **Risk if Missed** | Error page on cold start; operator concludes the app is broken |

### EC-11: Orchestrator Lambda retries the same scheduled event

| Field | Value |
| --- | --- |
| **AC(s)** | AC-13 |
| **Category** | Idempotency |
| **Input / Setup** | Lambda invoked twice with the same `scheduledAt` (EventBridge retry) |
| **Expected Result** | Same `session_id` generated; `UpdateItem` is idempotent; agent not double-invoked |
| **Risk if Missed** | Two runs against the same repo with the same session, corrupting logs and DynamoDB |

### EC-12: Agent dies without writing outcome → `incomplete` derivation

| Field | Value |
| --- | --- |
| **AC(s)** | AC-11 |
| **Category** | Failure Modes |
| **Input / Setup** | Agent process killed at `maxLifetime`; no `last_status` update, no span emitted |
| **Expected Result** | After `maxLifetime + grace`, run shows as `incomplete` with logs up to the cut-off |
| **Risk if Missed** | Run stuck as `running` forever; operator does not notice |

### EC-13: `token` header present but empty string

| Field | Value |
| --- | --- |
| **AC(s)** | AC-8 |
| **Category** | Input Domain |
| **Input / Setup** | `Cf-Access-Jwt-Assertion: ""` |
| **Expected Result** | Denied |
| **Risk if Missed** | Empty string passes a presence check and reaches the verifier as invalid input, potentially throwing an unhandled error |

### EC-14: DynamoDB item deleted mid-run — agent outcome write

| Field | Value |
| --- | --- |
| **AC(s)** | AC-14 |
| **Category** | Failure Modes |
| **Input / Setup** | Operator removes a subject/agent pair while a run for it is in progress |
| **Expected Result** | Agent's outcome `UpdateItem` encounters `ConditionalCheckFailed`; logs an error; does not create a new item |
| **Risk if Missed** | Ghost item appears with only `last_status` and `last_outcome_url`, confusing the repos view |

### EC-15: Multiple concurrent orchestrator invocations for the same repo

| Field | Value |
| --- | --- |
| **AC(s)** | AC-18 |
| **Category** | Timing & Concurrency |
| **Input / Setup** | EventBridge fires twice within the same minute due to a glitch |
| **Expected Result** | `buildSessionId` with `scheduledAt` produces the same ID → second `UpdateItem` is a no-op; second `InvokeAgentRuntime` with the same session may be treated as session resumption |
| **Risk if Missed** | Two concurrent runs on the same repo with data corruption or rate-limit exhaustion |

---

## Randomized Test Tactics

### RT-1: Fuzz `params` JSON field

| Field | Value |
| --- | --- |
| **AC(s)** | AC-7 |
| **Tactic type** | fuzz |
| **Input surface** | `params` textarea input, both client-side and server-side |
| **Property / Oracle** | No 5xx response. Validation error returned for invalid input. DynamoDB never written with unvalidated data. No shell or prompt injection observable. |
| **Iterations** | 500 |
| **Seed** | `fuzz-AC7-{timestamp}-{hex}` |
| **Replay instruction** | `pnpm --filter control-plane run test:fuzz -- --seed=<seed> --tactic=RT-1 --iterations=1` |
| **Shrink strategy** | Binary search on payload size and structure to find minimal rejected/accepted boundary |

**Mutation corpus:**
- Valid base: `{"allow_fixes": true, "max_fix_attempts": 3}`
- Mutations: truncated JSON, nested objects, arrays, `null` values, numbers > `MAX_SAFE_INTEGER`, strings exceeding 10KB, keys with shell metacharacters, keys matching `__proto__`, `constructor`, deeply nested structures, unicode escape sequences

### RT-2: Property — `deriveStatus` never returns `incomplete` for a run younger than `maxLifetime`

| Field | Value |
| --- | --- |
| **AC(s)** | AC-11 |
| **Tactic type** | property-based |
| **Input surface** | Random `lastRunAt` (within the last `maxLifetimeMs`), random `maxLifetimeMs` (900000–28800000), random `now` |
| **Property / Oracle** | If `now - lastRunAt < maxLifetimeMs + TERMINATION_GRACE_MS`, result is never `incomplete`. |
| **Iterations** | 1000 |
| **Seed** | `prop-AC11-{timestamp}-{hex}` |
| **Replay instruction** | `pnpm --filter shared run test:prop -- --seed=<seed> --tactic=RT-2 --iterations=1` |
| **Shrink strategy** | Narrow `now - lastRunAt` toward the boundary to find the tightest passing input |

### RT-3: Property — `buildSessionId` always ≥33 characters

| Field | Value |
| --- | --- |
| **AC(s)** | AC-13 |
| **Tactic type** | property-based |
| **Input surface** | Random agent names (1–64 chars, `[a-z0-9-]`), random repo names (1–100 chars), random dates |
| **Property / Oracle** | Output length is always ≥33. Output matches `[A-Za-z0-9-]` (no characters requiring URL encoding). Deterministic: same input → same output. |
| **Iterations** | 1000 |
| **Seed** | `prop-AC13-{timestamp}-{hex}` |
| **Replay instruction** | `pnpm --filter shared run test:prop -- --seed=<seed> --tactic=RT-3 --iterations=1` |
| **Shrink strategy** | Reduce agent and repo name lengths toward minimum to find shortest output |

### RT-4: Property — `estimateRunCost` never returns `usd = 0` with `complete = false`

| Field | Value |
| --- | --- |
| **AC(s)** | AC-10 |
| **Tactic type** | property-based |
| **Input surface** | Random model usages: 0–5 models, random token counts (0–10M), random pricing table entries (some models priced, some not) |
| **Property / Oracle** | If `complete === false` and `usd !== null`, then `usd > 0` (at least one model was priced). If no model was priced at all, `usd === null`. Never `usd === 0` AND `complete === false` simultaneously. |
| **Iterations** | 500 |
| **Seed** | `prop-AC10-{timestamp}-{hex}` |
| **Replay instruction** | `pnpm --filter control-plane run test:prop -- --seed=<seed> --tactic=RT-4 --iterations=1` |
| **Shrink strategy** | Reduce to 1 model usage entry; vary token counts toward zero |

### RT-5: Stateful walk — random scope mutations followed by invariant check

| Field | Value |
| --- | --- |
| **AC(s)** | AC-5, AC-6, AC-7, AC-14 |
| **Tactic type** | stateful-random-walk |
| **Input surface** | Sequence of: `addSubjectToAgent`, `setSubjectEnabled(true/false)`, `setSubjectParams(valid/invalid)` in random order |
| **Property / Oracle** | After any sequence: (1) every subject has a `META` item, (2) `last_*` attributes are never modified by these actions, (3) no invalid params in DynamoDB, (4) enabled-count matches reality. |
| **Iterations** | 200 sequences of 5–15 actions each |
| **Seed** | `walk-scope-{timestamp}-{hex}` |
| **Replay instruction** | `pnpm --filter control-plane run test:stateful -- --seed=<seed> --tactic=RT-5 --iterations=1` |
| **Shrink strategy** | Remove actions from failing sequence until invariant still fails; report minimal breaking sequence |

### RT-6: Fuzz JWT token structure

| Field | Value |
| --- | --- |
| **AC(s)** | AC-8 |
| **Tactic type** | fuzz |
| **Input surface** | `Cf-Access-Jwt-Assertion` header value |
| **Property / Oracle** | No 5xx. Every malformed/invalid token → denied (403). Never an authentication bypass. |
| **Iterations** | 300 |
| **Seed** | `fuzz-AC8-{timestamp}-{hex}` |
| **Replay instruction** | `pnpm --filter control-plane run test:fuzz -- --seed=<seed> --tactic=RT-6 --iterations=1` |
| **Shrink strategy** | Isolate which token segment (header/payload/signature) triggers unexpected behavior |

**Mutation corpus:**
- Valid base: correctly signed RS256 JWT
- Mutations: truncated token, extra `.` segments, base64-invalid payload, `alg: none`, `alg: HS256` with JWKS public key as HMAC secret, expired by 1 second, `aud` mismatch, `iss` mismatch, unknown `kid`, empty string, `null` bytes in payload, token > 8KB

---

## Execution Checklist

- [ ] All 19 acceptance criteria mapped to ≥1 positive and ≥1 negative/edge scenario
- [ ] All E2E scenarios reference observable behavior only (no internal implementation)
- [ ] All contract tests cover valid, missing-field, type-mismatch, and extra-field cases
- [ ] All 9 edge-case categories evaluated; N/A noted where applicable
- [ ] All randomized tactics have seed, replay, and shrink strategy
- [ ] Failure triage workflow applies to RT-1 through RT-6

---

## Category Coverage (Edge Cases)

| Category | Applicable? | Edge cases |
| --- | --- | --- |
| 1. Input Domain | Yes | EC-1, EC-6, EC-7, EC-8, EC-13 |
| 2. State Transitions | Yes | EC-12 (running → incomplete via timeout) |
| 3. Timing & Concurrency | Yes | EC-4, EC-11, EC-15 |
| 4. Idempotency | Yes | EC-5, EC-11 |
| 5. Failure Modes | Yes | EC-3, EC-9, EC-10, EC-12, EC-14 |
| 6. Auth & Permissions | Yes | CT-5, CT-6, CT-7, SC-9–SC-12, EC-13 |
| 7. Data Boundaries | Yes | EC-2, EC-8 |
| 8. Resource Exhaustion | N/A — single operator, no rate limiting in the app, resource bounds handled by AWS quotas | — |
| 9. API Versioning | N/A — no public API, no versioning in v1 | — |
