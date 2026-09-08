# Fidelity Report — S-115 (Fly Deployment, Privacy Release Gate, OIDC Probe)

## 1. Header / Verdict

- **Overall fidelity: HIGH** (committable half faithfully implements its ACs; live half is a documented, complete operator procedure — the expected state)
- **Highest drift impact present: Minor**
- **Scope:** Issue #128 / Story S-115 · PR #154 · branch `story/S-115-fly-deploy-oidc` · repo `llipe/dev-tasks-agent-fleet`
- **Mode:** Audit (grey-box). Migration: **N/A opt-out — legitimate** (no schema/data/API-table change; verified in the diff).

> This story has two halves by design. The **committable half** (config, privacy gate, `next build` fix, docs) is delivered and audited in the codebase. The **live half** (`fly deploy`, AWS OIDC IdP + IAM role, Fly secrets, live socket probe, live invocation) is **BLOCKED on operator** — it performs irreversible shared-cloud actions an agent cannot execute, and is documented as an operator procedure with a fill-in evidence log. Live ACs are reported **Pending-operator, not Fail.**

---

## 2. Human-Readable Summary ("what changed and why")

S-115 makes the panel deployable to Fly.io as a **private-only** app and turns "the app must not be public" from a hope into an enforced release gate. This matters because the panel has no login in v1 — the *only* thing stopping anyone from invoking agents is that the app isn't reachable from the public internet. If a future deploy quietly added a public address, that protection would vanish silently. So this work adds a script that inspects the live Fly app after every deploy and **fails the release** if it finds any public IP or public service, plus a committed Fly config that has no public entry points at all and a banner explaining why.

Everything that can be built and checked without touching live cloud infrastructure is done and verified: the production container image, the private Fly config, the privacy gate (with 25 automated tests that watch it correctly *reject* a public setup), a one-line fix that unblocks the production build, CI wiring, and a thorough operator runbook. The build now compiles cleanly.

The other half — actually deploying, wiring up AWS trust, setting secrets, and running one real end-to-end invocation — cannot be done by an automated agent (it needs cloud credentials and makes changes that are hard to undo). Those steps are written up as an exact, copy-paste operator procedure with an evidence table to fill in. That is the intended, expected state of this PR, not a gap in the work. No passwords, keys, or tokens were written into any committed file or the runbook.

---

## 3. Per-AC Result Table

| AC | Description | Codebase evidence | Runbook/Workstream evidence | Result |
|----|-------------|-------------------|-----------------------------|--------|
| AC1 | `Dockerfile` + `fly.toml` committed; `fly.toml` has no `[http_service]`/public ports + SR2/D16 comment | `panel/Dockerfile`, `panel/fly.toml` present; **no `[http_service]`, no `[[services]]`, no public ports** — confirmed by read; 22-line SR2/D16 banner present | Runbook §0 records image builds + boots | **Pass** |
| AC2 | Fly OIDC IdP in AWS; IAM role trusts `<org>:<app>:*`, grants only `bedrock-agentcore:InvokeAgentRuntime` on runtime ARN (never `*`) | n/a (live) | Runbook Impl Step 2: exact `aws iam` commands; trust policy scoped to `sub` `<org>:dt-agent-fleet-panel:*`; **invoke policy Resource is the specific runtime ARN, not `*`** — verified | **Pending-operator** |
| AC3/AC8 | Supabase service-role key is a Fly secret; `fly secrets list` contains **no** AWS key of any kind | n/a (live) | Runbook Impl Step 3: sets only `SUPABASE_SERVICE_ROLE_KEY` + `AGENT_RUNTIME_ROLE_ARN`; **explicit assertion `fly secrets list` MUST NOT contain `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_SESSION_TOKEN`** — verified | **Pending-operator** |
| AC4 | OIDC socket shape + normalized `sub` recorded; `credentials.ts` corrected iff reality differs from SD9 | `credentials.ts` **not modified** (correct — probe not yet run; SD9 stands) | Runbook Impl Step 5: `curl --unix-socket /.fly/api` probe; decision procedure "matches SD9 → no change / differs → correct + re-run test:unit" | **Pending-operator** |
| AC5 | `DurationSeconds: 900` ≤ role `MaxSessionDuration` | n/a (live) | Runbook Step 2 creates role `--max-session-duration 3600`; Step 5.4 confirms 900 assume-role succeeds; mismatch → recorded failure | **Pending-operator** |
| AC6 | Release check asserts no public IP/service and **fails the release** if present; demonstrated failing | `scripts/verify-fly-private.sh` (fail-closed) + pure parser `panel/scripts/fly-privacy-check.mjs`; **25 tests pass** (`fly-privacy-check.test.ts` 21 + `fly-privacy-check-cli.test.ts` 4) observing `private:false`/exit 1 on public-IP, shared-v4, public-v6, and public-service fixtures, and fail-closed on unreadable input | Runbook AC6 fail-demonstration block (allocate v4 → exit 1 → revert) for live confirm | **Pass-at-unit-level** (live fail-demo Pending-operator) |
| AC7 | `README.md` documents private-app requirement as a **precondition** | `panel/README.md` "Deployment precondition — the app MUST be private (SR2 / D16)" section replaces the old placeholder | — | **Pass** |
| AC8 (live) | One real invocation `queued → running` against deployed runtime, log tailing live | n/a (live) | Runbook Impl Step 6: invoke procedure + SQL check + `credentialSource(): fly-oidc` confirmation; evidence rows in log | **Pending-operator** |
| AC9 | OQ2 (`prompt`-wrapping) settled by observation and recorded | `invoke.ts` sends bare JSON (no wrapper) | Runbook OQ2 section cites #89 (settled 2026-09-06, `wrapper_only` branch never fired); evidence log row ☑ | **Pass** |
| AC10 | Local dev works unchanged with SSO profile (`credentialSource()` local branch, no AWS env keys) | Local branch unit-covered by S-111 `credentials.test.ts` | Runbook / README "Local SSO verification" procedure; live SSO run Pending-operator | **Pass-at-unit-level** (live SSO run Pending-operator) |

**Coverage:** 10/10 ACs addressed. 4 fully Pass, 2 Pass-at-unit-level, 4 Pending-operator. **No AC is Fail.**

---

## 4. Deep-Check Findings (the six the caller flagged)

1. **`fly.toml` private-only?** ✅ Verified. No `[http_service]`, no `[[services]]`, no public ports. SR2/D16 rationale present as a prominent banner comment explaining the boundary and that allocating a public IP/service MUST fail the gate.
2. **Privacy gate actually fails on public exposure + fail-closed?** ✅ Verified at unit + CLI level. `evaluatePrivacy` returns `private:false` on public v4, shared_v4, public v6, and a public service (even with private-only IPs); reports both reasons when both present. The CLI exits `1` (spawned as a real child process). Fail-closed: unknown IP types with a routable address → public; unreadable JSON → `null` → gate blocks. Shell wrapper is fail-closed on `fly` command failure. **"Gate observed failing" evidence is real** (25 passing assertions).
3. **Least-privilege IAM scoped to the specific runtime ARN?** ✅ Verified. Runbook `invoke-policy.json` grants `bedrock-agentcore:InvokeAgentRuntime` on `arn:aws:bedrock-agentcore:us-east-1:755641879575:runtime/dependencyupdate_dependency_update-UsQc5U5Yz0` — the exact runtime ARN, **not `*`**, with an explicit "never `*`" instruction.
4. **Runbook asserts `fly secrets list` has NO AWS key?** ✅ Verified. Impl Step 3 sets only the two required secrets and explicitly asserts the digest list MUST NOT contain any AWS key, naming all three variables.
5. **`parseAfterSeq` move behavior-preserving?** ✅ Verified strongly. Moved to `panel/lib/sse/cursor.ts`; the S-110 route imports it from `@/lib/sse/cursor`; the route now exports only standard Next.js symbols (`dynamic`/`revalidate`/`fetchCache`/`runtime`/`GET`). **`pnpm run build` (`next build`) passes cleanly** — the route-type-validator error is gone. `after-seq.test.ts` re-points to the new path and **passes (5 tests)**. Full unit suite: **549 passed / 4 skipped**.
6. **Secret material leaked?** ✅ None. Diff scan surfaced only a `'<service_role key for ...>'` placeholder and a comment *prohibiting* AWS keys. Runbook explicitly states no tokens/STS responses/credentials are recorded. `.dockerignore` excludes `.env*`; Dockerfile bakes no secrets.

---

## 5. Drift Catalog

All drift is **non-blocking to completion.**

| ID | Description | Impact | Intent | Evidence |
|----|-------------|--------|--------|----------|
| D1 | Live ACs (AC2/AC3/AC4/AC5/AC8/AC10-live-run) unexecuted — deploy, IAM, secrets, probe, invocation pending operator | Minor | **Intended** | Task list marks these `[~] BLOCKED on operator`; runbook is the documented procedure. This is the designed split, not a defect. |
| D2 | Spec §17 (OQ1/OQ2) and PRD §18 not edited in this PR | Minor | **Intended** | Task 1.32 + TG row 1.24 route OQ2 write-back (now, via #89) and OQ1 write-back (after the live probe) to `product-engineer`; OQ1 correctly kept **OPEN** since the probe hasn't run. Correct per meta-rules (verifier/writer don't edit spec directly). |
| D3 | AC6 live fail-demonstration (allocate public v4 → gate blocks → revert) not yet run | Minor | **Intended** | Scripted in runbook AC6 block for operator; deterministically demonstrated at unit/CLI level in the interim. |
| D4 | SR9 live service-role smoke read (added Wave-2 scope on #128) pending | Minor | **Intended** | Runbook "Live service-role smoke read" section; production read path remains proven-by-inference until the operator runs it. Consistent with S-104 audit posture. |

No Critical or Major drift. No Unintended drift. No Undetermined drift.

---

## 6. Recommendations

- **AC2/AC3/AC4/AC5/AC8/AC10-live, D1/D3/D4:** Operator to execute the runbook and fill the evidence log. No agent action possible. → **operator**
- **D2 (OQ2 spec/PRD write-back):** `product-engineer` may write back OQ2-resolved now (via #89); OQ1 write-back waits for the live probe. → **product-engineer**
- **Committable half:** No fixes needed — faithful to ACs, build green, tests green, no secrets. → **no action needed**

---

## 7. Output Contract

- **Mode/phase:** Audit / Phase 4 (Reporting & Publication)
- **Source artifacts:** issue #128 body (10 ACs), `workstream/tasks-prd-agent-fleet-panel-v2-s115-plan.md`, branch `story/S-115-fly-deploy-oidc` diff
- **Files created:** `workstream/fidelity-report-S-115.md`
- **AC coverage:** 10/10 addressed (4 Pass, 2 Pass-at-unit-level, 4 Pending-operator, 0 Fail)
- **Verdict:** Fidelity **HIGH**; highest drift **Minor** (all Intended)
- **Blocking gaps:** none (live ACs are expected pending-operator, not blockers)
- **Verification run:** `pnpm run build` → success; `pnpm run test:unit` → 549 passed / 4 skipped
