# Fidelity Report — S-165 (#309) webhook schema (verifier, Audit Mode)

**Verdict: High fidelity.** All 6 acceptance criteria met. Highest drift impact: **Minor** (2 intended additions, 1 out-of-scope finding routed elsewhere).

## AC → evidence

| AC | Evidence | Result |
| --- | --- | --- |
| Enums `webhook_source`, `webhook_outcome` with the exact values | `webhook-schema.test.ts` "defines the webhook enums…"; `pg_type` check | Pass |
| `webhook_endpoints` columns + defaults + unique token | "applies the documented defaults", "rejects a duplicate url_token" | Pass |
| `webhook_rules` columns, `(endpoint_id, position)` unique, repo_mode CHECK | "rejects a duplicate (endpoint_id, position)", both repo_mode rejections, "accepts repo_mode='fixed'…" | Pass |
| `webhook_deliveries` columns, dedup unique, feed index, run FK set-null | D-W16 block (4 tests), index test, "nulls run_id…" | Pass |
| Deny-all RLS on all three | `relrowsecurity=true`, 0 policies; anon role reads 0 rows while rows exist; shared `rls-deny-all.test.ts` (schema-enumerated) green | Pass |
| `set_updated_at` triggers | "bumps updated_at on update for all three tables" | Pass |

Test-plan items covered here: CT-8, CT-9, EC-8 (token format), EC-12 (rule delete keeps the delivery), I-8 (run FK set-null).

## Drift

| # | Finding | Type | Impact |
| --- | --- | --- | --- |
| 1 | Added constraints beyond the story: token format/length (EC-8), header-name format, length caps on delivery text (R-3), `unauthorized ⇒ dedup_key is null` (D-W16), one default rule per endpoint (FR15), non-negative position/failures, array/object `jsonb` shape. All trace to the spec, test plan, or decisions. | Intended | Minor |
| 2 | `(endpoint_id, position)` is `deferrable initially immediate` for the S-177 reorder. Postgres cannot use a deferrable unique as an `ON CONFLICT` arbiter, so the seed uses `where not exists`. Recorded in the migration comment for S-177. | Intended | Minor |
| 3 | `make validate-py` audit fails on `mcp` 1.29 (CVE-2026-59951, via `strands-agents`). It also fails on `main`, and this story changes no Python. Filed as **#355**. | Out of scope | — |

## Gates

- L2.5: 34/34 S-165 tests; full integration project 198/198 (31 files) after a `db reset` with the new seed.
- `make validate-js`: pass (1591 tests, lint, format, typecheck, audit).
- `make validate-py`: lint/format/typecheck/tests pass (462 + 714); audit **fails on #355** (pre-existing).
- Seed applied twice: 1 endpoint, 1 rule, disabled (idempotent).
