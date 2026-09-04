# Fidelity Report — Story S-111 (issue #124)

## 1. Header / Verdict

- **Overall fidelity verdict:** **High**
- **Highest drift impact present:** **Minor**
- **Scope:** issue #124 "AWS credential provider — Fly OIDC and local chain" · branch `story/S-111-aws-credential-provider` · draft PR #135 → `main`
- **Mode:** Audit (grey-box) · **Result:** all 8 ACs Met or Partially-Met-by-design; no Unintended drift; 36/36 S-111 unit tests pass.

This audit is **additive and non-blocking**. It does not gate PR/issue completion and does not replace the `test`/`lint`/`format:check`/`typecheck`/`audit` quality gates.

---

## 2. Human-Readable Summary — what changed and why

The panel now has a single, self-contained way to get AWS credentials, and it works the same whether the panel runs on Fly.io or on a developer's laptop — with no long-lived secret keys stored anywhere. On Fly, it asks the machine for a short-lived identity token and trades it for temporary AWS credentials; locally, it uses whatever the developer already has configured (SSO, a profile, or environment variables). The calling code never has to know which of the two paths ran.

The most important correction in this story fixes a subtle, dangerous bug (called "F5") in the older reference version. Previously, if the identity service returned an unexpected response, the code would grab the wrong field — the *audience* label `sts.amazonaws.com` — and hand it to AWS as if it were a login token. AWS would then reject it with a confusing "access denied"-style error that looks like a permissions misconfiguration, sending an operator down the wrong troubleshooting path. The new code refuses to guess: it accepts only the two known token fields and, for anything else, fails immediately with an error that lists exactly which fields it *did* receive — turning a multi-hour misdiagnosis into a one-line answer.

A companion piece cleanly separates two different failures so the on-call operator reaches the right runbook: "the panel couldn't get credentials at all" (a 500) versus "the panel had credentials but the agent-invocation call itself failed" (a 502). A thin invocation wrapper was also added (used by a later story) that logs which credential path was active on every call, so permission problems that only appear on Fly can be diagnosed after the fact.

Two things are deliberately **not** finished here and are not defects: the exact shape of Fly's real identity response can only be confirmed by probing a live Fly machine (that happens in S-115), and the guarantee that the credential source is logged on *every* invocation at the web-route level lands with the next story (S-112). Both are contract-defined here and fail loudly if reality differs, which is exactly the intended posture.

---

## 3. Per-AC Result Table

| AC | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
|---|---|---|---|---|---|
| **AC1** | `credentials.ts` exists; branch detection by `FLY_APP_NAME` + socket existence; callers receive only a provider | `credentials.ts` `isFly()` = `Boolean(FLY_APP_NAME) && fs.existsSync("/.fly/api")`; `awsCredentials` is an `AwsCredentialIdentityProvider`; `credentialSource()` exposes branch | Task 3.7, 3.17; test-plan CT (branch) | `credentials.test.ts` "branch detection" ×3 (env+socket, env+no-socket, no-env) | **Met** |
| **AC2** | Fly branch requests `/.fly/api` with `aud=sts.amazonaws.com`, exchanges via `AssumeRoleWithWebIdentity` | `fetchFlyOidcToken` POSTs `{aud}` to `FLY_OIDC_PATH=/v1/tokens/oidc` on socket; `assumeRoleFromFly` sends `AssumeRoleWithWebIdentityCommand` w/ `DurationSeconds: 900` | Task 3.18; test-plan G1 (provider-unverified) | `credentials.test.ts` "Fly branch — OIDC → AssumeRoleWithWebIdentity" asserts socketPath/path/method, `aud`, forwarded token, `DurationSeconds:900` | **Met (contract-defined; provider-unverified — G1/OQ1, expected)** |
| **AC3** | Token extraction accepts `value`/`token` only; else `FlyOidcShapeError` naming keys; `aud` + `data.trim()` fallbacks removed | `extractOidcToken` returns `obj.value`\|`obj.token` (string-typed), else throws `FlyOidcShapeError(Object.keys(obj))`; non-JSON → `FlyOidcShapeError([], "not valid JSON")`; no `aud`, no `data.trim()` | SD9; task 3.6, 3.19; test-plan CT-8 | `credentials.test.ts` accept `value`/`token`, prefer `value`; reject `{aud}` (F5, asserts value not leaked), `{}`, non-JSON, `{value:12345}`, array | **Met** |
| **AC4** | Local branch uses `fromNodeProviderChain()`, no code change between environments | `const localChain = fromNodeProviderChain()`; `awsCredentials` returns `localChain()` when `!isFly()` | Task 3.8, 3.20 | `credentials.test.ts` "local branch" delegates to chain, STS untouched | **Met** |
| **AC5** | In-memory cache w/ 60s refresh margin + single-flight promise | `REFRESH_MARGIN_MS = 60_000`; cache-hit guard `expiration - margin > now`; `inFlight ??= ….finally(() => inFlight = null)` single-flight | Task 3.7, 3.21; test-plan EC-6, EC-7 | `credentials.test.ts` 61s→hit, 59s→miss, two concurrent→1 STS call (`c1 === c2`) | **Met** |
| **AC6** | `credentialSource()` reports active branch and is logged on every invoke | `credentialSource()` returns `fly-oidc`\|`local-chain`; `invoke.ts` `logger.info(... credentialSource=${credentialSource()})` before send | Task 3.11, 3.22; test-plan G5 (route-level in S-112) | `invoke.test.ts` logs on every invoke, reflects both branches; never logs payload | **Partially Met (wrapper boundary only; route-level guarantee in S-112 — G5, expected)** |
| **AC7** | All comments English; `curl` probe command retained | `credentials.ts` header + inline comments all English; `curl --unix-socket /.fly/api …` retained (line 58) | SD9 item 3; task 3.9, 3.23 | File review (`grep curl` → present); no non-English strings observed | **Met** |
| **AC8** | `CREDENTIALS_UNAVAILABLE` (500) distinct from `INVOCATION_FAILED` (502) | `errors.ts`: `CredentialsUnavailableError.status=500`/`code=CREDENTIALS_UNAVAILABLE`; `InvocationFailedError.status=502`/`code=INVOCATION_FAILED`; `FlyOidcShapeError`→500; `invoke.ts` re-throws creds-unavailable as 500, wraps others as 502 | Spec §13 taxonomy; task 3.5, 3.24 | `aws-errors.test.ts` pins both codes/statuses + "not equal"; `credentials.test.ts` CT-9 (AccessDenied/InvalidIdentityToken/network→500); `invoke.test.ts` 500-vs-502 split | **Met (taxonomy). PRD-AC8 "no static AWS keys" live-closes only via S-115 probe — expected deferral)** |

**AC coverage status:** 8/8 covered. No AC is uncovered or blocked. Three ACs carry design-deferred partials (AC2/G1, AC6/G5, AC8/OQ1), all pre-flagged in the test plan and issue DoD.

---

## 4. Drift Catalog

> All drift below is **non-blocking to completion.**

| # | Description | Impact | Intent | Evidence source(s) |
|---|---|---|---|---|
| **D1** | `@aws-sdk/*` "shared minor" is literal-vs-actual mismatched. The task plan (3.2, DoD line 236) states the four packages are pinned "**all to the same minor**"; delivered pins are three clients at `3.1126.0` (minor `1126`) but `@aws-sdk/types` at `3.974.5` (minor `974`) — not the same minor. The **substantive** goal — one deduplicated `@smithy/core` — is met (`@smithy/core@3.33.3` single version in `pnpm-lock.yaml`). `@aws-sdk/types` tracks an independent, slower release cadence, so a byte-identical minor across all four is not generally achievable; the plan wording overstates the achievable invariant. | **Minor** | **Intended** | Code: `panel/package.json`; lockfile grep (`@smithy/core@3.33.3` only); workstream: `tasks-…-wave2-plan.md:108` (records actual) vs `:195`/`:236` (states "same minor") |
| **D2** | Env var renamed `AWS_ROLE_ARN` → `AGENT_RUNTIME_ROLE_ARN`, diverging from the reference stub's name. | **None** | **Intended** | Code: `credentials.ts` reads `AGENT_RUNTIME_ROLE_ARN`; `.env.example:27` matches; called out explicitly in the audit brief as intentional |
| **D3** | AC2 Fly-OIDC socket response shape and `sub` normalization are asserted against a mocked socket, not a live Fly Machine. | **None** (expected) | **Intended** | Test-plan G1/OQ1; issue #124 DoD ("AC8 remains blocked on S-115 / OQ1 — recorded, not silently passed"); code comment at `assumeRoleFromFly`/`extractOidcToken` |
| **D4** | AC6 "logged on every invoke" is verified at the `invoke.ts` wrapper only; the route-level guarantee (and the 500-vs-502 route mapping) lands in S-112. | **None** (expected) | **Intended** | Test-plan G5; `invoke.ts` module comment; task 3.24/3.25 |

No **Unintended** drift and no **Critical/Major** drift was found. Delivered behavior matches spec SD9, §13, §9.1, and the issue #124 ACs.

---

## 5. Edge-Case & Randomized Test Outcomes

Mapped against `test-plan-wave2-S-104-S-105-S-111.md` S-111 scenarios (all present and green):

| Scenario | Intent | Observed |
|---|---|---|
| CT-8 (token extraction accept/reject shapes) | Reject all non-token shapes incl. F5 `{aud}` | Pass — `{aud}` throws, audience value never returned/leaked |
| CT-9 (STS failure → `CREDENTIALS_UNAVAILABLE`) | AccessDenied/InvalidIdentityToken/network all 500 | Pass — all three map to 500, never 502 |
| EC-6 (single-flight) | 2 concurrent cold calls → 1 STS call | Pass — `stsSend` called once, `c1 === c2` |
| EC-7 (refresh-margin clock skew) | 59s→miss, 61s→hit | Pass — both boundaries asserted |
| EC-10 (socket refused / HTTP 500) | Loud `CREDENTIALS_UNAVAILABLE`, no silent local fallback | Pass — asserts `localChainProvider` not called |
| EC-11 (missing role ARN) | Named startup error, not invoke-time auth error | Pass — `/AGENT_RUNTIME_ROLE_ARN is not set/` |
| Secret-in-logs (§13) | No token/STS material in any console output | Pass — asserts `super-secret-jwt`/`STS_SECRET`/`STS_SESSION` absent |

No randomized/fuzz tests are in scope for S-111; none were required by the plan. **Coverage gate** (from brief): PASS, `lib/aws` 97.44% stmts.

---

## 6. Recommendations (no change applied by this audit)

| Item | Suggested next step |
|---|---|
| D1 — "same minor" wording vs `@aws-sdk/types` cadence | **`product-engineer` (drift-reconciliation):** soften the task/DoD wording from "all to the same minor" to the achievable invariant — "three clients on one shared minor + a single deduplicated `@smithy/core`" — so the checkbox at plan line 236 is not perpetually literally-false. Minor doc-hygiene, non-blocking. |
| D3 (AC2/OQ1), D4 (AC6/G5), AC8 live-close | **No action needed in S-111.** Confirm S-115 (#128) carries the live Fly-socket probe (OQ1, PRD-AC8) and S-112 (#125) carries the route-level AC6 + 500/502 mapping tests. Both are already scheduled; this audit records them as expected deferrals, not gaps. |
| AC7 English-comment check | **No action needed.** Verified by inspection; consider a lint rule only if non-English strings become a recurring concern (out of scope). |
| Open sub-task 3.30 | **Process reminder (not a code finding):** PR #135 is still draft and #124 open — correct per the workflow; close only after ready→approve→merge. |

---

## Output Contract

- **Mode / phase:** Audit / Phase 4 (Reporting & Publication)
- **Source artifacts used:** issue #124 (ACs, DoD); spec `specification-prd-agent-fleet-panel-v2.md` SD9, §9.1, §13; `tasks-prd-agent-fleet-panel-v2-wave2-plan.md` task 3.0; `test-plan-wave2-S-104-S-105-S-111.md` (CT-8/9, EC-6/7/10/11, G1/G5); `docs/reference/credentials.ts` (MOVED stub); delivered `panel/lib/aws/{credentials,errors,invoke}.ts` + `tests/unit/{credentials,invoke,aws-errors}.test.ts`; `panel/package.json`; `pnpm-lock.yaml`; `.env.example`
- **Output file:** `workstream/fidelity-report-S-111.md`
- **AC coverage status:** 8/8 covered (0 uncovered, 0 blocked)
- **Overall fidelity verdict / highest drift impact:** High / Minor
- **Blocking gaps:** none
