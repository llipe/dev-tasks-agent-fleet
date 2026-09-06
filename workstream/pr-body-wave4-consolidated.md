## Wave 4 — the invocation wave (S-112 + S-113)

Consolidated PR from `integration/wave4-invoke` → `main`. Wave 4 is the first time the panel *writes* to the database and reaches across the panel→agent boundary.

Closes #125
Closes #126
Closes #89

### Execution plan (as delivered)

| Seq | Story | Issue | Story PR | Result |
| --- | ----- | ----- | -------- | ------ |
| 1 | S-112 Invoke route handler + agent payload translation | #125 | #141 | ✅ merged to integration |
| 2 | S-113 Schema-driven invoke form | #126 | #142 | ✅ merged to integration |

S-112 was the serialization point (S-113 submits to its route and shares `lib/schema/ajv.ts`), so they ran strictly sequentially.

### Delivered scope

**S-112 — invoke route + payload contract (closes #89)**
- `POST /api/agents/[slug]/invoke` in the normative D1 order: resolve agent → resolve repo → Ajv-validate params → generate `run_id` → split `full_name` → **insert `queued` run** → invoke → update refs.
- `buildAgentPayload` emits exactly `run_id`/`repository_org`/`repository_name`/`base_branch`/`params`, never `repository_id`.
- `failed_to_start` written on invoke throw with `502` carrying `run_id` (AC12); `CREDENTIALS_UNAVAILABLE` (500) distinct from `INVOCATION_FAILED` (502).
- All three timeout snapshots explicit (OQ3); `triggered_by = "panel"` (SD7).
- Shared cross-language fixture (`tests/fixtures/agent-invocation-payload.json`) asserted by both the TS and Python suites (SR4).

**S-113 — schema-driven invoke form**
- `/agents/[slug]/invoke` renders the DESIGN §5.4 dialog entirely from `params_schema` (`buildFieldDescriptors`).
- Client Ajv shares strictness with the route; server authoritative.
- 202/502 navigate to `/runs/[id]`; inline vs banner errors; schema preview; unsupported types render disabled with a note.
- `ajv` bumped 8.17.1 → 8.20.0 (residual moderate advisory resolved; audit exit 1 → 0).

### Per-story changed files & tests

See story PRs #141 and #142 for the full AC→evidence tables. Net: 4 new `lib` modules + `lib/schema/*` + the route + 5 invoke components + 1 API route page; 9 new test files (5 unit, 2 component, 2 integration) + the Python fixture test.

### Integration test summary

`make validate` green on **both** branches on the integration branch HEAD:
- Panel: 621 passed / 9 Docker-gated skips.
- Python agent: all gates passed (incl. the new shared-fixture test).
- **Both new Layer 2.5 suites RAN LIVE** against the local Supabase stack (not skipped): `invoke-insert.test.ts` (real queued insert, snapshots non-null, failed_to_start transition) and `synthetic-agent-form.test.ts` (AC7 end-to-end through the DB).

### Wave 4 exit criteria

- [x] Invoke inserts `queued` before contacting AgentCore, all three timeout snapshots explicit (D1, OQ3), marks `failed_to_start` on throw (AC12)
- [x] Invalid `params` and malformed `full_name` rejected before any insert (security-negative #3 and #4), no DB trace (AC13)
- [x] Shared JSON fixture asserted by both TS and Python suites (SR4); **#89 closed with evidence**
- [x] `/agents/[slug]/invoke` renders a schema-driven form, proven by a second synthetic agent row rendering with zero code change (AC7/FR16)
- [x] Client Ajv shares strictness with the server route; server authoritative
- [x] Both routes declare `force-dynamic` inline; no status read from `runs.status` directly
- [x] `ajv` bumped to `>=8.18.0`; `make validate` green on both branches; #125 and #126 merged
- [~] **OQ2 (`prompt` wrapping): recorded BLOCKED** pending the deployed AgentCore runtime (per the S-111 precedent for AC8/OQ1)
- [x] Wave 5 (S-114 E2E → S-115 deploy) is unblocked

### Recorded blocked (deployed-runtime dependent — not silently passed)

- **S-112 AC10 / OQ2** (`prompt`-wrapping observation) and the two **live #89 checks** (`queued → running`; malformed payload → agent `INVALID_PARAMS`) require the deployed AgentCore runtime. Recorded blocked; to be verified during S-115.

### Rollup drift (routed, non-blocking)

- **jsonb key order (S-113):** Postgres `jsonb` does not preserve `params_schema` key order → form field order follows jsonb order, not authoring order. No AC mandates order. Routed to `product-engineer` for a DESIGN §5.4 note.
- **1024px/1440px geometry:** deferred to the S-114 Playwright suite (jsdom computes no geometry), consistent with the wave pattern.

### Migrations

**None.** Both stories write/render only existing schema; opt-out rationale recorded per story (tasks 1.31 / 2.32).
