## What

Implements Story **S-114** — a Playwright end-to-end suite for the panel plus CI hardening that makes the Layer 2.5 integration suites **gating** in CI. Delivers two issues in one PR because both edit the CI workflow around the local-stack lifecycle:

- **#127** — Playwright E2E against the local Supabase stack (7 scenarios, AgentCore stubbed at the network boundary).
- **#134** — make Layer 2.5 integration suites gating in CI (a Docker-gated skip becomes a hard failure in CI via `REQUIRE_LOCAL_DB=1`).

## Why

E2E is the only composition layer — every other layer mocks at least one boundary. S-114 exercises invoke → run detail → live tail through the real UI and the real database. #134 is what makes a green CI trustworthy: today the Layer 2.5 suites skip vacuously when Docker is absent, so a "green" run may have asserted nothing about the DB boundary.

## How

- Playwright config filled in: single worker (shared DB), `retries: 0` (determinism), headless in CI / headed locally, `webServer` builds+starts the panel on port 3100 with the local Supabase env + the AgentCore stub endpoint.
- `global-setup.ts` resets the DB to the seeded baseline (`supabase db reset`), polls readiness (no fixed sleeps), and starts an HTTP-boundary AgentCore stub so the real credential branch runs but no AWS call leaves the machine.
- Deterministic per-scenario seed/reset helpers; no cross-scenario order dependence.
- `panel/tests/integration/db.ts` honors `REQUIRE_LOCAL_DB=1`: a probe failure or Docker-gated skip becomes a hard failure in CI; local behavior (unset) unchanged.
- `.github/workflows/ci.yml` starts the local stack + applies migrations/seed before the JS/TS test branch, then runs the gated integration suites and E2E.
- Both negative demonstrations (broken `effectiveStatus` → red via `status-parity`; `anon` granted `select` → red via `rls-deny-all`) are performed once and recorded.

## Testing

- `pnpm run test` (unit + component), `pnpm run test:integration` (Layer 2.5, live), `pnpm run test:e2e` (7 scenarios), `make validate` at the repo root (both branches).
- Scenario → PRD-AC traceability table in `TESTING.md`.

## Checklist

- [ ] E2E suite green against the local stack (AgentCore stubbed at the network boundary — no real AWS call)
- [ ] Scenario → AC mapping complete and non-vacuous
- [ ] Layer 2.5 suites gating in CI; both negative demos recorded
- [ ] Local `make validate` without Docker still succeeds with a recorded skip reason
- [ ] `TESTING.md` updated (CI-vs-local skip policy + scenario table)
- [ ] Quality gates: test / lint / format:check / typecheck / audit

## Migration

N/A — no schema/data-model change (documented opt-out). CI *applies* existing migrations; it authors none.

Closes #127
Closes #134
