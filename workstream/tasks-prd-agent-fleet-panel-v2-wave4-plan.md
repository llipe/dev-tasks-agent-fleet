# Implementation Plan — Agent Fleet Control Panel, Phase 2 (Wave 4)

## Scope

> **Status (2026-09-06): DELIVERED.** Both stories merged to `main` via consolidated PR [#143](https://github.com/llipe/dev-tasks-agent-fleet/pull/143); #125, #126, and #89 closed. `make validate` green on both branches. Two items remain **recorded BLOCKED** pending the deployed AgentCore runtime (tasks 1.17, 1.27 — OQ2 + the two live #89 checks) and are carried into S-115; task 2.18's 1024/1440 pixel-geometry check is deferred to the S-114 Playwright suite. These are the only non-`[x]` items and are marked `[~]`. A separate follow-up (`story/enable-invoke`) flips `INVOKE_ROUTE_AVAILABLE` to `true` now that the S-113 route ships.

Wave 4 is **the invocation wave**: the first time the panel *writes* to the database and reaches across the panel→agent boundary. S-112 lands the invoke route handler and the payload contract that closes [#89](https://github.com/llipe/dev-tasks-agent-fleet/issues/89); S-113 renders the schema-driven form on top of it. Everything before this wave was read-only.

| Task | Story | Issue | Size | Title |
| ---- | ----- | ----- | ---- | ----- |
| 1.0 | S-112 | [#125](https://github.com/llipe/dev-tasks-agent-fleet/issues/125) | L | Invoke route handler and agent payload translation (closes #89) |
| 2.0 | S-113 | [#126](https://github.com/llipe/dev-tasks-agent-fleet/issues/126) | M | Schema-driven invoke form |

Sources: [`user-stories-prd-agent-fleet-panel-v2.md`](user-stories-prd-agent-fleet-panel-v2.md) v1.2 (S-112, S-113), [`specification-prd-agent-fleet-panel-v2.md`](specification-prd-agent-fleet-panel-v2.md) (SD5, SD7, SD8, §4, §13, §15), [`/DESIGN.md`](../DESIGN.md) v1.1 (§5.4, §6, §7). Payload contract authority: `agents/dependency-update/app/dependencyUpdate/main.py:74` (`_REQUIRED_FIELDS = ("run_id", "repository_org", "repository_name")`).

Predecessors: Wave 1 (S-101/S-102/S-103 — closed), Wave 2 (S-104/S-105/S-111 — closed), Wave 3 (S-106/S-107/S-108 — S-107/#120 and S-108/#121 closed; S-106/#119 merged).

**Project type:** existing codebase. Workspace, gates, token layer, primitives, server read boundary, and the AWS credential/invocation modules all exist. **No Task 0.**

### Dependency state

**All Wave 4 dependencies are satisfied as of 2026-09-05.**

| Story | Depends on | State |
| ----- | ---------- | ----- |
| S-112 | S-104, S-111, S-103 | S-104 ✅ closed (#117); S-111 ✅ closed (#124, PR #135); S-103 ✅ closed (#116) |
| S-113 | S-105, S-112 | S-105 ✅ merged (#118); S-112 is task 1.0 |

**S-112 is the wave's serialization point.** S-113 submits to the S-112 route and shares the Ajv setup (`lib/schema/ajv.ts`) with it, so 1.0 completes before 2.0 begins. They are not parallelizable — S-113 cannot render a working submit path until the route exists.

The building blocks S-112 consumes are all in place:
- `panel/lib/aws/{credentials,invoke,errors}.ts` — the two-branch provider, the `InvokeAgentRuntime` wrapper against `runtime_arn` + `runtime_qualifier`, and the `CREDENTIALS_UNAVAILABLE`/`INVOCATION_FAILED` taxonomy (S-111).
- `panel/lib/supabase/{server,queries,types}.ts` and `panel/lib/domain/status.ts` — server-only reads and `effectiveStatus` (S-104).
- English `params_schema` titles/descriptions in the seed (S-103) — so the S-113 form is built against final labels, not Spanish ones that would force a rebuild (spec §15 ordering constraint, the reason S-103 preceded this wave).

### New surfaces this wave introduces

- **The first panel database write.** Every prior story read `v_runs` or the tables; S-112 inserts a `runs` row. The ordering is normative (**D1**): the `queued` row exists *before* AgentCore is contacted, so a launch that never starts is still a visible `failed_to_start` row rather than an invisible nothing (the #100 zero-row-`start()` failure the agent SDK now warns about).
- **The first cross-language contract test.** Nothing type-checks the panel→agent boundary — it is JSON over `InvokeAgentRuntime` into a Python `validate_payload`. **SR4**: a shared JSON fixture (`tests/fixtures/agent-invocation-payload.json`) is consumed by *both* the panel's Layer 1 test and a *new Python test* in the agent suite, so a dropped/renamed/nested field fails a test on one side instead of silently at runtime. This is the mechanism that closes #89 and keeps it closed.
- **`lib/schema/`** (new directory) — Ajv validation shared between the route (server-authoritative) and the form (client convenience), so the two cannot diverge in strictness.

### Wave-level notes carried forward

- **Route-segment config must be declared inline.** Next.js silently ignores `dynamic`/`revalidate`/`fetchCache` re-exported from another module (S-104 audit D4, `technical-guidelines.md` §12). The invoke route handler and the invoke form route both declare their config inline.
- **`effectiveStatus` is the only status source.** The form navigates to `/runs/[id]` on both `202` and `502`; where it shows a run's status it derives through `lib/domain/status.ts`, never `runs.status` (FR11a).
- **No migrations in this wave.** S-112 writes only *existing* columns of `runs`; S-113 renders and submits. Both record an explicit migration opt-out rationale (plan activity rule 8). **OQ3 is answered and must be honored:** `runs.max_runtime_seconds` is `not null` with *no default*, while `grace_seconds`/`start_timeout_seconds` are `not null default 120/300` — so the insert must send **all three** timeout snapshots explicitly, or two silently take schema defaults. This is a correctness requirement on the insert, not a schema change.
- **Untrusted-input discipline.** `params` is validated with Ajv `additionalProperties: false` and only schema-present keys pass through. `full_name` splitting is validated before any insert. `triggered_by` is the constant `"panel"` (SD7), never an identity.
- **New Layer 2.5 suites inherit the G2 hole** ([#134](https://github.com/llipe/dev-tasks-agent-fleet/issues/134)): the Docker gate skips-to-green when the local stack is down. Each story must state whether its integration suite **ran live** or skipped — a skip is not evidence.
- **The `ajv` bump to `>=8.18.0`** ([#126 note](https://github.com/llipe/dev-tasks-agent-fleet/issues/126)): S-113 is where `ajv` first does real work (the residual moderate advisory sits below the `--audit-level=high` gate today). Bump and re-audit is task 2.x.
- **Two live checks depend on the deployed runtime.** S-112 AC10 (`prompt`-wrapping observation, OQ2) and the two live #89 verifications (`queued → running`, and a malformed payload hitting `INVALID_PARAMS`) require the deployed AgentCore runtime. If the runtime is not yet deployed at implementation time, these are **recorded as blocked, not silently passed** — the same discipline S-111 applied to AC8/OQ1.

### Mandatory security-negative tests in this wave

Per the user-stories security-negative mapping, S-112 carries **#3** (Ajv rejects `additionalProperties`; no `runs` row written) and **#4** (`buildAgentPayload` rejects every malformed `full_name` shape). Both are DoD-blocking for S-112.

### Execution rules

One sub-task at a time, marked `[x]` locally **and** in the GitHub Issue checklist, then stop for approval. Branch per story (`story/S-112-invoke-route`, `story/S-113-invoke-form`), draft PR opened immediately after the first commit with `Closes #<n>`. Quality gates (`lint`, `format:check`, `typecheck`, `test`, `audit`) then `make validate` before completion. `pnpm` throughout; canonical scripts only. `gh issue`/`pr` operations use `--body-file`, never inline `--body`. No push or merge to `main`.

## Relevant Files

### Invoke route + payload contract (S-112)

- `panel/app/api/agents/[slug]/invoke/route.ts` — `POST` handler; normative ordering, inline `force-dynamic`, error taxonomy
- `panel/lib/domain/payload.ts` — `buildAgentPayload` (emits `run_id`, `repository_org`, `repository_name`, `base_branch`, `params`; never `repository_id`)
- `panel/lib/domain/run-insert.ts` — the `queued`-row snapshot builder (all three timeout columns explicit)
- `panel/lib/schema/validate.ts` — Ajv `params` validation against `params_schema` (`additionalProperties: false`)
- `panel/lib/schema/ajv.ts` — shared Ajv instance/config (consumed by S-113)
- `panel/lib/errors.ts` — the `{ error: { code, message, details } }` shape + code taxonomy (spec §13)
- `panel/lib/supabase/queries.ts` — extend with the run-insert / session-update helpers if not already present
- `tests/fixtures/agent-invocation-payload.json` — **shared** cross-language contract fixture (repo root)
- `panel/tests/unit/payload.test.ts`, `panel/tests/component/invoke-route.test.ts`, `panel/tests/integration/invoke-insert.test.ts`
- `agents/dependency-update/app/dependencyUpdate/tests/unit/test_payload_contract_fixture.py` — Python side of the shared fixture (asserts `validate_payload` accepts it; **must not modify agent production code**)
- `docs/runbooks/issue-89-live-verification.md` — operator runbook for the live #89 checks (tasks 1.17/1.27/OQ2), unblocked once the runtime is deployed
- `panel/scripts/verify-invoke.mjs` — operator helper automating Check A (`queued → running`)

### Schema-driven invoke form (S-113)

- `panel/app/agents/[slug]/invoke/page.tsx` — centered dialog route (`/DESIGN.md` §5.4)
- `panel/components/invoke/{InvokeDialog,FieldRow,RepositorySelect,SchemaPreview,SuccessState}.tsx`
- `panel/lib/schema/form.ts` — `params_schema` → field-descriptor array (enum→select, boolean→toggle, bounded int→number, string→text; unsupported→disabled note)
- `panel/lib/schema/ajv.ts` — shared with the S-112 route (client re-validation)
- `panel/tests/unit/form.test.ts`, `panel/tests/component/invoke-form.test.tsx`, `panel/tests/integration/synthetic-agent-form.test.ts`
- `panel/package.json` — `ajv` bump to `>=8.18.0` (#126 note)

## Tasks

- [x] 1.0 Implement Story S-112 ([#125](https://github.com/llipe/dev-tasks-agent-fleet/issues/125)): Invoke route handler and agent payload translation (closes #89)

  > Note: implements **FR14** and resolves **F1**/**SD5** — the boundary that closes #89. The authoritative contract is `main.py:74`: `run_id`, `repository_org`, `repository_name` as three non-empty top-level strings. Ordering is normative (**D1**): the `queued` `runs` row exists before AgentCore is contacted, so a launch that never starts is a visible `failed_to_start` row, not an invisible nothing. Nothing type-checks this boundary, so the shared JSON fixture (SR4) consumed by both the TS and Python suites is what keeps #89 from regressing.

  - [x] 1.1 Confirm #125 is open; confirm dependencies closed (S-104 #117, S-111 #124, S-103 #116); create branch `story/S-112-invoke-route` from latest `main`
  - [x] 1.2 Write the `buildAgentPayload` unit tests **first** (test-first) — happy path emitting exactly `run_id`/`repository_org`/`repository_name`/`base_branch`/`params`, and the malformed-`full_name` matrix (no slash, leading slash, trailing slash, multiple slashes, empty, whitespace-only halves) → **security-negative #4**; assert `repository_id` is never present in the payload
  - [x] 1.3 Implement `lib/domain/payload.ts` (`buildAgentPayload`) and commit `tests/fixtures/agent-invocation-payload.json` as the shared contract fixture; assert `buildAgentPayload` emits the fixture
  - [x] 1.4 First commit; open draft PR against `main` with `Closes #125` (use `--body-file`)
  - [x] 1.5 Add the Python-side fixture test `agents/.../tests/unit/test_payload_contract_fixture.py` asserting the agent's `validate_payload` accepts the shared fixture; confirm `make validate` runs it (Python branch). **Do not modify agent production code** — the agent contract is authoritative and unchanged
  - [x] 1.6 Implement `lib/errors.ts` — the `{ error: { code, message, details } }` shape and the code taxonomy from spec §13 (`MALFORMED_REPOSITORY` 400, `INVALID_PARAMS` 400, `CREDENTIALS_UNAVAILABLE` 500, `INVOCATION_FAILED` 502, `DATABASE_ERROR` 500), reusing the S-111 `lib/aws/errors.ts` codes where they already exist
  - [x] 1.7 Implement `lib/schema/validate.ts` + `lib/schema/ajv.ts` — Ajv 8 + `ajv-formats`, `additionalProperties: false`, validator compiled and cached per agent id + schema hash; only schema-present keys pass through
  - [x] 1.8 Implement `lib/domain/run-insert.ts` — the `queued`-row snapshot builder writing `params`, `agent_version` (from `agents.version`), and **all three** timeout columns explicitly (`max_runtime_seconds`, `grace_seconds`, `start_timeout_seconds`) per OQ3; `triggered_by = "panel"` (SD7); fail the request rather than write a row the reaper cannot resolve
  - [x] 1.9 Implement `app/api/agents/[slug]/invoke/route.ts` in the **normative order**: resolve agent → resolve repository → Ajv-validate `params` → generate `run_id` → split `full_name` → **insert `queued` run** → assume role → `InvokeAgentRuntime` → update `session_id`/`runtime_invocation_id`. Declare route-segment config **inline**
  - [x] 1.10 Add the `failed_to_start` write-on-throw path: if `InvokeAgentRuntime` throws, mark the run `failed_to_start` with an `error_code` in the handler and return `502` carrying `run_id` — no waiting for the reaper (AC12)
  - [x] 1.11 Add structured JSON logging on every invoke: `run_id`, `agent_slug`, `repository_full_name`, and `credentialSource()`; never log the payload, token, or STS response
  - [x] 1.12 Run Tests — unit: `pnpm run test:unit` — `buildAgentPayload` happy path + malformed-`full_name` matrix (**security-negative #4**); snapshot-builder completeness (all three timeouts non-null)
  - [x] 1.13 Run Tests — component: `pnpm run test` — route handler with Supabase, STS, and AgentCore mocked: full ordering assertion (insert precedes invoke), `400` + **no insert** for invalid params (**security-negative #3**) and for malformed `full_name`, `404` for unknown/disabled slug, `400` for disabled/archived repository, `failed_to_start` written on throw (AC12), `502` carries `run_id`, `CREDENTIALS_UNAVAILABLE` distinct from `INVOCATION_FAILED`
  - [x] 1.14 Run Tests — cross-language contract: the shared fixture is consumed by the panel unit test **and** the Python `validate_payload` test; assert failure if any required field is dropped, renamed, or nested (#89 AC3)
  - [x] 1.15 Run Tests — integration (2.5): `pnpm run test:integration` — against the local stack, a successful invoke (AgentCore mocked) writes exactly one `runs` row with all snapshots non-null; a rejected invoke writes zero rows. **State in the PR whether this ran live or skipped** (#134)
  - [x] 1.16 Run Tests — edge cases: `requires_repository = true` with `repository_id` absent; `repository_id` for a repo under a different installation; concurrent double-submit (two runs, two ids — no idempotency claim in v1); `params: {}` against a schema with required fields; unknown JSON-Schema type; agent row missing `runtime_arn`; STS success then AgentCore throw (row must end `failed_to_start`, not `queued`)
  - [~] 1.17 Manual/live verification (needs the deployed runtime): one real invocation transitioning `queued → running` (#89 AC1), and one deliberately malformed payload confirming the agent's `INVALID_PARAMS` (#89 AC2). **RECORDED BLOCKED** — runtime not deployed at wave-4 implementation time; to be verified during S-115
  - [x] 1.18 Verify Acceptance Criterion: `POST /api/agents/[slug]/invoke` accepts `{ repository_id, params }` and returns `202 { run_id, status: "queued" }` on success
  - [x] 1.19 Verify Acceptance Criterion: the ordering is exactly resolve→validate→generate→split→insert→assume→invoke→update
  - [x] 1.20 Verify Acceptance Criterion: `buildAgentPayload` emits `run_id`/`repository_org`/`repository_name`/`base_branch`/`params`; `repository_id` is never sent
  - [x] 1.21 Verify Acceptance Criterion: a `full_name` not splitting into exactly two non-empty halves is rejected `MALFORMED_REPOSITORY` (400) before any insert
  - [x] 1.22 Verify Acceptance Criterion: invalid `params` rejected `INVALID_PARAMS` (400), leaving no database trace (AC13)
  - [x] 1.23 Verify Acceptance Criterion: the insert snapshots `params`/`agent_version`/`max_runtime_seconds`/`grace_seconds`/`start_timeout_seconds` explicitly, never relying on defaults (OQ3)
  - [x] 1.24 Verify Acceptance Criterion: `InvokeAgentRuntime` throw → run marked `failed_to_start` + `502` with `run_id`, no reaper wait (AC12)
  - [x] 1.25 Verify Acceptance Criterion: credential failure returns `CREDENTIALS_UNAVAILABLE` (500), distinct from `INVOCATION_FAILED` (502)
  - [x] 1.26 Verify Acceptance Criterion: the shared fixture is asserted by both the panel Layer 1 test and the new Python test (SR4)
  - [~] 1.27 Verify Acceptance Criterion: the `prompt`-wrapping question (OQ2) is settled by observation on the first real integration and recorded — **RECORDED BLOCKED** pending the deployed runtime (S-115); `unwrap_payload` tolerance is in place and unit-tested
  - [x] 1.28 Verify Acceptance Criterion: every invoke logs `run_id`/`agent_slug`/`repository_full_name`/`credentialSource()` as structured JSON
  - [x] 1.29 Map acceptance criteria to test evidence in the PR: AC1–AC2/AC7–AC8 → handler component tests; AC3–AC4 → payload unit tests; AC5 → security-negative #3 + PRD AC13; AC6 → snapshot integration test; AC9 → shared-fixture tests both sides; AC10 → recorded observation; AC11 → log assertion
  - [x] 1.30 Run quality gates: `pnpm run lint`, `pnpm run format:check`, `pnpm run typecheck`, `pnpm run test`, `pnpm run audit`, then `make validate` (must run the new Python fixture test too)
  - [x] 1.31 Migration lifecycle: **not applicable** — writes only existing `runs` columns, no schema or data-model change. Opt-out rationale recorded here and in the issue
  - [x] 1.32 Close #89 with evidence (link the shared-fixture tests and, if available, the two live checks); record the OQ2 observation
  - [x] 1.33 Mark PR ready for review, notify the user, and close #125 only after the PR is approved and merged

- [x] 2.0 Implement Story S-113 ([#126](https://github.com/llipe/dev-tasks-agent-fleet/issues/126)): Schema-driven invoke form

  > Note: implements **FR13**/**D2** and proves **FR16**/**AC7** — a new agent is one database row, not a deploy. **SD8** rejects generic JSON-Schema form libraries (they fight `/DESIGN.md`'s token system); the actual need is small: `enum`→select, `boolean`→toggle, bounded `integer`→number, `string`→text. The repository field renders separately because it is not part of `params_schema` at all. The AC that proves the story is AC7: a *second* synthetic agent row with a different schema must render a correct form with zero code change.

  - [x] 2.1 Confirm task 1.0 is merged; confirm #126 is open; create branch `story/S-113-invoke-form` from latest `main`
  - [x] 2.2 Write the `form.ts` mapping unit tests **first**, then `lib/schema/form.ts` — enum→select, boolean→toggle, bounded integer→number, string→text, integer without bounds, `oneOf` (unsupported→disabled note), nested object (unsupported→disabled note), missing `title` (falls back to key name), `default` propagation, required-field marking
  - [x] 2.3 First commit; open draft PR against `main` with `Closes #126` (use `--body-file`)
  - [x] 2.4 Build the dialog shell `components/invoke/InvokeDialog.tsx` per `/DESIGN.md` §5.4 (centered, max-width 760px, `--shadow-lg`, header with agent slug + close, two-column field grid `minmax(0,1fr) 292px`), reusing the S-105 `Toggle`/`Input`/`Button`/`KLabel` primitives
  - [x] 2.5 Render controls from field descriptors (`FieldRow.tsx`); an unsupported schema type renders a **disabled field with a visible "unsupported type" note** — parameters never vanish silently
  - [x] 2.6 Add `RepositorySelect.tsx` rendered separately, outside the params, only when `requires_repository = true`, listing enabled non-archived repositories; empty-repositories state blocks submit
  - [x] 2.7 Wire client-side Ajv re-validation using the shared `lib/schema/ajv.ts` (same strictness as the S-112 route); invalid params block submission
  - [x] 2.8 Wire submission to the S-112 route and navigation: `202` → navigate to `/runs/[id]` with the `SuccessState` (`rise` animation, run ID, link); `502` → also navigate, where the run shows `failed_to_start`
  - [x] 2.9 Add error rendering: inline per-field for `INVALID_PARAMS`; banner for `MALFORMED_REPOSITORY`/`CREDENTIALS_UNAVAILABLE`/`DATABASE_ERROR`
  - [x] 2.10 Add the schema preview toggle (`SchemaPreview.tsx`) showing the raw `params_schema` (`/DESIGN.md` §5.4)
  - [x] 2.11 Pull labels/help text from the schema's `title`/`description` (English after S-103) and defaults from `default` / `agents.default_params`
  - [x] 2.12 Bump `ajv` to `>=8.18.0` in `panel/package.json` (this is where `ajv` first does real work — #126 note) and re-run `pnpm run audit`; record the advisory delta in the PR
  - [x] 2.13 Run Tests — unit: `pnpm run test:unit` — `form.ts` mapping matrix incl. the unsupported-type path, missing-`title` fallback, `default` propagation, required marking
  - [x] 2.14 Run Tests — component: `pnpm run test` — the seeded `dependency-update` schema renders the four expected controls (`fix_mode` select, `fail_on_findings` toggle, `max_fix_attempts` bounded number, `base_branch` text) purely from the schema (AC11); repository selector hidden when `requires_repository = false`; invalid input blocks submit; inline vs. banner error rendering; success navigation
  - [x] 2.15 Run Tests — AC7 proof (component/integration): a **synthetic second agent row** with a different `params_schema` renders a correct form with **zero code change**
  - [x] 2.16 Run Tests — integration (2.5): `pnpm run test:integration` — insert a synthetic agent row into the local stack and assert the form route renders its fields. **State in the PR whether this ran live or skipped** (#134)
  - [x] 2.17 Run Tests — edge cases: empty `params_schema` (`{}`) → no fields, submit still valid; schema with a `required` field having no default; zero enabled repositories → selector empty state + blocked submit; `max_fix_attempts` at 0 and 5 (inclusive bounds) and 6 (rejected); very long enum list; disabled agent → 404
  - [~] 2.18 Manual/UI verification: `pnpm --filter panel dev` → submit a real `audit_only`-style invocation and land on `/runs/[id]` (log tailing joins S-110); compare the dialog against `docs/prototype/` at 1024px and 1440px. **PARTIAL** — 1024/1440 pixel-geometry comparison deferred to the S-114 Playwright suite (jsdom computes no geometry); live submit-to-`/runs/[id]` depends on S-109/S-110 + deployed runtime
  - [x] 2.19 Verify Acceptance Criterion: `/agents/[slug]/invoke` renders the §5.4 dialog with slug, schema-driven field list, Cancel/Run
  - [x] 2.20 Verify Acceptance Criterion: `form.ts` maps the `dependency-update` schema to the four expected controls, derived solely from the schema (AC11)
  - [x] 2.21 Verify Acceptance Criterion: the repository selector renders separately, only when `requires_repository = true`, listing enabled non-archived repositories
  - [x] 2.22 Verify Acceptance Criterion: an unsupported schema type renders a disabled field with an "unsupported type" note — no silent vanish
  - [x] 2.23 Verify Acceptance Criterion: client Ajv blocks invalid submission and the server re-validates; a rejected submission leaves no `runs` row (AC13)
  - [x] 2.24 Verify Acceptance Criterion: submission navigates to `/runs/[id]` on `202`; a `502` also navigates, showing `failed_to_start`
  - [x] 2.25 Verify Acceptance Criterion: labels/help from schema `title`/`description`; defaults from `default`/`agents.default_params`
  - [x] 2.26 Verify Acceptance Criterion: AC7 — a second agent row with a different schema renders a correct form with zero code change
  - [x] 2.27 Verify Acceptance Criterion: errors render inline per field for `INVALID_PARAMS`, as a banner for the others
  - [x] 2.28 Verify Acceptance Criterion: the schema preview toggle shows the raw `params_schema`
  - [x] 2.29 Map acceptance criteria to test evidence in the PR: AC1–AC4/AC7/AC9–AC10 → component tests; AC5 → client Ajv test + the S-112 server test (PRD AC13); AC6 → navigation test + manual; AC8 → synthetic-agent test (PRD AC7)
  - [x] 2.30 Record `/DESIGN.md` §5.4 conformance notes in the PR — any prototype detail not reproduced
  - [x] 2.31 Run quality gates: `pnpm run lint`, `pnpm run format:check`, `pnpm run typecheck`, `pnpm run test`, `pnpm run audit`, then `make validate`
  - [x] 2.32 Migration lifecycle: **not applicable** — presentational + submit story, no schema or data-model change. Opt-out rationale recorded here and in the issue
  - [x] 2.33 Mark PR ready for review, notify the user, and close #126 only after the PR is approved and merged

## Wave 4 Exit Criteria

- [x] `POST /api/agents/[slug]/invoke` inserts the `queued` `runs` row **before** contacting AgentCore, with all three timeout snapshots explicit (D1, OQ3), and marks `failed_to_start` on invocation throw (AC12)
- [x] Invalid `params` and malformed `full_name` are rejected before any insert (security-negative #3 and #4), leaving no database trace (AC13)
- [x] The shared JSON fixture is asserted by both the TS and Python suites, so a panel→agent contract drift fails a test on one side (SR4); **#89 is closed with evidence**
- [x] `/agents/[slug]/invoke` renders a schema-driven form from `params_schema` alone, proven by a second synthetic agent row rendering correctly with zero code change (AC7/FR16)
- [x] The form's client Ajv shares strictness with the server route; the server remains authoritative
- [x] Both routes declare `force-dynamic` inline; no status is read from `runs.status` directly
- [x] `ajv` bumped to `>=8.18.0` (8.17.1 → 8.20.0); `make validate` green on both branches for both stories; #125 and #126 merged (PR #143) and closed
- [~] OQ2 (`prompt` wrapping) — **recorded BLOCKED** pending the deployed AgentCore runtime; to be observed and closed during S-115 (same discipline S-111 applied to AC8/OQ1). The `unwrap_payload` tolerance is in place and unit-tested; only the live observation is outstanding
- [x] Wave 5 (S-114 E2E → S-115 deploy) is unblocked

## Deferred — recorded so it is not mistaken for scope

- **Run detail** (`/runs/[id]`, S-109 #122) and **SSE live tail** (S-110 #123) are their own wave — the form navigates to `/runs/[id]`, which may not fully render until S-109 lands. Sequence the merges if S-109 has not landed when S-113 completes.
- **The two live #89 checks and OQ2** need the deployed AgentCore runtime; if undeployed, they are recorded blocked and closed during S-115, not silently passed.
- **Idempotency on double-submit** is not claimed in v1 (two submits = two runs).
- **User authentication** stays excluded (D16/FR18); `triggered_by` is the constant `"panel"`.
- **The privacy release gate and OIDC probe** are S-115 (#128).
- **Making Layer 2.5 skips fail CI** is [#134](https://github.com/llipe/dev-tasks-agent-fleet/issues/134), not a task here.

## Next Wave (proposed, not planned)

| Story | Issue | Size | Note |
| ----- | ----- | ---- | ---- |
| S-114 | [#127](https://github.com/llipe/dev-tasks-agent-fleet/issues/127) | M | Playwright E2E against the local stack — needs S-110 + S-113 |
| S-115 | [#128](https://github.com/llipe/dev-tasks-agent-fleet/issues/128) | M | Fly deployment, privacy release gate, OIDC probe — needs S-114 |

S-114 also needs S-109/S-110 (the run-detail + live-tail path scenarios 2/3/7). If those are not yet merged, they precede S-114 regardless of this wave.
