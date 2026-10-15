# ADR-008: The Auth Chokepoint Moves to `proxy.ts` on the Node.js Runtime

## Status

Accepted

## Context

The panel's single authorization chokepoint shipped (Story S-117, ADR-007) as
`panel/middleware.ts`: a fail-closed Next.js middleware that classifies every
non-static request, verifies identity with Supabase `getClaims()` (never
`getSession()`), and either passes through (threading refreshed cookies on the
one response object), redirects a UI request to `/login` (302), or returns a JSON
`401` for an API/SSE request. The S-153 scheduler added an `internal` class:
`/api/internal/**` callers (pg_cron via pg_net) are **not** session-gated — the
chokepoint declines the session check and lets the request reach the handler,
which enforces its own fail-closed, constant-time shared secret. The auth gate is
the panel's security boundary (ADR-007); the auth **release gate**
(`scripts/verify-panel-auth.sh`, checks 1–5) proves that boundary on every deploy,
check 5 being the live unauthenticated `/api/internal/**` → 401.

Issue #217 upgrades the panel to **Next.js 16**, which **deprecates `middleware`
in favor of `proxy`**. The file must be renamed `middleware.ts` → `proxy.ts`, and
`proxy` runs on the **Node.js runtime only** — whereas the former `middleware.ts`
declared no `runtime` and therefore ran on **Edge**. The rename is thus also a
runtime change for the one piece of code that is the panel's security boundary.

The Edge → Node move has one subtle consequence beyond the rename: the Edge
runtime imposed an implicit per-request time budget that the Node.js server
runtime does not. The gate `await`s `getClaims()`; today the project's signing
keys are ES256 (local JWKS verification, no network), so a hang is latent, but a
future symmetric-key configuration would make `getClaims()` a network call that
could stall the gate indefinitely under Node with no platform-level deadline.

## Decision

**Rename `panel/middleware.ts` → `panel/proxy.ts` (via `git mv`) and keep every
authorization behavior identical, with one deliberate addition: a bounded,
fail-closed `getClaims()` timeout (D-15).**

Preserved **verbatim** (any difference other than the two below is a regression,
not a change):

1. **Fail-closed.** Any auth error, thrown exception, or missing claims denies.
2. **`getClaims()`, never `getSession()`.** The `auth-no-getsession` grep guard is
   retargeted to name `proxy.ts`, so the ban still holds for the renamed file.
3. **The same `config.matcher`** — the gate runs on everything except Next
   internals and static assets.
4. **The `internal` route-policy branch.** `/api/internal/**` declines the
   session gate and reaches the handler; the chokepoint **never returns a 200 /
   success body** for this class — authorization is the handler's secret check,
   never an open pass. Release-gate **check 5** must still pass after the rename.
5. **SD2.** `proxy.ts` reads only the anon-key cookie-threading client; it never
   imports `lib/supabase/server` (the service-role client).
6. **Cookie threading.** The success path returns the cookie-handler response, so
   a refreshed token reaches the browser (no fresh `NextResponse.next()` — the
   "intermittent logout" trap). The same-origin, no-`0.0.0.0` login redirect
   (built from `nextUrl`, not raw `request.url`) is re-verified under Node.

Changed, deliberately:

- **Runtime: Edge → Node.js.** This is the Next 16 `proxy` requirement, not a
  choice. `proxy.ts` exports both a named `proxy` and a default function (Next 16
  accepts either); it does **not** export a route-segment `runtime` config —
  Next 16 forbids route-segment config in a proxy file because proxy is always
  Node.
- **A bounded `getClaims()` timeout (D-15).** The gate races `getClaims()` against
  a **5 s** timeout (injectable for tests, default `DEFAULT_GETCLAIMS_TIMEOUT_MS`).
  On timeout the gate fails **closed** exactly like an auth error — UI → 302
  `/login`, API/SSE → 401 — restoring the bounded, fail-closed behavior the Edge
  platform budget used to provide implicitly. The timer is always cleared on
  settle (resolve, reject, or timeout) so no open handle is left behind.

The existing gate suites (`proxy-gate` — renamed from `middleware-gate`,
`auth-route-policy`, `auth-no-getsession`, `internal-secret`) pass with only
target/name changes plus the new timeout tests. The E2E `auth.spec.ts` is the
end-to-end acceptance that the runtime move preserved behavior.

## Consequences

**Positive**

- The panel is on Next 16, clearing the two moderate `next <15.5.27` advisories
  handed over by #252, with the security boundary's behavior proven unchanged by
  the retargeted gate suites, the route-level image smoke test, and the live
  release gate (checks 1–5, check 5 = the internal boundary).
- The gate is no longer at the mercy of an unbounded auth call on the Node
  runtime: a hung `getClaims()` now denies within 5 s instead of stalling.

**Negative / accepted**

- The gate runs on the Node.js runtime (more memory/startup than Edge), accepted
  as the required cost of the Next 16 `proxy` convention. The panel already runs
  its full server on Node in the Fly image, so there is no new runtime surface.
- The 5 s timeout is a fixed default; if a legitimate slow-but-valid auth call
  ever exceeded it the user would be bounced to `/login` (fail-closed, recoverable
  by re-login) rather than hang. Accepted — fail-closed is the correct posture for
  the security boundary, and ES256 local verification is far under the bound.

## Alternatives considered

- **Keep the file named `middleware.ts`.** Rejected — Next 16 deprecates the
  `middleware` convention; `proxy` is the supported chokepoint.
- **No `getClaims()` timeout (rely on `try/catch` only).** Rejected (D-15) — the
  Node runtime removes the implicit request budget Edge provided, so a hung call
  could stall the gate; a bounded, fail-closed race restores the guarantee.
- **Pin an explicit `runtime` export.** Rejected — Next 16 forbids route-segment
  config in a proxy file (`next build` errors); proxy is implicitly Node.

## References

- Issue #217; refinement `workstream/issue-217-nextjs-16-node-upgrade-refinement.md`
  (AC2, AC8), decisions D-03, D-10, D-12, D-15, D-16.
- Precedent: ADR-007 (the auth boundary / release gate), which this preserves.
- `panel/proxy.ts`, `panel/lib/auth/route-policy.ts`,
  `panel/lib/supabase/auth-middleware.ts`, `panel/lib/auth/internal-secret.ts`,
  `panel/tests/component/proxy-gate.test.ts`,
  `panel/tests/unit/auth-no-getsession.test.ts`,
  `scripts/verify-panel-auth.sh` (check 5), `docs/runbooks/panel-deployment.md`.
