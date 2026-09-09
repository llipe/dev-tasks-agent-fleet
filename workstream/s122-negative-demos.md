# S-122 / #161 — Auth release gate: both-directions evidence (gate observed passing AND failing)

A gate never observed failing is not a proven gate. The S-122 auth release gate
(`scripts/verify-panel-auth.sh` + `panel/scripts/panel-auth-check.mjs`) replaces
the S-115 privacy gate. This file records that the gate **passes on a correct
deployment** and **fails on each violation** — captured both at unit level
(deterministic fixtures) and against the live wrapper (real `curl` probes to a
local mock standing in for the deployed app). No secret values appear anywhere;
the wrapper prints only names, status codes, and pass/fail reasons.

> Why a mock, not the live Fly app: this story ships the gate and keeps the app
> PRIVATE (fly.toml unchanged except the banner). The live run against the
> deployed private app is a documented operator step (runbook Phase A step 4/5).
> The mock reproduces the four observable outcomes the gate consumes (302/401/200,
> signup accepted/rejected) so both gate directions are demonstrated here now.

---

## Direction 1 — the gate PASSES on a correct deployment

### Unit level (deterministic, `panel/tests/unit/panel-auth-check.test.ts`)

```
✓ evaluateAuthGate — the release-gate verdict (both directions)
  ✓ PASSES on a fully correct deployment fixture
```

Fixture: env names present, protected UI → `302 /login`, SSE → `401`, signup
`{ rejected: true }`. Verdict `pass: true`, `reasons: []`.

### Live wrapper (real `curl` against a correct mock — signups disabled)

Mock: protected path → `302 /login?redirect=…`, SSE → `401`, `/auth/v1/signup` →
`422 signup_disabled`.

```
[panel-auth] (1/4) Collecting auth env-var NAMES (names only, never values)...
[panel-auth] (2/4) Probing protected UI path / (expect 302 -> /login)...
[panel-auth] (3/4) Probing SSE path /api/runs/00000000-…/events/stream (expect 401)...
[panel-auth] (4/4) Attempting a signUp (expect REJECTED — signups must be disabled)...
[panel-auth] OK — auth boundary holds: env names present, protected UI → /login, SSE → 401, signups rejected.
[panel-auth] RELEASE ALLOWED — the auth boundary holds on http://localhost:18099.
WRAPPER EXIT=0
```

---

## Direction 2 — the gate FAILS on each violation

### Violation A — protected UI path returns 200 (gate not enforcing)

Unit fixture `{ ...OK, protectedProbe: { status: 200 } }` →

```
FAIL: pass=false; reason matches /200/
  - Protected UI path returned 200 to an unauthenticated request (gate NOT enforcing).
```

### Violation B — SSE path returns 200 (stream reachable anonymously)

Unit fixture `{ ...OK, sseProbe: { status: 200 } }` →

```
FAIL: pass=false
  - SSE path returned 200 to an unauthenticated request (stream reachable anonymously).
```

### Violation C — a signUp SUCCEEDS (PRD AC17 / R9 — the highest-value check)

Unit fixture `{ ...OK, signupProbe: { rejected: false, createdUserId: "u-1" } }` →

```
FAIL: pass=false
  - A signUp SUCCEEDED — public signups are ENABLED. Release BLOCKED (anyone
    could self-register). Delete the created account.
```

### Violation D — a required env name is missing

Unit fixture `{ ...OK, envNames: ["NEXT_PUBLIC_SUPABASE_URL"] }` →

```
FAIL: pass=false
  - Missing required auth env var name(s) on the app: NEXT_PUBLIC_SUPABASE_ANON_KEY
```

### All four at once — live wrapper against a "bad" mock

Mock: protected → `200 <html>`, SSE → `200 text/event-stream`, `/auth/v1/signup`
→ `200 { id: … }` (a user created), env-name override supplied.

```
[panel-auth]   WARN — a signup account was created but no SUPABASE_SERVICE_ROLE_KEY to delete it; delete it manually.
[panel-auth] FAIL — the auth boundary is NOT proven. The release is BLOCKED.
  - Protected UI path returned 200 to an unauthenticated request (gate NOT enforcing).
  - SSE path returned 200 to an unauthenticated request (stream reachable anonymously).
  - A signUp SUCCEEDED — public signups are ENABLED. Release BLOCKED (anyone could self-register). Delete the created account.
[panel-auth] RELEASE BLOCKED — the auth boundary is NOT proven (see above).
WRAPPER EXIT=1
```

(The `WARN` line shows the signup-cleanup path firing: when a service-role key is
available the created account is auto-deleted via the admin API; here none was
supplied, so it warns to delete manually. The gate FAILS either way — a
successful signup is a release blocker.)

---

## Fail-closed by construction

- **Unreadable/unparseable gate input** → the parser CLI exits non-zero
  (`could not read/parse the gate input JSON (fail-closed)`).
- **Empty object** (no probes collected) → all four checks contribute a reason;
  `pass: false`.
- **Network timeout / unreachable host** → each affected probe reports an error
  and its check fails. Live-verified against an unreachable port:

```
[panel-auth] FAIL — the auth boundary is NOT proven. The release is BLOCKED.
  - Protected-path probe failed to complete: curl: (7) Failed to connect …
  - SSE probe failed to complete: curl: (7) Failed to connect …
  - Signup probe outcome could not be confirmed as a rejection (fail-closed).
WRAPPER EXIT=1
```

- **Redirect to a NON-/login location** → protected-path check fails
  (`redirected to "…", not /login`).
- **401 with an HTML body** → SSE check PASSES (status is authoritative; a 401 is
  a 401 regardless of body) — covered by a dedicated unit case.
- **Unexpected Supabase signup error shape** → signup check fails-closed
  (`outcome could not be confirmed as a rejection`).

## Reproduce

```bash
# Unit (deterministic, both directions):
pnpm --filter panel exec vitest run --project unit panel-auth-check

# Shellcheck the wrapper:
shellcheck scripts/verify-panel-auth.sh          # (or koalaman/shellcheck:stable via docker)

# Live wrapper against a local mock: see the mock servers used above (302/401 +
# 422 signup_disabled for PASS; 200/200 + 200-with-id for the violation set).
```
