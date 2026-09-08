# S-114 / #134 — Negative-demo evidence (gates observed failing)

A gate never observed failing is not a proven gate. Both Layer 2.5 gates were
deliberately broken once, observed red under `REQUIRE_LOCAL_DB=1` against the
live local stack, then reverted. Both are green again after revert.

## Demo A — broken `effectiveStatus` → `status-parity.test.ts` red (task 2.4)

Change: inverted the strict comparison in `panel/lib/domain/status.ts` running
branch (`nowMs > thresholdMs` → `nowMs < thresholdMs`).

Observed (reverted after capture):

```
FAIL tests/integration/status-parity.test.ts > effectiveStatus ⇄ v_runs parity > agrees on every status × clock combination (CT-1)
AssertionError: disagreement on "running-fresh" (status=running): sql=running ts=timed_out
  Expected: "running"
  Received: "timed_out"
FAIL tests/integration/status-parity.test.ts > resolves exact-boundary and ±1s rows identically (CT-2)
  running-boundary-959: sql=running: expected 'timed_out' to be 'running'
```

Result: the SD4 SQL/TS parity gate catches a broken derivation. Reverted; suite green.

## Demo B — `anon` can read `runs` → `rls-deny-all.test.ts` red (task 2.5)

Change: added a permissive policy `create policy demo_b_anon_leak on runs for
select to anon using (true)` and seeded one `runs` row (a plain
`grant select ... to anon` alone does NOT leak — RLS deny-all is the gate, not
grants, so the realistic misconfiguration is a permissive policy).

Observed (reverted after capture):

```
FAIL tests/integration/rls-deny-all.test.ts > anon-key client reads zero rows from every base table
AssertionError: table runs leaked 1 row(s) to anon: expected [ {…} ] to have a length of +0 but got 1
FAIL tests/integration/rls-deny-all.test.ts > anon-key client reads zero rows from the v_runs view (EC-14)
AssertionError: v_runs leaked 1 row(s) to anon
```

Result: the RLS deny-all gate catches a policy misconfiguration. Reverted
(`drop policy`, `revoke`, `supabase db reset`); suite green.

## CI-vs-local gate behavior (tasks 2.1 / 2.6)

- `REQUIRE_LOCAL_DB=1` + stack unreachable → all 13 Layer 2.5 files **FAIL**
  (`probeLocalDb` throws — a skip is not evidence in CI).
- gate unset (local) + stack unreachable → all 13 files **skip** with a recorded
  reason; `make validate` stays green without Docker. Verified by pointing
  `SUPABASE_DB_PORT` at a dead port in both modes.
