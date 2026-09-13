# Fidelity Report — Issue #172 (Audit Mode / grey-box)

## Header / Verdict

- **Overall fidelity: HIGH**
- **Highest drift impact present: Minor**
- **Scope:** issue #172 · PR #180 · branch `issue/172-publishable-api-keys` · commits `83bb495`, `2dfad89`
- **Mode:** Audit (grey-box) — codebase diff + `/workstream` artifacts + test suite + issue/refinement intent
- **Gate posture:** additive, **non-blocking**. Drift below does not block completion.

---

## Human-readable summary — what changed and why

The panel used to authenticate browser users with Supabase's classic `anon` JWT
key. Supabase now treats that key as **legacy** and recommends a new
**publishable** API key that can be created, named, and revoked individually
(the old key can only be rotated by busting every session project-wide). This
change moves the panel's login/session client onto the new key, while leaving
the server's data-reading client completely untouched.

It does this **without a flag day**: the code now looks for the new
`NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` first, and if it's not set, quietly falls
back to the old `NEXT_PUBLIC_SUPABASE_ANON_KEY` and logs a one-time "this is
deprecated, please switch" warning. Only if **neither** is present does startup
fail with a clear, named error. That means local machines, CI, and the deployed
app can each switch to the new key on their own schedule; nothing breaks in the
meantime. The release safety gate was likewise taught to accept **either** key
name (it only ever checks that a *name* is present, never a value). Docs — the
panel README, the deployment runbook, and the `.env` guidance — now describe the
publishable key as preferred and the anon key as a temporary legacy fallback,
and the runbook adds a step to revoke the old key after cutover.

Two things were deliberately **not** changed, and both were verified: the
server's service-role data client (`server.ts`) is **byte-for-byte identical**
to before, so the security boundary that keeps the powerful server key out of
the browser is provably intact; and no dependency needed upgrading, because the
installed Supabase libraries already understand the new key format. There is no
database or data-model change.

Bottom line: the delivered work matches the requested intent closely. Everything
the issue asked for is present, tested, and passing. The only observations are
cosmetic/housekeeping notes (below), none of which affect behavior or security.

---

## Per-AC result table

| AC | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
|----|-------------|-------------------|---------------------|---------------|--------|
| AC1 | `readAuthEnv()` resolves publishable first → legacy anon fallback w/ one-time deprecation → `AuthConfigError` if neither | `auth-env.ts` L84–107: publishable → anon (guarded `console.warn`) → throw; URL still validated first | Refinement "Proposed approach"; tasks 1.1/1.9 | `tests/unit/auth-env.test.ts` (11 tests: prefer / both-present / fallback-warns-once / blank-handling / neither→throw). Ran live: **11/11 pass** | **Pass** |
| AC2 | `browser.ts` / `auth-server.ts` consume the resolved publishable key | `browser.ts` L28 `const { url, publishableKey } = readAuthEnv()`; `auth-server.ts` L53 same; both pass `publishableKey` to `@supabase/ssr` | tasks 1.2/1.10 | Layer 2.5 `auth-login.test.ts` sets `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` and exercises sign-in + cookie round-trip via `getClaims()` (ran live 4/4 per evidence) | **Pass** |
| AC3 | Auth-release gate accepts EITHER publishable or legacy anon name (names only, SD2 preserved) | `panel-auth-check.mjs`: `CLIENT_KEY_ENV_NAMES` + `REQUIRED_AUTH_ENV_GROUPS` "either-of"; `checkEnvNames` group-satisfaction; still names-only/fail-closed | tasks 1.3/1.12; refinement approach | `panel-auth-check.test.ts` (41) + `panel-auth-check-cli.test.ts` (5). Ran live: **46/46 pass**, incl. explicit "legacy anon name" + "both present" cases | **Pass** |
| AC4 | `server.ts` BYTE-UNCHANGED; SD2/D15 boundary intact; no publishable/secret key crosses client/server line | `git diff --exit-code origin/main...HEAD -- panel/lib/supabase/server.ts` → **clean** (verified this audit). `auth-env.ts` reads only `NEXT_PUBLIC_*`; no service-role name touched | task 1.11; "Server-client invariant" | Existing SD2 guards unchanged (`import "server-only"` in `server.ts`/`auth-server.ts`) | **Pass** |
| AC5 | Env wiring + docs prefer new name; anon documented as legacy | `playwright.config.ts` (publishable→anon→server fallback chain), `global-setup.ts`, `auth-login.test.ts`, `.env.local` guidance, `verify-panel-auth.sh` all prefer publishable; `README.md` env table + `panel-deployment.md` checklist #6 + env-delivery note + revoke step | tasks 1.6/1.7/1.8/1.13 | README/runbook diffs reviewed this audit; E2E 19/19 per evidence | **Pass** |
| AC6 | No dependency bump; migration opt-out documented (no schema/data change) | No `package.json`/lockfile change in diff | tasks 1.14/1.15; "Compatibility note" (`@supabase/ssr` 0.12.7 / `supabase-js` 2.114.0 already support publishable keys); "Migration opt-out" section | `audit` green per evidence (no advisory ≥ high) | **Pass** |

**AC coverage: 6/6 covered, 6/6 Pass. No uncovered ACs.**

---

## Drift catalog

All drift below is **non-blocking to completion.**

### D1 — `.env.local` carries a live anon-role JWT under the new publishable name
- **Impact:** Minor · **Intent:** Intended (pre-existing local-dev artifact)
- **Evidence:** `panel/.env.local` L48 sets `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=<anon-role JWT>`; the file is **gitignored and untracked** (`git check-ignore` confirms; not in the branch diff). The value is a local project's RLS-bound anon-role key, not a secret, and is **not committed**.
- **Note:** No values-committed violation; SD2 preserved. This just reflects that the local CLI stack only issues an anon-role key, carried under the new name to exercise the publishable-first path. Fully consistent with the refinement's stated approach. No action needed.

### D2 — `REQUIRED_AUTH_ENV_NAMES` back-compat export still lists only the anon name
- **Impact:** Minor · **Intent:** Intended (documented back-compat shim)
- **Evidence:** `panel-auth-check.mjs` L65 keeps `REQUIRED_AUTH_ENV_NAMES = [URL, "NEXT_PUBLIC_SUPABASE_ANON_KEY"]` for importers, while the canonical check moved to `REQUIRED_AUTH_ENV_GROUPS` (either-of). The live `checkEnvNames` path uses the groups, so gate behavior is correct; only the retained legacy export names anon.
- **Note:** A follow-up could drop this shim when the anon fallback is removed. No behavioral effect. → `product-engineer`/`developer` follow-up (fallback-removal release).

### D3 — One-time deprecation warning is module-scoped, not process-scoped
- **Impact:** Minor · **Intent:** Intended (matches "one-time" as specified)
- **Evidence:** `legacyFallbackWarned` is a module-level guard (`auth-env.ts` L61). The tests deliberately `vi.resetModules()` to observe the first warn. In a long-lived process the warning fires once, as intended; the caveat is only that a module reload would re-arm it — irrelevant in production.
- **Note:** Matches AC intent ("one-time deprecation warning"). No action needed.

### D4 — Two untracked stray " 2" copy files in the working tree (unrelated to #172)
- **Impact:** Minor · **Intent:** Unintended (pre-existing, flagged by the implementer)
- **Evidence:** `panel/scripts/fly-privacy-check 2.mjs` and `panel/tests/unit/fly-privacy-check-cli.test 2.ts` — accidental copies of S-115 files S-122 removed. Untracked, not staged, not in the diff. The task list already flags them under "Untracked-artifact note."
- **Note:** Housekeeping cleanup outside this issue's scope. → `developer` cleanup, separate from #172.

---

## Edge-case & randomized outcomes

No Design-Mode test plan exists for this scope, so no separate edge-case/randomized suite was run. Edge coverage is nonetheless present in the delivered unit tests: blank/whitespace key handling, both-names-present precedence, blank publishable → anon fallback, both-blank → throw, malformed URL, and the `fly secrets list` table-parse leading-`│`/space cases in `panel-auth-check.test.ts`.

---

## Recommendations (per drift item)

| Item | Suggested next step |
|------|---------------------|
| D1 | No action needed (untracked, non-secret, intended). |
| D2 | `developer`: drop `REQUIRED_AUTH_ENV_NAMES` shim in the fallback-removal follow-up release. |
| D3 | No action needed (matches intent). |
| D4 | `developer`: delete the two stray " 2" files as housekeeping, outside #172. |

None of the above blocks PR/issue completion. Existing quality gates (`test`/`lint`/`format:check`/`typecheck`/`audit`) remain the completion gates and are reported green.

---

## Independent verification performed this audit

- `git diff --exit-code … server.ts` → **clean** (AC4 confirmed, not merely trusted).
- Re-ran `tests/unit/{auth-env,panel-auth-check,panel-auth-check-cli}.test.ts` under Node v22.23.2 (nvm) → **57/57 pass**.
- Read `auth-env.ts`, `browser.ts`, `auth-server.ts`, `panel-auth-check.mjs`, `playwright.config.ts`, `global-setup.ts`, `auth-login.test.ts` and both doc diffs directly.
- Confirmed `panel/.env.local` is gitignored/untracked (no committed key value).
- Not independently re-run this audit (accepted from delivery evidence): full `pnpm run validate` (957/49-skip), `pnpm run build`, `pnpm run test:e2e` 19/19, live Layer 2.5 `auth-login` 4/4, coverage_gate PASS.
