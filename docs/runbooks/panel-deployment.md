# Operator Runbook — Panel deployment, privacy gate, and OIDC probe (Issue #128 / S-115)

> **Audience:** the human operator with (a) a Fly.io account/org that can create and deploy
> apps and set secrets, and (b) AWS credentials that can register an OIDC identity provider,
> create/modify an IAM role and trust policy, and (once deployed) be assumed by the Fly app to call
> `bedrock-agentcore:InvokeAgentRuntime`.
>
> **Why this runbook exists — these steps CANNOT be done by the developer agent.** They perform
> **live, hard-to-reverse actions** against shared cloud state: registering an AWS OIDC IdP, creating
> IAM roles/trust policies, setting production Fly secrets, deploying a public-facing platform app,
> and running a real (billable, DB-writing) agent invocation. Each is gated on **explicit operator
> execution**. The committable artifacts (Dockerfile, `fly.toml`, the privacy release gate + its
> tests, the `next build` fix) are already merged on the S-115 branch; this runbook is the
> procedure + evidence log for the live half.
>
> **No secret material is ever printed here.** Do not paste tokens, STS responses, assumed-role
> credentials, or service-role keys into this file. Record only names, ARNs, claim *shapes* (key
> names, not values), timestamps, and run ids.

| Field | Value |
|-------|-------|
| Issue | [#128](https://github.com/llipe/dev-tasks-agent-fleet/issues/128) (Story S-115) |
| Depends on | S-114 (#127) merged — E2E green against the local stack |
| Fly app | `dt-agent-fleet-panel` (see `panel/fly.toml`) |
| Region | AWS `us-east-1`; Fly primary region `iad` |
| Supabase project | `hegxeycmbmjfgzqpdiik` (dev-tasks-agent-fleet) — the deployed panel reads this project |
| Runtime ARN | `arn:aws:bedrock-agentcore:us-east-1:755641879575:runtime/dependencyupdate_dependency_update-UsQc5U5Yz0` (authoritative: `supabase/seed.sql` `agents.runtime_arn`) |
| Agent slug | `dependency-update` |
| Closes | AC8 (no static keys, live), spec **OQ1** (OIDC socket shape + `sub` normalization), **OQ2** (`prompt` wrapping — already observed, see #89), **SR2** (privacy as a release gate) |

---

## 0. Preconditions

- [ ] S-114 (#127) is merged to `main`.
- [ ] The **agent runtime is deployed** (spec §15 ordering). The live invocation (§6) needs it to
      exist. If it is not deployed, deploy it first (agent-side runbook `issue-77-deployment-e2e.md`).
- [ ] Local tooling: `flyctl` (authenticated: `fly auth whoami`), `aws` CLI (authenticated:
      `aws sts get-caller-identity`), `docker` (for a local image sanity build, optional), `node`.
- [ ] The committable S-115 artifacts are present on the branch: `panel/Dockerfile`,
      `panel/.dockerignore`, `panel/fly.toml`, `scripts/verify-fly-private.sh`,
      `panel/scripts/fly-privacy-check.mjs`.

**The panel image builds and boots locally** (developer-verified, reversible sanity check — safe to
re-run):

```bash
docker build -f panel/Dockerfile -t dt-panel:local .     # from the repo root
docker run --rm -p 18080:8080 \
  -e SUPABASE_URL=http://example.invalid -e SUPABASE_SERVICE_ROLE_KEY=x \
  dt-panel:local          # expect: "✓ Ready" on 0.0.0.0:8080, then Ctrl-C
docker rmi dt-panel:local
```

---

## Impl Step 2 — AWS OIDC IdP + IAM role (task 1.9) · **[LIVE / CONFIRM]**

> **Effect:** creates a durable AWS OIDC identity provider trusting Fly, and an IAM role the Fly app
> can assume. Reversible (`delete-open-id-connect-provider`, `delete-role`) but affects the AWS
> account. Run only against the intended account.

1. **Register Fly as an OIDC IdP** (once per AWS account). The Fly OIDC issuer is
   `https://oidc.fly.io/<org-slug>`. Confirm the issuer for your org from Fly's docs / token, then:

   ```bash
   ORG_SLUG='<your-fly-org-slug>'
   aws iam create-open-id-connect-provider \
     --url "https://oidc.fly.io/${ORG_SLUG}" \
     --client-id-list "sts.amazonaws.com"
   ```

   Record the returned **provider ARN** in the evidence table below. (The audience
   `sts.amazonaws.com` matches `STS_AUDIENCE` in `panel/lib/aws/credentials.ts`.)

2. **Create the IAM role with a scoped trust policy.** The trust policy must trust the app's `sub`
   pattern (`<org>:<app>:*`) — the exact normalized claim string is what OQ1's §5 probe confirms.
   Start from the assumed shape and correct it after the probe if AWS normalizes `sub` differently.

   ```jsonc
   // trust-policy.json — federated web-identity, scoped to the app's sub
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Effect": "Allow",
       "Principal": { "Federated": "<OIDC_PROVIDER_ARN>" },
       "Action": "sts:AssumeRoleWithWebIdentity",
       "Condition": {
         "StringEquals": { "oidc.fly.io/<org-slug>:aud": "sts.amazonaws.com" },
         "StringLike":   { "oidc.fly.io/<org-slug>:sub": "<org>:dt-agent-fleet-panel:*" }
       }
     }]
   }
   ```

   ```bash
   aws iam create-role \
     --role-name panel-agentcore-invoke \
     --assume-role-policy-document file://trust-policy.json \
     --max-session-duration 3600
   ```

   > **`--max-session-duration` MUST be ≥ 900** — the panel requests `DurationSeconds: 900`
   > (`credentials.ts`). 3600 is the AWS default and safely above 900. Record the value (task 1.15).

3. **Attach a least-privilege inline policy — only `InvokeAgentRuntime` on the runtime ARN, never
   `*`:**

   ```jsonc
   // invoke-policy.json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Effect": "Allow",
       "Action": "bedrock-agentcore:InvokeAgentRuntime",
       "Resource": "arn:aws:bedrock-agentcore:us-east-1:755641879575:runtime/dependencyupdate_dependency_update-UsQc5U5Yz0"
     }]
   }
   ```

   ```bash
   aws iam put-role-policy \
     --role-name panel-agentcore-invoke \
     --policy-name invoke-runtime \
     --policy-document file://invoke-policy.json
   ```

   Record the **role ARN** and confirm the resource is the specific runtime ARN (not `*`) in the
   evidence table (task 1.19 / AC2).

---

## Impl Step 3 — Fly secrets (task 1.10) · **[LIVE / CONFIRM]**

> **Effect:** writes production secrets to the Fly app. Reversible (`fly secrets unset`) but live.

1. **Create the app first if it does not exist** (no deploy yet):

   ```bash
   fly apps create dt-agent-fleet-panel        # or `fly launch --no-deploy` from the repo root
   ```

2. **Set only the two required secrets — the Supabase service-role key and the role ARN. No AWS
   access key of any kind (D12/AC8):**

   ```bash
   fly secrets set \
     SUPABASE_SERVICE_ROLE_KEY='<service_role key for hegxeycmbmjfgzqpdiik>' \
     AGENT_RUNTIME_ROLE_ARN='<role ARN from task 1.9>' \
     -a dt-agent-fleet-panel
   # SUPABASE_URL and AWS_REGION are non-secret and live in fly.toml [env];
   # set SUPABASE_URL as a secret too if you prefer not to commit the project URL.
   ```

3. **Assert there is NO AWS key of any kind (AC8/D12):**

   ```bash
   fly secrets list -a dt-agent-fleet-panel
   # Expect the digest list to contain ONLY: SUPABASE_SERVICE_ROLE_KEY, AGENT_RUNTIME_ROLE_ARN
   # (and optionally SUPABASE_URL). It MUST NOT contain AWS_ACCESS_KEY_ID,
   # AWS_SECRET_ACCESS_KEY, or AWS_SESSION_TOKEN.
   ```

   Record the **secret-name list** (names only, never values) in the evidence table (task 1.20 / AC3).

---

## Impl Step 4 — Deploy + privacy gate (tasks 1.11, 1.12) · **[LIVE / CONFIRM]**

> **Effect:** deploys a running app to Fly. Reversible by redeploying the prior image (see Rollback).

1. **Confirm the agent runtime is deployed** (task 1.11 — see Preconditions).

2. **Deploy the panel from the repo root** (the build context is the monorepo root):

   ```bash
   fly deploy -a dt-agent-fleet-panel --config panel/fly.toml
   ```

3. **Run the privacy release gate against the live app (task 1.12 / AC6). The release is only valid
   if this exits 0:**

   ```bash
   scripts/verify-fly-private.sh -a dt-agent-fleet-panel
   # PASS: "[fly-privacy] RELEASE ALLOWED — app is private-only."
   # FAIL (exit 1): a public IP or public service exists → the release is BLOCKED.
   ```

4. **Confirm unreachability from the public internet.** From a network with no Fly WireGuard/6PN
   access, the app must not resolve/serve; from a peered network, reach it via
   `fly proxy 8080:8080 -a dt-agent-fleet-panel` then `curl http://localhost:8080`. Record both
   observations.

---

## Impl Step 5 — OIDC socket probe (tasks 1.13–1.15) · **[LIVE / CONFIRM] — the OQ1 closer**

> This is the only way to close spec **OQ1** (PRD Open Question #5): the real OIDC socket response
> shape and AWS's normalized `sub` claim cannot be learned from docs.

1. **Probe the socket on a live Machine** using the command embedded in `credentials.ts`:

   ```bash
   fly ssh console -a dt-agent-fleet-panel
   # inside the Machine:
   curl --unix-socket /.fly/api -X POST http://localhost/v1/tokens/oidc \
        --data '{"aud":"sts.amazonaws.com"}'
   ```

   **Record the JSON response SHAPE only** — the key names, not the token value. The panel's
   `extractOidcToken` accepts a string `value` or `token` field and throws `FlyOidcShapeError`
   (naming the keys received) for anything else (the F5 fix). Confirm which key carries the token.

2. **Record AWS's normalized `sub` claim.** After the first successful assume-role (or from the OIDC
   token's decoded `sub`), record the exact `sub` string AWS matched against the trust policy
   `StringLike` (e.g. `<org>:dt-agent-fleet-panel:<machine-or-*>`). This is what the trust policy
   condition must match.

3. **Compare to SD9 and correct code ONLY if reality differs (task 1.14):**
   - If the socket returns `{"value": "<token>"}` (or `{"token": ...}`) and `sub` matches the
     assumed `<org>:<app>:*` pattern → **no code change.** Record "matches SD9" with the evidence.
   - If the shape differs (different key, or `sub` normalized differently) → correct
     `panel/lib/aws/credentials.ts` (`extractOidcToken` and/or the trust policy pattern),
     re-run `pnpm --filter panel run test:unit`, and commit the correction.

4. **Confirm `DurationSeconds: 900 ≤ MaxSessionDuration` (task 1.15 / AC5).** The role was created
   with `--max-session-duration 3600` (§2). Confirm the assume-role at 900 succeeds; a
   `ValidationError` on `DurationSeconds` would mean the role's max is < 900 — a clear, recorded
   failure to fix by raising `--max-session-duration`.

---

## Impl Step 6 — Live end-to-end invocation (task 1.16) · **[LIVE / CONFIRM] — AC8**

> **Effect:** starts a real agent run (billable; writes to the production Supabase project).

From the deployed panel UI (over the private network via `fly proxy`), invoke
`dependency-update` against a real enabled repository (e.g. `fix_mode: audit_only`), and observe in
Supabase SQL (project `hegxeycmbmjfgzqpdiik`):

```sql
select id, status, started_at, error_code from runs where id = '<run_id>';
```

- **PASS (AC8):** the run flips `queued → running` with `started_at` set, and the log tails live in
  the browser (exercises S-110 SSE in production, PRD AC6). Record the run id + timestamps.
- On the deployed panel, the invoke logs `credentialSource(): "fly-oidc"` (the Fly branch ran) — this
  is the live confirmation that AWS access came from OIDC → STS, no static keys (AC8/D12).

---

## OQ2 — `prompt` wrapping (task 1.17 / AC9): already settled by live observation

**No new action required.** OQ2 was closed on **2026-09-06** against the deployed runtime: the panel
sends **bare inner JSON** (`panel/lib/aws/invoke.ts`, no `prompt` wrapper), and a bare-sent payload
reached `running` while a malformed bare payload was rejected `INVALID_PARAMS` under the
`missing_fields` classification (never the `wrapper_only` "appears double-wrapped" branch, which a
12-hour log sweep shows has never fired). Full procedure + evidence:
[`issue-89-live-verification.md`](issue-89-live-verification.md). If the S-115 live invocation (§6)
surfaces any residual, record it here; otherwise cite #89.

---

## Live service-role smoke read (spec v1.4 SR9 mitigation)

The production service-role SELECT path is currently proven **by inference** (the hosted project
carries Supabase platform-default grants absent from the canonical migration). While on the deployed
panel, confirm a real read returns rows (e.g. load `/` and confirm the dashboard renders seeded
agents, or run a service-role `select count(*) from runs`). Record the observation — this upgrades
the read path from inferred to live-asserted.

---

## Rollback

The panel is **stateless** — rollback is redeploying the prior image:

```bash
fly releases -a dt-agent-fleet-panel                 # find the prior release version
fly deploy -a dt-agent-fleet-panel --image <prior-image-ref>   # or `fly releases rollback`
```

No database or migration rollback is involved (S-115 makes **no** schema/data change).

---

## Which Supabase project does each environment target? (SR7 / R7)

| Environment | Supabase project | Notes |
|-------------|------------------|-------|
| Deployed panel (Fly) | `hegxeycmbmjfgzqpdiik` (hosted) | `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` set as Fly secrets/env |
| Local dev / E2E | Local Supabase CLI stack (`supabase start`) | `panel/.env.local` points at `127.0.0.1:54321`; never the hosted project for tests |

> **R7 live risk:** local dev *can* be pointed at the hosted project (e.g. for the #89 live-invoke
> check), which mixes test runs with production data. Keep `.env.local` on the local stack except
> during a deliberate, recorded live check.

---

## Evidence log — fill in during execution

| Task | AC | Item | Evidence (names/ARNs/timestamps only — no secrets) | Result |
|------|----|------|-----------------------------------------------------|--------|
| 1.4/1.5 | AC1 | `Dockerfile` + `fly.toml` committed; no `[http_service]`/public ports; SR2/D16 comment | committed on `story/S-115-fly-deploy-oidc`; image builds + boots (developer-verified) | ☐ |
| 1.9 | AC2 | OIDC IdP provider ARN | | ☐ |
| 1.9 | AC2 | IAM role ARN; policy resource = runtime ARN (not `*`) | | ☐ |
| 1.10 | AC3/AC8 | `fly secrets list` — names only; NO AWS key present | | ☐ |
| 1.12 | AC6 | `verify-fly-private.sh` exit 0 against live app | | ☐ |
| 1.12 | AC6 | app unreachable from public net; reachable via `fly proxy` | | ☐ |
| 1.23 | AC6 | gate **observed failing** on a deliberately public service, then reverted | | ☐ |
| 1.13 | AC4 | OIDC socket response shape (key names) | | ☐ |
| 1.13 | AC4 | normalized `sub` claim string | | ☐ |
| 1.14 | AC4 | `credentials.ts` matches SD9 (no change) / corrected | | ☐ |
| 1.15 | AC5 | `DurationSeconds 900 ≤ MaxSessionDuration` (value) | | ☐ |
| 1.16 | AC8 | live run `queued → running`; run id + timestamps; live log tail | | ☐ |
| 1.16 | AC8 | deployed panel logs `credentialSource(): fly-oidc` | | ☐ |
| 1.17 | AC9 | OQ2 — cite #89 (settled 2026-09-06) or record residual | see `issue-89-live-verification.md` | ☑ (via #89) |
| — | SR9 | live service-role smoke read returns rows | | ☐ |

### AC6 fail-demonstration (task 1.23) — how to observe the gate failing live

To prove the gate actually blocks (not just that it passes), deliberately misconfigure, observe the
failure, then **revert immediately**:

```bash
fly ips allocate-v4 -a dt-agent-fleet-panel        # allocate a PUBLIC v4 (temporary!)
scripts/verify-fly-private.sh -a dt-agent-fleet-panel   # EXPECT exit 1 — release BLOCKED
fly ips release <the-allocated-v4> -a dt-agent-fleet-panel   # REVERT
scripts/verify-fly-private.sh -a dt-agent-fleet-panel   # EXPECT exit 0 again
```

Record both the failing and the reverted-passing runs. (The unit test
`panel/tests/unit/fly-privacy-check.test.ts` already demonstrates the same failure deterministically
on fixtures — this live demo confirms it against real `fly` output.)
