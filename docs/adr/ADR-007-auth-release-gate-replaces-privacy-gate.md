# ADR-007: The Auth Release Gate Replaces the Privacy Release Gate (D16 Reversed)

## Status

Accepted

## Context

In v1 the panel had **no user authentication** (decision D16 / risk R1). Its only
security boundary was network privacy: the Fly app was unreachable from the
public internet, so the unauthenticated agent-invoke surface was never exposed.
Story S-115 mechanized that boundary as a **release gate** — `scripts/verify-fly-private.sh`
(+ the pure parser `panel/scripts/fly-privacy-check.mjs`) ran after every deploy
and **failed the release if the app had any public IP or public service** (SR2 /
AC6). "Privacy is a release gate, not a preference" was an enforceable rule in
`technical-guidelines.md` §6.

The Phase 2 auth wave (S-116…S-122) **reverses D16**: the panel now requires a
Supabase password login. `middleware.ts` is a fail-closed authorization
chokepoint, `/login` is the only public screen, logout is POST-only, and the SSE
route returns `401` to an unauthenticated client. Once authentication exists, the
security boundary that protects the invoke surface is **login**, not network
privacy — and (in the separate Phase B / S-123) the app is intended to go public.

This creates a direct conflict with the shipped mechanical gate: the privacy gate
would **fail the very release that makes the app public**, which is exactly the
outcome the auth wave is designed to enable. The gate is the mechanized form of a
decision that has been reversed.

Two things had to be true for the reversal to be safe:

1. **The mechanical check must never simply disappear.** Deleting
   `verify-fly-private.sh` would leave a release with *no* boundary assertion at
   all — the worst outcome. A boundary that is only a runbook checkbox ("remember
   to require login", "remember to turn signups off") drifts silently, and the
   failure mode is an unauthenticated or self-registerable invoke surface on the
   internet.

2. **The new boundary must be asserted by observation, not by trusting
   configuration.** Auth correctness is not a property of `fly.toml`; it is a
   property of what the *deployed* app actually does to an unauthenticated
   request, and of whether the Supabase project actually rejects a signup.

## Decision

**Replace the privacy release gate with an auth release gate**, keeping the exact
same pure-parser + shell-wrapper split (so the decision logic is unit-testable and
the suite can observe the gate failing on a violation), and keeping the same
**fail-closed** posture (anything not positively confirmed is a failure).

- **Remove** `scripts/verify-fly-private.sh` and `panel/scripts/fly-privacy-check.mjs`
  and re-point their unit tests to the new parser (no dangling test importing a
  deleted module).
- **Add** `panel/scripts/panel-auth-check.mjs` — a pure, no-I/O verdict parser —
  and `scripts/verify-panel-auth.sh` — the live wrapper that probes the deployed
  app at a **hostname argument** (so the same gate runs over the private network
  in Phase A and publicly in Phase B).
- The gate asserts, after deploy:
  1. The auth env-var **names** (`NEXT_PUBLIC_SUPABASE_URL`,
     `NEXT_PUBLIC_SUPABASE_ANON_KEY`) are present on the app — **names only, never
     values**.
  2. An unauthenticated request to a protected UI path returns **302 → /login**,
     not 200.
  3. An unauthenticated request to the SSE path returns **401**, not 200.
  4. An attempted `signUp` for a clearly-marked disposable address is
     **rejected**; a **successful signup fails the release** (PRD AC17 / R9). Any
     account somehow created is deleted.
- CI runs the parser unit tests by name and `shellcheck`s the new wrapper.

**The enforceable rule in `technical-guidelines.md` §6 changes** from "panel
privacy is a release gate" to **"the auth boundary is a release gate, asserted by
observation."** Risk R1 (no authentication) is **resolved**; a new risk R8
(public login endpoint invites brute force) is accepted for v1 (Supabase built-in
rate limiting).

**Scope boundary — the gate is not the go-public action.** S-122 ships the gate
and keeps `panel/fly.toml` **private** (no `[http_service]`, no public IP).
Actually exposing the app is the separate, operator-executed, separately-merged
Phase B (S-123), taken only after the gate passes on the still-private app. This
structural separation (spec §15.1) removes the exposure window (R10): a public app
never exists without a proven gate, and containment is one command
(`fly ips release`).

## Consequences

**Positive**

- The release always has a mechanical boundary check — the check is *replaced*,
  never absent.
- The boundary is proven by **observation on the deployed app**, not by trusting
  `fly.toml` or a dashboard setting. Check 4 in particular converts "remember to
  turn signups off" into a deterministic, falsifiable assertion — the same
  "operator may intend, deterministic check disposes" posture as the ADR-001
  mandate backstop.
- The pure-parser split keeps the verdict logic unit-testable; the suite observes
  the gate passing on a correct fixture and failing on each violation
  (200-on-protected-path, 200-on-SSE, successful signup, missing env,
  fail-closed) — `workstream/s122-negative-demos.md`.
- The same gate works over the private network (Phase A) and publicly (Phase B)
  because it takes a hostname argument.

**Negative / accepted**

- The gate’s live checks require a deployed app and the Supabase anon key + URL in
  the environment; they cannot run in CI (only the pure parser does). This is the
  same "pure logic in CI, live probe by operator" split S-115 accepted.
- The signup check writes to the Auth endpoint (a disposable address) and relies
  on the admin API (service-role key) to delete any account it creates; without
  the service-role key it warns to delete manually. Accepted — the check’s value
  (catching an open signup on a public panel) far outweighs a transient probe
  account.
- A public login endpoint invites credential stuffing / brute force (R8) —
  accepted for v1 with Supabase’s built-in rate limits; revisit with
  lockout/CAPTCHA if abuse appears.

## Alternatives considered

- **Delete the privacy gate, add no replacement.** Rejected — leaves a release
  with no boundary assertion; the boundary would degrade to a runbook checkbox
  that drifts silently.
- **Keep the privacy gate and add auth alongside it.** Rejected — the privacy
  gate would fail the go-public release it now must allow; the two gates directly
  contradict once the app is meant to be public.
- **Assert auth from configuration (parse `fly.toml` / read the Supabase
  setting).** Rejected — auth correctness is a property of the deployed app’s
  behavior, not of a config file; only observation of a real unauthenticated
  request and a real signup attempt proves the boundary.

## References

- Story S-122 (#161); PRD AC17; spec §12.1 (the SR2 inversion), §15.1 (Phase
  A/B ordering), §16 (R8/R9/R10).
- Supersedes the S-115 enforceable rule "panel privacy is a release gate, not a
  preference" (ADR context — that rule’s gate is removed here).
- `panel/scripts/panel-auth-check.mjs`, `scripts/verify-panel-auth.sh`,
  `panel/tests/unit/panel-auth-check.test.ts`,
  `workstream/s122-negative-demos.md`, `docs/runbooks/panel-deployment.md`.
