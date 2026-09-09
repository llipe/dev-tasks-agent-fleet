# Fidelity Report — Story S-122 (issue #161)

## Header / Verdict

- **Overall fidelity: HIGH**
- **Highest drift impact: Minor** (all drift Intended)
- **Scope:** Story S-122 "Auth release gate replacing the privacy gate" · branch `story/S-122-auth-release-gate` · PR #169 (base `integration/v2.1-panel-auth`) · repo `llipe/dev-tasks-agent-fleet`
- **Mode:** Audit (grey-box) — codebase + `/workstream` artifacts + tests + PRD/spec intent
- **Result:** 10/10 audited AC groups **Pass**. Additive/non-blocking to PR completion.

## Human-readable summary (what changed and why)

Until now, the panel's only safety net was that it lived on a private network — a
release check (`verify-fly-private.sh`) refused to ship if the app was ever made
reachable from the internet. The auth wave changes the deal: the panel now has a
real login, so the thing that keeps strangers out is the login, not the network.
That flips the old check on its head — it would have blocked the very release the
team now wants.

S-122 does the right thing: instead of just deleting the old check (which would
leave a release with *no* safety net), it **replaces** it with a new one that
proves the login actually works on the deployed app. The new gate checks four
things by actually poking the running app: the auth config is present (by name
only, never leaking secret values), an anonymous visitor to a real page gets
bounced to `/login`, an anonymous request to the live-log stream is refused
(`401`), and — most importantly — that **strangers cannot sign themselves up**.
That last check is the standout: "remember to turn off public signups" is exactly
the kind of setting that silently drifts, and if it's wrong, anyone on the
internet could register and start running agents against your repositories, so a
successful signup deliberately **fails the release**.

Crucially, this story **does not make the app public** — that is a separate,
deliberately isolated final step (S-123). It ships the gate and keeps the app
private, so a public app can never exist without an already-proven login. The gate
is "fail-closed": if it can't confirm something is safe, it treats that as unsafe.
Both directions were demonstrated — the gate passing on a good setup and failing
on each kind of problem — and the enforceable-rule change is recorded in a new
architecture decision record (ADR-007) plus the technical guidelines.

## Per-AC results

| AC | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
|----|-------------|-------------------|---------------------|---------------|--------|
| 1 | Parser pure/no-I/O + unit-tested; wrapper supplies live inputs, exits non-zero on any failure | `panel/scripts/panel-auth-check.mjs` exported fns (`checkEnvNames`/`checkProtectedRedirect`/`checkSseUnauthorized`/`checkSignupRejected`/`evaluateAuthGate`) are pure; I/O (`readFileSync`) confined to `mainCli()` guarded by `import.meta.url===argv[1]`. `verify-panel-auth.sh` collects live probes, `set -euo pipefail`, `exit "$code"` | Story ACs 1–2; s122-negative-demos §Reproduce | `panel-auth-check.test.ts` (30) + `panel-auth-check-cli.test.ts` (4) — **34 pass** | **Pass** |
| 2 | Gate asserts env NAMES (never values); unauth protected UI → 302 /login not 200; unauth SSE → 401 not 200 | `checkEnvNames` matches names case-insensitively; `checkProtectedRedirect` fails 200, requires 302/307 to `/login`; `checkSseUnauthorized` fails 200, requires 401. Wrapper extracts NAME column only, curl `-H` never echoed | Spec §12.1 checks 1–3 | Unit cases: env-present, 200→fail, non-`/login`→fail, SSE-200→fail, 401→pass | **Pass** |
| 3 | AC17: signUp rejected; a SUCCESSFUL signup FAILS release; disposable marked address + deletes created account; never logs secret values | `checkSignupRejected`: `rejected:true`→pass, `rejected:false`/`createdUserId`→FAIL, unknown→fail-closed. Wrapper uses `panel-auth-gate-probe+<ts>-<pid>@release-gate.invalid`, classifies body via node file-read (never printed), admin `DELETE /auth/v1/admin/users/<id>` when service-role key present | Spec §12.1 check 4; PRD AC17 / R9; Business Rules | Unit: success→fail (`self-register`), CLI signup-open→exit 1 | **Pass** |
| 4 | Fail-closed: unreadable/unparseable/unconfirmable → non-zero (parser + wrapper) | CLI `readJsonOrNull` catch→`exit(1)`; each check fails on `null`/`{}`/error/`null` status; wrapper leaves probes as `{"error":...}` on curl failure, `set -e`, node/curl/parser presence guards | Spec §12.1 check 5; s122-negative-demos §Fail-closed | Unit: garbage→fail, empty-obj→4 reasons, timeout→fail; CLI: garbage + missing file→exit 1 | **Pass** |
| 5 | Old privacy gate removed AND tests re-pointed (no dangling import) | `verify-fly-private.sh`, `fly-privacy-check.mjs`, `fly-privacy-check.test.ts`, `fly-privacy-check-cli.test.ts` all deleted; no code import of removed modules (grep clean; remaining refs are comment/doc mentions only) | Story AC9; ADR-007 | New suites import `@/scripts/panel-auth-check.mjs`; `make validate`/CI green | **Pass** |
| 6 | `fly.toml` remains PRIVATE (no public service/IP) | `panel/fly.toml`: banner "DOES NOT MAKE THE APP PUBLIC"; no `[http_service]`, no `[[services]]` public ports; `[env]` non-secret only | Story AC10; spec §15.1 Phase A | (config; not unit-tested) | **Pass** |
| 7 | CI runs parser unit tests + shellchecks wrapper | `.github/workflows/ci.yml`: `vitest run --project unit panel-auth-check` (matches both new suites); `shellcheck scripts/verify-panel-auth.sh`; old S-115 steps removed | Story AC11 | 34 unit tests pass locally; shellcheck runs on ubuntu CI runner | **Pass** |
| 8 | Both gate directions demonstrated (RED-then-reverted) | — | `workstream/s122-negative-demos.md`: Direction 1 (pass) + Direction 2 (violations A–D + all-four live) + fail-closed set + reproduce commands | Unit `evaluateAuthGate` both-directions block | **Pass** |
| 9 | Enforceable-rule write-back recorded (ADR + guidelines §6/§18 R1 resolved) | `docs/adr/ADR-007-*.md` (Accepted, D16 reversed); guidelines §6 rule replaced, §5 boundary=login, §13 re-pointed, §18 R1→**Resolved** + R8 added, v1.29 changelog | Story DoD | — | **Pass** |
| 10 | Stayed in scope: did NOT make app public (S-123); did NOT touch `lib/supabase/server.ts`, `middleware.ts`, `lib/sse/relay.ts`, `(panel)` group | `git diff --name-only` vs base: **none** of the protected paths appear; fly.toml still private | Story context "does not make the app public" | — | **Pass** |

## Drift catalog

All drift is **Minor / Intended** and **non-blocking** to PR/issue completion.

- **D1 — Env-name check reads only Supabase URL + anon-key names, not the S-122-mentioned "SUPABASE_SERVICE_ROLE_KEY".** `REQUIRED_AUTH_ENV_NAMES` is the two `NEXT_PUBLIC_SUPABASE_*` names. Impact: **Minor**. Intent: **Intended** — spec §12.1 check 1 names exactly those two; the service-role key is used opportunistically for cleanup, not required for the boundary. Evidence: `panel-auth-check.mjs` `REQUIRED_AUTH_ENV_NAMES`. Recommendation: **no action needed**.
- **D2 — Protected-redirect check also accepts `307` (not only `302`).** Spec/AC say "302". Impact: **Minor**. Intent: **Intended** — a 307 to `/login` is still an enforced redirect (not a 200); broadening toward safety, still fails 200 and non-`/login` targets. Evidence: `checkProtectedRedirect` `status !== 302 && status !== 307`. Recommendation: **no action needed** (optionally note in spec §12.1).
- **D3 — Account auto-deletion is best-effort, conditional on `SUPABASE_SERVICE_ROLE_KEY` being present.** If absent, the wrapper WARNs to delete manually (gate still FAILS). Impact: **Minor**. Intent: **Intended** — Business Rule says "delete any account it somehow creates"; deletion needs admin creds, and the release-blocking verdict is unconditional. Evidence: `verify-panel-auth.sh` admin-DELETE branch + WARN fallbacks. Recommendation: **no action needed**.
- **D4 — Live end-to-end run is against a local mock, not the deployed Fly app.** Impact: **Minor**. Intent: **Intended** — story keeps the app private; the live private-network run is a documented operator step (runbook Phase A 4/5). Evidence: `s122-negative-demos.md` "Why a mock". Recommendation: **no action needed** (operator runs it in Phase A).

> Note: the D16/R1 write-back to the **spec §17 / PRD** decision records is
> explicitly routed to `product-engineer` (recorded in the v1.29 changelog row and
> ADR-007), consistent with prior-wave convention — not a defect.

## Edge-case & randomized outcomes

Story's edge-case matrix is covered by named unit cases: redirect-to-non-`/login`
→ fail; 401-with-HTML-body → pass (status authoritative); network timeout →
fail-closed; unexpected Supabase signup error shape → fail-closed; empty output →
4 reasons. No randomized/fuzz tactics in scope for this gate story.

## Recommendations

1. All ACs Pass — **no `developer` remediation required** for this story.
2. `product-engineer`: perform the D16-reversal / R1 write-back into spec §17 / PRD decision records (already routed).
3. Optional (`product-engineer`): note the 307-acceptance and the two-name env list in spec §12.1 for exactness — cosmetic only.
