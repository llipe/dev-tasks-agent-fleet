# Compliance Test Plan — Agent Fleet Control Panel, Phase 2 (Wave 4: S-112, S-113)

> **verifier — Design Mode.** Test-first compliance plan derived from observable behavior, before implementation.
> **Independence caveat:** this pass was authored under the `product-engineer` seat that also wrote `tasks-prd-agent-fleet-panel-v2-wave4-plan.md`, not by an independent `verifier` agent. It therefore provides reduced-independence assurance — it inherits any blind spots of the task plan rather than cross-checking them from a fresh reading. Treat the flagged gaps (§Flagged Gaps) as the places that most need a second set of eyes.

## Scope

| Story | Issue | Source | Input type |
| ----- | ----- | ------ | ---------- |
| S-112 — Invoke route handler and agent payload translation (closes #89) | [#125](https://github.com/llipe/dev-tasks-agent-fleet/issues/125) | `user-stories-prd-agent-fleet-panel-v2.md` v1.2 | story |
| S-113 — Schema-driven invoke form | [#126](https://github.com/llipe/dev-tasks-agent-fleet/issues/126) | `user-stories-prd-agent-fleet-panel-v2.md` v1.2 | story |

Companion artifacts: [`tasks-prd-agent-fleet-panel-v2-wave4-plan.md`](tasks-prd-agent-fleet-panel-v2-wave4-plan.md), [`specification-prd-agent-fleet-panel-v2.md`](specification-prd-agent-fleet-panel-v2.md) (SD5, SD7, SD8, §4, §13, §15), [`/DESIGN.md`](../DESIGN.md) §5.4.

**Grounded facts read from source (not assumed):**

- **Contract authority** — `agents/dependency-update/app/dependencyUpdate/main.py:74`: `_REQUIRED_FIELDS = ("run_id", "repository_org", "repository_name")`. `validate_payload` (`:149`) rejects unless each is a **non-empty string**; `params` is *not* in `_REQUIRED_FIELDS` (the agent tolerates its absence and defaults it in `apply_defaults` `:163`), but the panel always sends it. The panel payload also carries `base_branch`, which the agent ignores when absent — so the fixture must include it for a full-contract assertion while the required-field test targets only the three.
- **Payload unwrap** — the agent runs `unwrap_payload` (`:83`) then `validate_payload`; a still-wrapper-only payload triggers the "appears double-wrapped" diagnostic (issue #97). This is the OQ2 surface: whether the panel must pre-wrap in a `prompt` key is settled **by observation**, and both wrapped and bare forms are accepted agent-side.
- **`runs` insert / OQ3** — `create table runs` (`migrations/…_initial_schema.sql:108`): `max_runtime_seconds` (`:131`) is `not null` **with no default**; `grace_seconds`/`start_timeout_seconds` (`:132-133`) are `not null default 60/300`. The seeded **agent** row (`agents` table, different defaults 900/60/300 at `:93-95`) carries **3600/120/300**. Consequence the plan must catch: omitting `max_runtime_seconds` on the insert fails loudly, but omitting `grace_seconds` silently writes **60** instead of the agent's **120** — a run the reaper then evaluates against the wrong grace window. OQ3 is therefore a real correctness requirement, not a style note.
- **Error taxonomy** — spec §13 (`:500-510`): single shape `{ error: { code, message, details } }`. Codes/statuses: `INVALID_PARAMS` 400, `MALFORMED_REPOSITORY` 400, `INVOCATION_FAILED` 502, `CREDENTIALS_UNAVAILABLE` 500, `DATABASE_ERROR` 500. `DATABASE_ERROR` logs the Postgres code, never returns it.
- **`triggered_by`** — constant `"panel"` (spec §13 `:345`, SD7); the column is nullable in DDL (`:116`) but the panel writes the constant.
- **Seeded `params_schema`** (`supabase/seed.sql:71-104`, English post-S-103): `fix_mode` (string enum `[audit_only, llm_fix]`, **required**, default `audit_only`), `fail_on_findings` (boolean, default true), `max_fix_attempts` (integer, **min 0 max 5**, default 3), `base_branch` (string, default `main`). `additionalProperties: false`. This is the exact fixture for AC11 and the bounds edge cases.

## Requirement Extraction

### S-112 acceptance criteria (from the story)

| AC | Requirement (observable) |
| --- | --- |
| AC-112.1 | `POST /api/agents/[slug]/invoke` accepts `{ repository_id, params }`, returns `202 { run_id, status: "queued" }` on success |
| AC-112.2 | Order is exactly: resolve agent → resolve repository → Ajv-validate → generate `run_id` → split `full_name` → **insert `queued`** → assume role → `InvokeAgentRuntime` → update `session_id`/`runtime_invocation_id` |
| AC-112.3 | `buildAgentPayload` emits `run_id`, `repository_org`, `repository_name`, `base_branch` (from `repositories.default_branch`), `params`; `repository_id` **never** sent |
| AC-112.4 | `full_name` not splitting into exactly two non-empty halves → `MALFORMED_REPOSITORY` (400) **before** any insert |
| AC-112.5 | Invalid `params` → `INVALID_PARAMS` (400), **no** database trace (AC13) |
| AC-112.6 | Insert snapshots `params`/`agent_version`/`max_runtime_seconds`/`grace_seconds`/`start_timeout_seconds` explicitly; never relies on defaults; fails rather than writing an unresolvable row (OQ3) |
| AC-112.7 | `InvokeAgentRuntime` throw → run marked `failed_to_start` with an `error_code`, returns `502` with `run_id`, no reaper wait (AC12) |
| AC-112.8 | Credential failure → `CREDENTIALS_UNAVAILABLE` (500), distinct from `INVOCATION_FAILED` (502) |
| AC-112.9 | `tests/fixtures/agent-invocation-payload.json` asserted by the panel Layer 1 test **and** a new Python `validate_payload` test (SR4) |
| AC-112.10 | `prompt`-wrapper requirement confirmed by observation, recorded (OQ2) |
| AC-112.11 | Every invoke logs `run_id`/`agent_slug`/`repository_full_name`/`credentialSource()` as structured JSON |

### S-113 acceptance criteria (from the story)

| AC | Requirement (observable) |
| --- | --- |
| AC-113.1 | `/agents/[slug]/invoke` renders a centered §5.4 dialog with slug, schema-driven field list, Cancel / Run |
| AC-113.2 | `form.ts` maps `params_schema` to field descriptors; the seeded schema renders `fix_mode`→select, `fail_on_findings`→toggle, `max_fix_attempts`→bounded number, `base_branch`→text, **from the schema alone** (AC11) |
| AC-113.3 | Repository selector renders **separately**, outside params, only when `requires_repository = true`, listing enabled non-archived repos |
| AC-113.4 | Unsupported schema type → **disabled field with a visible "unsupported type" note** (never silent vanish) |
| AC-113.5 | Client Ajv blocks invalid submission; server re-validates; rejected submission leaves **no** `runs` row (AC13) |
| AC-113.6 | `202` → navigate `/runs/[id]`; `502` → also navigate, run shows `failed_to_start` |
| AC-113.7 | Labels/help from schema `title`/`description` (English post-S-103); defaults from `default`/`agents.default_params` |
| AC-113.8 | **AC7 proof:** a second synthetic agent row with a different `params_schema` renders a correct form with **zero code change** |
| AC-113.9 | Errors: inline per field for `INVALID_PARAMS`; banner for `MALFORMED_REPOSITORY`/`CREDENTIALS_UNAVAILABLE`/`DATABASE_ERROR` |
| AC-113.10 | Schema preview toggle shows the raw `params_schema` |

## Test Design Principles

- **Black-box first.** Assertions derive from HTTP responses, database row presence/contents, emitted payloads, and rendered DOM — not internal function structure.
- **Database-observable, not just return-observable.** The invoke handler's central guarantees are about *rows* (present/absent, columns non-null). Every "no DB trace" and "insert-before-invoke" scenario asserts against the row, not only the response body.
- **The insert-before-invoke ordering (D1) is the single highest-value invariant** and gets a dedicated instrument (CT-2), because a handler that passes every isolated assertion can still get the *order* wrong and reintroduce the invisible-failed-launch bug.
- **Cross-language contract via one shared fixture (SR4).** The fixture is the single artifact both suites read; a field renamed on either side fails a test.
- **Determinism.** Randomized/property tactics capture a seed and replay command (§Randomized Tactics).

---

## S-112 — Contract Validation Scenarios

Every scenario runs the route handler with Supabase, STS, and `InvokeAgentRuntime` mocked (component layer) unless marked **[2.5]** (local stack) or **[live]** (deployed runtime).

| ID | Scenario | AC | Positive/Negative | Assertion |
| --- | --- | --- | --- | --- |
| CT-1 | Valid `{ repository_id, params }` for an enabled agent + enabled repo | 112.1 | + | `202`, body `{ run_id, status: "queued" }`, `run_id` is a uuid |
| CT-2 | **Ordering instrument** — record the call sequence via mock spies | 112.2 | + | The Supabase `insert` mock is called **before** the STS/`InvokeAgentRuntime` mock; a variant that invokes first fails this test (falsifiability check: temporarily reorder → red) |
| CT-3 | `buildAgentPayload` output shape | 112.3 | + | Emits exactly `run_id`, `repository_org`, `repository_name`, `base_branch`, `params`; `repository_id` key **absent**; matches the shared fixture |
| CT-4 | Malformed `full_name` matrix (see EC-1) | 112.4 | − | `400 MALFORMED_REPOSITORY`; **zero** `runs` rows written (insert mock never called) — security-negative #4 |
| CT-5 | `params` violating schema (`additionalProperties`, wrong type, missing required `fix_mode`) | 112.5 | − | `400 INVALID_PARAMS`; **zero** `runs` rows — security-negative #3 |
| CT-6 | Snapshot completeness | 112.6 | + | The inserted row has `max_runtime_seconds`/`grace_seconds`/`start_timeout_seconds` = the agent's **3600/120/300**, `agent_version` = `agents.version`, `params` = validated params, `triggered_by = "panel"` |
| CT-6b | **OQ3 negative** — inject a run-insert that omits `grace_seconds` | 112.6 | − | Either the builder refuses (preferred) or the row would carry **60** not **120**; the test asserts the builder sends all three explicitly so the silent-default path cannot occur |
| CT-7 | `InvokeAgentRuntime` throws after a successful insert | 112.7 | − | Row transitions `queued → failed_to_start` with an `error_code`; response `502` carries `run_id`; reaper not involved |
| CT-8 | Credential provider throws (STS/OIDC) | 112.8 | − | `500 CREDENTIALS_UNAVAILABLE`, distinct code from the `502 INVOCATION_FAILED` of CT-7; assert the two are not conflated |
| CT-9 | Unknown or disabled agent slug | 112.1 | − | `404`; zero rows |
| CT-10 | Disabled or archived repository | 112.1 | − | `400`; zero rows |
| CT-11 | `DATABASE_ERROR` — insert fails at PostgREST | 112.5 | − | `500 DATABASE_ERROR`; the returned body does **not** contain the Postgres error code (it is logged, not returned) |
| CT-12 | **[2.5]** Successful invoke against local stack (AgentCore mocked) | 112.6 | + | Exactly **one** `runs` row, all three timeout snapshots non-null and equal to the seeded agent values |
| CT-13 | **[2.5]** Rejected invoke against local stack | 112.5 | − | **Zero** `runs` rows after an `INVALID_PARAMS` rejection |
| CT-14 | **Cross-language contract** — shared fixture consumed by TS (`buildAgentPayload` emits it) and Python (`validate_payload` accepts it) | 112.9 | + | Both pass; a mutation (drop `run_id`, rename `repository_org`→`org`, nest under `payload`) fails **at least one** side — SR4 |
| CT-15 | Structured log line per invoke | 112.11 | + | Log carries `run_id`/`agent_slug`/`repository_full_name`/`credentialSource()`; asserts the payload, token, and STS response are **absent** from logs |
| CT-16 | **[live]** Real invocation `queued → running` | 112.1 / #89 AC1 | + | Against the deployed runtime; **recorded blocked** if undeployed, not passed |
| CT-17 | **[live]** Malformed payload → agent `INVALID_PARAMS` | #89 AC2 | − | Against the deployed runtime; recorded blocked if undeployed |
| CT-18 | **[live]** `prompt`-wrapping observation | 112.10 / OQ2 | n/a | Record whether `InvokeAgentRuntime` required a `prompt` wrapper; write back to spec. Recorded blocked if undeployed |

---

## S-113 — Contract / Component Scenarios

Component layer with `next/navigation` and the S-112 route mocked, unless **[2.5]**.

| ID | Scenario | AC | +/− | Assertion |
| --- | --- | --- | --- | --- |
| CT-19 | Seeded schema → four controls | 113.2 | + | `fix_mode` renders a `<select>` with options `audit_only`/`llm_fix`; `fail_on_findings` a toggle; `max_fix_attempts` a number input with `min=0 max=5`; `base_branch` a text input — derived from schema only, no hardcoded field name (grep guard: no literal `"fix_mode"` string in a JSX conditional) |
| CT-20 | **AC7 proof** — second synthetic schema (e.g. a `string` + a different `enum`) | 113.8 | + | Renders correct controls with **zero code change**; falsifiability: a hardcoded `dependency-update` field list would render wrong controls here |
| CT-21 | Unsupported type (`oneOf`, nested `object`, `array`) | 113.4 | − | Renders a **disabled** field + visible "unsupported type" note; the parameter is present in the DOM, not dropped |
| CT-22 | Repository selector visibility | 113.3 | + | Rendered separately when `requires_repository = true`; hidden when false; lists only enabled non-archived repos |
| CT-23 | Client Ajv blocks invalid submit | 113.5 | − | Submit disabled/blocked on invalid params; the S-112 route mock is **not called** |
| CT-24 | Success navigation | 113.6 | + | `202` from route → `router.push('/runs/<id>')` + `SuccessState` renders the run ID |
| CT-25 | Failure navigation | 113.6 | − | `502` → still navigates to `/runs/[id]` (where the run shows `failed_to_start`) |
| CT-26 | Error rendering split | 113.9 | − | `INVALID_PARAMS` → inline per-field messages; `MALFORMED_REPOSITORY`/`CREDENTIALS_UNAVAILABLE`/`DATABASE_ERROR` → a banner |
| CT-27 | Labels/defaults from schema | 113.7 | + | Field labels are the English `title` values; `max_fix_attempts` prefilled `3`, `base_branch` prefilled `main`, `fix_mode` `audit_only` |
| CT-28 | Schema preview toggle | 113.10 | + | Toggling shows the raw `params_schema` JSON |
| CT-29 | **[2.5]** Synthetic agent row → form route renders its fields | 113.8 | + | Insert a synthetic agent into the local stack; the route renders its schema's controls; state live-or-skipped (#134) |
| CT-30 | Dialog structure | 113.1 | + | Centered dialog, agent slug shown, Cancel + Run actions present, two-column grid |

---

## Edge-Case Catalog

Categorized per `activity-edge-case-refinement`. Each maps to a scenario or adds one.

### Input domain — `full_name` splitting (S-112, security-negative #4)

- **EC-1** matrix, all → `MALFORMED_REPOSITORY`, zero rows: `"noslash"`, `"/name"` (empty org), `"org/"` (empty name), `"a/b/c"` (multiple slashes), `""` (empty), `"   "` (whitespace), `" / "` (whitespace halves), `"org/ "` (trailing whitespace-only half). Feeds CT-4.

### Input domain — `params` (S-112 CT-5, S-113)

- **EC-2** `params: {}` against required `fix_mode` → `INVALID_PARAMS`, zero rows.
- **EC-3** `additionalProperties` present (`{ fix_mode: "audit_only", rogue: 1 }`) → `INVALID_PARAMS` (schema is `additionalProperties: false`).
- **EC-4** `fix_mode: "invalid_enum"` → `INVALID_PARAMS`.
- **EC-5** `max_fix_attempts` **bounds**: `0` valid, `5` valid, `-1` rejected, `6` rejected, `3.5` rejected (integer). Both client (S-113) and server (S-112) must agree — shared Ajv.
- **EC-6** wrong type (`fail_on_findings: "yes"` string) → `INVALID_PARAMS`.

### State transition (S-112)

- **EC-7** `queued → failed_to_start` on `InvokeAgentRuntime` throw (CT-7) — the row must not remain `queued`.
- **EC-8** STS succeeds then AgentCore throws → row ends `failed_to_start`, not `queued`, not `running`.
- **EC-9** insert succeeds, `session_id`/`runtime_invocation_id` update fails → run is still `queued`/live with a recorded log; the launch is not lost.

### Timing / idempotency (S-112)

- **EC-10** concurrent double-submit of the same form → **two** runs, **two** `run_id`s (no idempotency claim in v1); assert no unique-constraint crash, two distinct rows.
- **EC-11** `run_id` collision (astronomically unlikely, but the DB has a PK) → surfaces as `DATABASE_ERROR`, not a silent overwrite.

### Auth / permissions (S-112)

- **EC-12** `repository_id` for a repo under a **different** installation than the agent expects → rejected before invoke, zero rows.
- **EC-13** agent row missing `runtime_arn` → clear failure (not a null-ARN call to AgentCore).

### Data boundaries (S-112 OQ3 — the correctness trap)

- **EC-14** agent seeded values 3600/120/300 must appear **verbatim** in the inserted `runs` row (CT-6). A builder that lets `grace_seconds` default to 60 writes a row the reaper evaluates against a 60s grace instead of 120s.
- **EC-15** an agent whose `max_runtime_seconds` is somehow null/absent → the insert fails loudly (the column has no default), never writes a partial row.

### Form / schema mapping (S-113)

- **EC-16** empty `params_schema` `{}` → zero fields, submit still valid (agent tolerates absent params).
- **EC-17** `required` field with no `default` → rendered, submit blocked until filled.
- **EC-18** missing `title` on a property → label falls back to the key name.
- **EC-19** zero enabled repositories with `requires_repository = true` → selector empty state, submit blocked.
- **EC-20** very long `enum` list → renders without layout break (select scrolls).
- **EC-21** disabled agent slug on the form route → `404`.
- **EC-22** unsupported type in an otherwise-valid schema → the *rest* of the form still renders; only that field is the disabled note (CT-21 completeness).

### Injection / untrusted content

- **EC-23** `base_branch` containing shell/markup (`"main; rm -rf"`, `"<script>"`) → passes through as a plain string value (the agent treats it as a branch name; the panel does not interpret it) — assert it is not executed or rendered as HTML on the form.

---

## Randomized / Property Tactics

Per `activity-random-test-tactics`. Seed captured, replay command recorded in the PR.

- **RT-1 (S-112, property)** — for any `full_name` **not** matching `^[^/]+/[^/]+$`, the handler returns `MALFORMED_REPOSITORY` and writes zero rows. Generate random strings; seed logged. Replay: `pnpm run test:unit -- payload --seed=<n>`.
- **RT-2 (S-112, property)** — for any `params` object rejected by Ajv, **zero** `runs` rows exist afterward. Ties security-negative #3 to a generated corpus, not just the hand-picked EC-2..EC-6.
- **RT-3 (S-113, property)** — for any schema built from the supported type set (`enum`/`boolean`/bounded-`integer`/`string`), `form.ts` produces exactly one descriptor per property and never throws; unsupported types always yield the disabled note. Round-trips against generated schemas.
- **Failure triage** (per verifier protocol): on a random failure, capture seed + minimized input, confirm deterministic reproduction, classify (spec gap → `product-engineer`; impl defect → `developer`; flaky → `inconclusive` after ≤3 retries).

---

## Traceability Matrix

### S-112 (#125)

| AC | Positive test(s) | Negative/edge test(s) | Layer |
| --- | --- | --- | --- |
| 112.1 | CT-1 | CT-9, CT-10 | component |
| 112.2 | CT-2 | (falsifiability reorder) | component |
| 112.3 | CT-3, CT-14 | — | unit |
| 112.4 | — | CT-4, EC-1, RT-1 | unit/component |
| 112.5 | — | CT-5, CT-11, CT-13, EC-2..EC-6, RT-2 | unit/component/2.5 |
| 112.6 | CT-6, CT-12 | CT-6b, EC-14, EC-15 | component/2.5 |
| 112.7 | — | CT-7, EC-7, EC-8 | component |
| 112.8 | — | CT-8 | component |
| 112.9 | CT-14 | (mutation cases) | unit (TS+Py) |
| 112.10 | CT-18 | — | live (or blocked) |
| 112.11 | CT-15 | — | component |

Every S-112 AC maps to ≥1 positive and ≥1 negative/edge test. ✅

### S-113 (#126)

| AC | Positive test(s) | Negative/edge test(s) | Layer |
| --- | --- | --- | --- |
| 113.1 | CT-30 | — | component |
| 113.2 | CT-19 | EC-22 | component |
| 113.3 | CT-22 | EC-19 | component |
| 113.4 | CT-21 | EC-22 | component |
| 113.5 | CT-23 | EC-2..EC-6, EC-5 bounds | component |
| 113.6 | CT-24 | CT-25 | component |
| 113.7 | CT-27 | EC-16, EC-18 | component |
| 113.8 | CT-20, CT-29 | (hardcoded-field falsifiability) | component/2.5 |
| 113.9 | — | CT-26 | component |
| 113.10 | CT-28 | — | component |

Every S-113 AC maps to ≥1 positive and ≥1 negative/edge test. ✅ (113.9 is inherently negative-path; its "positive" is the correct-routing assertion within CT-26.)

---

## Execution Checklist

1. **S-112 first** (serialization point). Write CT-3/CT-4 unit tests and the shared fixture before the handler (test-first). Commit the fixture; add the Python `validate_payload` test (CT-14) so `make validate` runs both sides.
2. Implement handler; run CT-1..CT-11, CT-15 (component) and EC-1..EC-13 (unit/component).
3. Run **[2.5]** CT-12/CT-13 against the local stack; **state live-or-skipped** (#134).
4. Run RT-1/RT-2 with recorded seeds.
5. Live CT-16/CT-17/CT-18 against the deployed runtime **or** record blocked (do not mark passed).
6. **S-113 after S-112 merges.** Write CT-19/CT-20 (`form.ts` mapping) before components. Run CT-19..CT-30, EC-16..EC-23, RT-3.
7. Run **[2.5]** CT-29; state live-or-skipped.
8. Quality gates both branches: `pnpm run lint`, `format:check`, `typecheck`, `test`, `audit`, then `make validate`.

---

## Flagged Gaps (need the most independent scrutiny)

- **G1 — Live checks are the real proof of #89, and they may be unrunnable.** CT-16/CT-17/CT-18 (and OQ2) depend on a deployed AgentCore runtime. The mocked contract test (CT-14) proves the *shape* matches, but only a live round-trip proves `InvokeAgentRuntime` accepts it (including the `prompt`-wrapping question). If the runtime is undeployed at implementation time, #89 closes on **inference + shared-fixture**, not observation. Record this explicitly; do not let the mocked green stand in for the live green. (Same discipline S-111 applied to AC8/OQ1.)
- **G2 — Layer 2.5 skip-to-green** (#134): CT-12/CT-13/CT-29 skip green when Docker is down. A skipped integration suite is **not** evidence for AC-112.6 (the OQ3 snapshot correctness) or AC-113.8. Each story must state which ran live.
- **G3 — The ordering instrument (CT-2) is the plan's most falsifiable-by-construction test and its weakest if written lazily.** Asserting "insert was called" is not enough; it must assert insert was called **before** invoke. Recommend a shared call-order spy and a deliberate reorder-to-red check in review.
- **G4 — OQ3 silent-default (CT-6b/EC-14) is a correctness trap a passing suite can miss.** The row is *valid* either way; only comparing the snapshot to the agent's 3600/**120**/300 catches a `grace_seconds`-defaults-to-60 regression. This assertion must compare exact values, not just non-null.
- **G5 — Shared Ajv strictness drift (S-113 CT-23 ↔ S-112 CT-5).** Client and server must reject the *same* inputs. If they compile Ajv differently, a param the client accepts could be server-rejected (or worse, vice versa). Recommend one shared `lib/schema/ajv.ts` instance and a test that runs the **same** invalid-params corpus through both.
- **G6 — Reduced independence (whole plan).** Authored under the `product-engineer` seat, not an independent `verifier`. A genuine `verifier` Design-Mode pass over this plan is recommended before treating coverage as assured.

## Output Contract

- **Mode/phase:** Design Mode, Phase 4 complete (test plan authored).
- **Source artifacts:** user stories v1.2 (S-112/S-113), wave-4 task plan, spec §13/§4/§15, `main.py:74/149`, `seed.sql:71-104`, `runs` DDL.
- **Output file:** `workstream/test-plan-wave4-S-112-S-113.md`.
- **AC coverage:** S-112 11/11 covered; S-113 10/10 covered.
- **Traceability:** every AC → ≥1 positive + ≥1 negative/edge, mapped above.
- **Blocking gaps:** none block *planning*; G1 (live checks) and G2 (2.5 skip) are runtime-dependent and must be reported as blocked-not-passed at execution.
- **Reduced-independence caveat:** recorded (G6).
