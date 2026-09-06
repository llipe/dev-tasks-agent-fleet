## Story S-112 (#125): Invoke route handler and agent payload translation

Closes #125
Closes #89

Wave 4, task 1.0. The panel's first database write and first cross-language contract test — the boundary that closes the #89 payload mismatch.

### What this delivers

- `lib/domain/payload.ts` — `buildAgentPayload` emits exactly the agent contract (`run_id`, `repository_org`, `repository_name`, `base_branch`, `params`), never `repository_id`. Authoritative contract: `main.py:74` `_REQUIRED_FIELDS = ("run_id", "repository_org", "repository_name")`.
- `lib/schema/{ajv,validate}.ts` — shared Ajv validation of `params` against `agents.params_schema` with `additionalProperties: false`; validators compiled and cached per agent id + schema hash.
- `lib/domain/run-insert.ts` — the `queued`-row snapshot builder writing all three timeout columns explicitly (OQ3); `triggered_by = "panel"` (SD7).
- `lib/errors.ts` — the `{ error: { code, message, details } }` shape + spec §13 taxonomy, reusing the S-111 AWS codes and S-104 `DATABASE_ERROR`.
- `app/api/agents/[slug]/invoke/route.ts` — `POST` handler in the normative D1 order: resolve → validate → generate → split → **insert `queued`** → invoke → update. Inline route-segment config.
- `tests/fixtures/agent-invocation-payload.json` — shared cross-language contract fixture (SR4), asserted by both the panel unit test and a new Python test in the agent suite.

### Contract / ordering guarantees

- **D1 ordering:** the `queued` `runs` row exists before AgentCore is contacted (unit test asserts `["insert","invoke"]`); an invocation that never starts is a visible `failed_to_start` row (AC12), not an invisible nothing.
- **OQ3:** the insert sends `max_runtime_seconds`, `grace_seconds`, and `start_timeout_seconds` explicitly from the agent snapshot — never relying on schema defaults (asserted live in Layer 2.5).
- **Security-negative #3:** invalid `params` (`additionalProperties`) rejected `INVALID_PARAMS` 400, no `runs` row written.
- **Security-negative #4:** malformed `full_name` rejected `MALFORMED_REPOSITORY` 400 before any insert (full matrix).
- `triggered_by` is the constant `"panel"` (SD7), never an identity.
- `CREDENTIALS_UNAVAILABLE` (500) is distinct from `INVOCATION_FAILED` (502).

### AC → test evidence

| AC | Evidence |
| -- | -------- |
| AC1/AC7 (202, ordering) | `tests/unit/invoke-route.test.ts` — order assertion insert-precedes-invoke |
| AC3/AC4 (payload, malformed full_name) | `tests/unit/payload.test.ts` (19) — security-negative #4 matrix, `repository_id` never present |
| AC5 (INVALID_PARAMS, no insert) | `invoke-route.test.ts` + `schema-validate.test.ts` — security-negative #3 |
| AC6 (snapshot, all timeouts non-null) | `tests/integration/invoke-insert.test.ts` — **RAN LIVE** |
| AC9/SR4 (shared fixture both sides) | `payload.test.ts` + `tests/unit/test_payload_contract_fixture.py` (Python) |
| AC12 (failed_to_start on throw) | `invoke-route.test.ts` + `invoke-route-edge.test.ts` + live integration |
| AC11 (structured logging) | `invoke-route.test.ts` log assertion — never logs the payload |

### Layer 2.5 (#134 discipline)

`tests/integration/invoke-insert.test.ts` **RAN LIVE** against the local Supabase stack (4 tests passing) — not skipped. It writes a real `queued` run, asserts all three timeout snapshots non-null, and asserts the `failed_to_start` transition persists.

### Coverage

`payload.ts` / `run-insert.ts` / `ajv.ts` 100%; `validate.ts` 100% stmts; `errors.ts` ~97-100%; `route.ts` 86% stmts (uncovered = generic-500 and mark-failed DB-error defensive branches). `coverage_gate: PASS`.

### Blocked (deployed-runtime dependent — recorded, not passed)

- **AC10 / OQ2** (`prompt`-wrapping observation) — needs the deployed AgentCore runtime.
- **Live #89 AC1/AC2** (`queued → running`; malformed payload → `INVALID_PARAMS`) — needs the deployed runtime.

These are recorded **blocked** per the wave's S-111 precedent; closed during S-115, not silently passed.

### Migration lifecycle

**Not applicable** — writes only existing columns of `runs`; no schema or data-model change. Opt-out rationale recorded (plan task 1.31).

### Gates

`make validate` green on **both** branches (panel 571 passed / 9 Docker-gated skips; Python all gates passed incl. the new fixture test). `ajv` bump to `>=8.18.0` is S-113 scope (task 2.12).
