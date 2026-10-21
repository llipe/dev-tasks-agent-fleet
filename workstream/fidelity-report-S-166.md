# Fidelity Report — S-166 (#310) Vault signing secret + webhook.config (verifier, Audit Mode)

**Verdict: High fidelity.** All 3 acceptance criteria met. Highest drift impact: **Minor** (one intended design change, plus one pre-existing finding filed elsewhere).

## AC → evidence

| AC | Evidence | Result |
| --- | --- | --- |
| `webhook` schema; Vault wrappers keyed `webhook_endpoint_<id>` | `webhook-vault.test.ts`: round-trip, rotation upserts one row, absent → null, delete, empty value rejected | Pass |
| `webhook.config` seeded `delivery_retention_days=30` + `bot_login`, typed getters | "returns the seeded webhook.config defaults"; invalid value falls back to 30 | Pass |
| No secret in a table column or a log line | "no webhook table has a column that could hold the secret"; `getEndpointSecret` never logs, and its `DatabaseError` message carries no Postgres detail (L1) | Pass |

Task 2.4 (`getEndpointSecret`): L1, 5/5 tests. A mutant that removed the fail-closed check failed 2 of them, so the tests catch that regression.
Task 2.5 (runbook): `docs/runbooks/webhook-deployment.md`, indexed in `docs/runbooks/README.md`. The verification SQL was checked as `postgres`.
Test-plan items covered: CT-10, EC-21 (null secret → fail closed), AC9.

## Drift

| # | Finding | Type | Impact |
| --- | --- | --- | --- |
| 1 | The story said to "mirror `scheduler.read_secret`/`set_secret`". That pattern is safe only because `anon` lacks `USAGE` on the `scheduler` schema. The panel must call into `public` through PostgREST, and a `SECURITY DEFINER` function there that returns a secret would be callable with the anon key. So every webhook function revokes `EXECUTE` from `public`/`anon`/`authenticated` and grants it to `service_role` only. This is checked for all 4 secret functions at the SQL level, and through PostgREST: anon gets `42501`, service role gets 200. | Intended (security) | Minor |
| 2 | While checking that pattern I found that the existing `public` scheduler RPCs (`scheduler_record_fire_failure`, `reap_stale_runs`, `scheduler_preview_next_runs`) are anon-executable through PostgREST (HTTP 204 reproduced with a nonexistent id, so no data changed). This is pre-existing on `main`. Filed as **#357**. | Out of scope | — |
| 3 | `make validate-py` audit still fails on #355 (pre-existing, no Python touched). | Out of scope | — |

## Gates

- L2.5 `webhook-vault.test.ts`: 15/15. It was red before the migration (13 failing). The two tests already passing then were the column check, which is true from S-165, and the anon denial, which only became meaningful once the paired service-role test passed.
- `make validate-js`: pass (1613 tests, lint, format, typecheck, audit).
- `make validate-py`: lint, typecheck and tests pass; audit fails on #355.
