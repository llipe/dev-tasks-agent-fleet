# Operator Runbook — Panel deployment, auth release gate, and OIDC probe (auth wave: #128/S-115 + #161/S-122; go-public: #162/S-123)

> **What this runbook now covers.** It began as the S-115 deploy + privacy-gate + OIDC-probe
> procedure. The Phase 2 **auth wave** (S-116…S-122) reversed the original "privacy is the only
> boundary" decision (D16): the panel now requires a Supabase password login, so the security
> boundary is **authentication**, mechanically asserted by the new **auth release gate**
> (`scripts/verify-panel-auth.sh` + `panel/scripts/panel-auth-check.mjs`) that replaced the privacy
> gate. This runbook is the single operator source for:
>
> - **Phase A (private):** deploy the auth build, configure Supabase, and verify the auth boundary
>   over the **private** Fly network — the app stays unreachable from the internet. (S-122 ships the
>   gate; the app remains private.)
> - **Phase B (go public, S-123):** a **separate, operator-executed, separately-merged** step that
>   allocates a public IP and enables a public HTTPS service — done **only** after Phase A passes,
>   behind an explicit confirmation gate, reversible in one command.
>
> The S-115 AWS OIDC IdP / IAM-role / OIDC-socket-probe steps below are still required (they are how
> the deployed panel gets AWS credentials with no static keys) and are unchanged.

> **Audience:** the human operator with (a) a Fly.io account/org that can create and deploy
> apps and set secrets, and (b) AWS credentials that can register an OIDC identity provider,
> create/modify an IAM role and trust policy, and (once deployed) be assumed by the Fly app to call
> `bedrock-agentcore:InvokeAgentRuntime`.
>
> **Why this runbook exists — these steps CANNOT be done by the developer agent.** They perform
> **live, hard-to-reverse actions** against shared cloud state: registering an AWS OIDC IdP, creating
> IAM roles/trust policies, setting production Fly secrets, deploying a platform app, going public,
> and running a real (billable, DB-writing) agent invocation. Each is gated on **explicit operator
> execution**. The committable artifacts (Dockerfile, `fly.toml`, the auth release gate + its tests,
> the `next build` fix) are already merged; this runbook is the procedure + evidence log for the live
> half.
>
> **No secret material is ever printed here.** Do not paste tokens, STS responses, assumed-role
> credentials, service-role keys, or the anon key's value into this file. Record only names, ARNs,
> claim *shapes* (key names, not values), timestamps, and run ids.

| Field | Value |
|-------|-------|
| Issues | [#128](https://github.com/llipe/dev-tasks-agent-fleet/issues/128) (S-115 deploy/OIDC), [#161](https://github.com/llipe/dev-tasks-agent-fleet/issues/161) (S-122 auth gate), [#162](https://github.com/llipe/dev-tasks-agent-fleet/issues/162) (S-123 go public) |
| Depends on | Phase A auth wave (S-116…S-121) merged into `integration/v2.1-panel-auth`; S-114 (#127) E2E green |
| Fly app | `dt-agent-fleet-panel` (see `panel/fly.toml`) |
| Region | AWS `us-east-1`; Fly primary region `iad` |
| Supabase project | `hegxeycmbmjfgzqpdiik` (dev-tasks-agent-fleet) — the deployed panel reads this project |
| Runtime ARN | `arn:aws:bedrock-agentcore:us-east-1:755641879575:runtime/dependencyupdate_dependency_update-UsQc5U5Yz0` (authoritative: `supabase/seed.sql` `agents.runtime_arn`) |
| Agent slug | `dependency-update` |
| Closes | AC8 (no static keys, live), spec **OQ1** (OIDC socket shape + `sub` normalization), **OQ2** (`prompt` wrapping — already observed, see #89); the **auth release gate** replaces SR2 privacy-as-a-boundary (D16 reversed) |

---

## 0. Preconditions

- [x] S-114 (#127) is merged to `main`.
- [x] The **agent runtime is deployed** (spec §15 ordering). The live invocation (§6) needs it to
      exist. If it is not deployed, deploy it first (agent-side runbook `issue-77-deployment-e2e.md`).
- [x] Local tooling: `flyctl` (authenticated: `fly auth whoami`), `aws` CLI (authenticated:
      `aws sts get-caller-identity`), `docker` (for a local image sanity build, optional), `node`.
- [x] The committable S-115 artifacts are present on the branch: `Dockerfile.panel` (repo root),
      `.dockerignore` (repo root), `panel/fly.toml`.
- [x] The committable **S-122 auth-gate** artifacts are present: `scripts/verify-panel-auth.sh`,
      `panel/scripts/panel-auth-check.mjs` (these REPLACE the removed S-115 privacy pair
      `scripts/verify-fly-private.sh` + `panel/scripts/fly-privacy-check.mjs`).

> **Dockerfile / .dockerignore live at the REPO ROOT, not under `panel/`.** Fly resolves
> `[build].dockerfile`/`ignorefile` relative to the `fly.toml` directory (`panel/`), and Docker only
> auto-applies a `.dockerignore` at the build-context root (the repo root). So `panel/fly.toml`
> points at `../Dockerfile.panel` and `../.dockerignore`. Building from `panel/Dockerfile` (the old
> path) fails with `panel/panel/Dockerfile' not found` and ships a 2.6 GB context.

**The panel image builds and boots locally** (developer-verified, reversible sanity check — safe to
re-run):

```bash
docker build -f Dockerfile.panel -t dt-panel:local .     # from the repo root
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

## Impl Step 4 — Deploy + confirm still private (tasks 1.11, 1.12) · **[LIVE / CONFIRM]**

> **Effect:** deploys a running app to Fly. Reversible by redeploying the prior image (see Rollback).

1. **Confirm the agent runtime is deployed** (task 1.11 — see Preconditions).

2. **Deploy the panel from the repo root** (the build context is the monorepo root). Remote builds
   have been unreliable here, so prefer a **local build** (`--local-only` uses your local Docker
   daemon and only pushes the finished image to Fly):

   ```bash
   fly deploy -a dt-agent-fleet-panel --config panel/fly.toml --local-only
   ```

3. **Confirm the deployed app is still PRIVATE (no public exposure introduced by the deploy).**
   Auth reverses the old "privacy is the only boundary" rule, but S-122 keeps the app private —
   `panel/fly.toml` declares no `[http_service]` and no public ports. Confirm no public IP was
   allocated:

   ```bash
   fly ips list -a dt-agent-fleet-panel
   # Expect ONLY a private (6PN, type "private", fdaa:…) address — NO v4/v6/shared_v4 public IP.
   ```

4. **Confirm unreachability from the public internet.** From a network with no Fly WireGuard/6PN
   access, the app must not resolve/serve; from a peered network, reach it via
   `fly proxy 8080:8080 -a dt-agent-fleet-panel` then `curl -i http://localhost:8080`. Record both
   observations.

5. **Run the AUTH release gate over the private network** — this is the substantive verification and
   is covered in detail in **§Phase A — verify the auth boundary (private)** below. In short, with a
   `fly proxy` tunnel open:

   ```bash
   NEXT_PUBLIC_SUPABASE_URL=… NEXT_PUBLIC_SUPABASE_ANON_KEY=… \
     scripts/verify-panel-auth.sh http://localhost:8080 -a dt-agent-fleet-panel
   # PASS (exit 0): env names present, protected UI → 302 /login, SSE → 401, signup REJECTED.
   ```

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

## Supabase project configuration checklist (operator, out-of-band — do this FIRST)

These are dashboard/API settings on the Supabase project (`hegxeycmbmjfgzqpdiik`), **not** in code —
so they can drift silently. Do them **before** the Phase A deploy; the auth gate (Phase A step 5)
then re-asserts the load-bearing ones by observation. No secret values recorded here — names/settings
only.

| # | Setting | Where | Why |
|---|---------|-------|-----|
| 1 | **Enable the Email provider** | Auth → Providers → Email | Password sign-in is the only supported method (spec §9.3). |
| 2 | **DISABLE public signups** | Auth → Providers → Email → "Allow new users to sign up" = OFF | **Release blocker (R9 / PRD AC17).** Once the app is public (Phase B) the Auth endpoint is reachable; an open signup lets anyone self-register into the agent-invoke surface. The auth gate’s signup check (verify-panel-auth.sh check 4) fails the release if a `signUp` succeeds. |
| 3 | **Refresh-token inactivity timeout = 12h** | Auth → Sessions (or Settings → Auth) → inactivity timeout | FR14 — sessions expire after 12h of inactivity (surfaced as the `/login` fine print). |
| 4 | **Create the operator user(s)** | Auth → Users → Add user (email + password) | Invitation-only; accounts are provisioned here, never seeded by a migration. |
| 5 | **Confirm signing keys are asymmetric** | Auth → Signing keys / JWKS | spec **OQ1 (auth)**: asymmetric (ES256/EC P-256) keys let `getClaims()` verify **locally** via cached JWKS with **no per-request network call** (confirmed by live JWKS probe, spec §11). If a project were on legacy symmetric (HS256) keys, `getClaims()` would need the auth server per request — a latency/availability change. Record which you observe. |

> **Env delivery (spec OQ2 — auth):** the panel needs `NEXT_PUBLIC_SUPABASE_URL` and
> `NEXT_PUBLIC_SUPABASE_ANON_KEY` at runtime. The anon (publishable) key is **safe for the browser**
> (RLS-bound), so the recommended delivery is `panel/fly.toml [env]` (non-secret, visible in config).
> Delivering it via `fly secrets` also works and keeps it out of the committed file; either is
> acceptable. The **service-role** key stays a `fly secrets` secret and MUST NOT gain a
> `NEXT_PUBLIC_` twin (SD2/D15). The auth gate checks only that the two `NEXT_PUBLIC_*` **names** are
> present on the app — never their values.

---

## Phase A — deploy + verify the auth boundary (app stays PRIVATE)

**Goal:** ship the auth build, configure Supabase, and prove the login boundary holds **over the
private Fly network** — at no point is the app reachable from the internet. This removes the exposure
window entirely (spec §15.1, R10): a public app never exists without a proven gate.

**Ordering (do not reorder):**

1. **Supabase checklist above** — email on, **signups off**, 12h inactivity, operator user created.
2. **Set the auth env** on the app (per the OQ2 note above):
   ```bash
   # Recommended: anon key + URL in fly.toml [env] (publishable, non-secret). If you prefer secrets:
   fly secrets set NEXT_PUBLIC_SUPABASE_URL='https://<project>.supabase.co' \
                   NEXT_PUBLIC_SUPABASE_ANON_KEY='<publishable anon key>' -a dt-agent-fleet-panel
   ```
3. **Deploy the auth build** (Impl Step 4 above) — `fly.toml` still private, **no public IP**.
4. **Verify over the private network** (`fly proxy`), unauthenticated:
   ```bash
   fly proxy 8080:8080 -a dt-agent-fleet-panel   # in one terminal; leave it open
   # in another terminal:
   curl -i  http://localhost:8080/                                   # expect 302 -> /login
   curl -si http://localhost:8080/api/runs/00000000-0000-0000-0000-000000000000/events/stream \
        -H 'Accept: text/event-stream' | head -1                     # expect HTTP/…​ 401
   ```
   Then confirm **login and logout both work** in a browser pointed at `http://localhost:8080`
   (sign in as the operator user → dashboard renders; click the sidebar **Log out** → back to
   `/login`; revisit `/` → redirected to `/login`).
5. **Run the auth release gate against the PRIVATE host** (the mechanical form of step 4):
   ```bash
   NEXT_PUBLIC_SUPABASE_URL='https://<project>.supabase.co' \
   NEXT_PUBLIC_SUPABASE_ANON_KEY='<publishable anon key>' \
   SUPABASE_SERVICE_ROLE_KEY='<service role key>'   `# optional: lets the gate auto-delete a stray signup account` \
     scripts/verify-panel-auth.sh http://localhost:8080 -a dt-agent-fleet-panel
   # PASS (exit 0): env names present, protected UI → 302 /login, SSE → 401, signUp REJECTED.
   # FAIL (exit 1): any check fails — FIX and redeploy. The app is still private; zero exposure.
   ```
   The gate’s check 4 attempts a `signUp` for a disposable `…@release-gate.invalid` address; if
   signups are still on it FAILS the release and deletes any account it created (needs the
   service-role key for the delete — otherwise it warns to delete manually).

**Phase A is complete when:** the build is deployed, the app is still private (no public IP, no
public service), and `verify-panel-auth.sh` exits 0 against the private host. **Do not proceed to
Phase B until every check passes.**

---

## Phase B — go public · **SEPARATE, OPERATOR-EXECUTED, SEPARATE PR — NOT part of the auth wave (S-123 / #162)**

> **This is Story S-123 and MUST NOT share a PR, story, or deploy with any Phase A story (spec
> §15.1, R10).** It performs the single hard-to-reverse action of the whole feature — exposing the
> app to the internet — behind an explicit operator-confirmation gate. It is reversible in one
> command (`fly ips release`), which is why it is isolated: containment does not require a redeploy.

**Preconditions:** Phase A is merged, deployed, and verified private; `verify-panel-auth.sh` passed
against the private host; the Supabase checklist (esp. **signups OFF**) is confirmed.

1. **Confirm the Supabase checklist again** — especially that public signups are OFF. This is the
   last chance to catch drift before the Auth endpoint is internet-reachable.
2. **Re-verify Phase A is deployed and private** (`fly ips list` shows only a 6PN address;
   `verify-panel-auth.sh http://localhost:8080` via `fly proxy` exits 0).
3. **EXPLICIT USER-CONFIRMATION GATE.** Do not run step 4 until the operator has explicitly confirmed
   "go public". There is no feature flag and no automation for this step by design (spec §15.3) — the
   deliberate manual action *is* the control.
4. **Enable the public service in `panel/fly.toml`** — add an HTTPS service and **rewrite the SR2
   banner** to state the app is now public and the auth gate is the boundary. Minimal service:
   ```toml
   [http_service]
     internal_port = 8080
     force_https = true
     auto_stop_machines = true
     auto_start_machines = true
     min_machines_running = 1
   ```
5. **Deploy the public config:**
   ```bash
   fly deploy -a dt-agent-fleet-panel --config panel/fly.toml --local-only
   ```
6. **Allocate the public IP:**
   ```bash
   fly ips allocate-v4 -a dt-agent-fleet-panel
   fly ips allocate-v6 -a dt-agent-fleet-panel   # optional
   ```
7. **Run the auth gate against the PUBLIC hostname** — same gate, public host. The **signup-rejected
   check is now load-bearing** (the Auth endpoint is internet-reachable):
   ```bash
   NEXT_PUBLIC_SUPABASE_URL=… NEXT_PUBLIC_SUPABASE_ANON_KEY=… SUPABASE_SERVICE_ROLE_KEY=… \
     scripts/verify-panel-auth.sh https://dt-agent-fleet-panel.fly.dev -a dt-agent-fleet-panel
   # MUST exit 0. If it FAILS → CONTAIN FIRST (step below), diagnose second.
   ```
8. **Signed-in live walkthrough** (in a browser at the public URL): sign in as the operator →
   **dashboard** renders seeded agents → open an agent’s **run history** → open a **run detail** →
   confirm the **live tail** streams (SSE) on a running run → **Log out** returns to `/login`.

### Phase B rollback / containment (faster than a redeploy)

> **Rule: if ANY gate check fails after exposure, CONTAIN FIRST, diagnose SECOND.** The panel is
> stateless; releasing the public IP makes it private again in one command without a redeploy.

```bash
fly ips list -a dt-agent-fleet-panel                 # find the public addr(s)
fly ips release <public-addr> -a dt-agent-fleet-panel   # app is private again immediately
# (optionally revert the [http_service] addition in fly.toml and redeploy to restore the private config)
```

Only after the app is private again: diagnose the gate failure, fix, re-run Phase A private
verification, and re-attempt Phase B.



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

No database or migration rollback is involved (the auth wave makes **no** schema/data change; auth
state lives in Supabase-managed `auth.*` + cookies). If the app is already public and a check fails,
prefer the **Phase B containment** above (`fly ips release`) — it makes the app private again in one
command without a redeploy.

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
| A5 | S-122 | auth env NAMES present; **auth gate** exit 0 against PRIVATE host (`verify-panel-auth.sh`) | | ☐ |
| A4 | S-122 | private, unauth: protected UI → 302 /login; SSE → 401; login+logout work | | ☐ |
| A5 | AC17 | signUp REJECTED (signups OFF); any created probe account deleted | | ☐ |
| A3 | S-122 | deployed app still PRIVATE — `fly ips list` shows only 6PN (no public IP) | | ☐ |
| 1.13 | AC4 | OIDC socket response shape (key names) | | ☐ |
| 1.13 | AC4 | normalized `sub` claim string | | ☐ |
| 1.14 | AC4 | `credentials.ts` matches SD9 (no change) / corrected | | ☐ |
| 1.15 | AC5 | `DurationSeconds 900 ≤ MaxSessionDuration` (value) | | ☐ |
| 1.16 | AC8 | live run `queued → running`; run id + timestamps; live log tail | | ☐ |
| 1.16 | AC8 | deployed panel logs `credentialSource(): fly-oidc` | | ☐ |
| 1.17 | AC9 | OQ2 — cite #89 (settled 2026-09-06) or record residual | see `issue-89-live-verification.md` | ☑ (via #89) |
| — | SR9 | live service-role smoke read returns rows | | ☐ |

### Auth-gate fail-demonstration — how to observe the gate failing live

To prove the gate actually blocks (not just that it passes), you can observe it failing against the
deployed app, then revert. The safest live demonstration is the **signup** direction (no public
exposure required): temporarily re-enable public signups in the Supabase dashboard, run the gate
against the private host, observe the failure, then turn signups back OFF.

```bash
# 1. In the Supabase dashboard, temporarily set "Allow new users to sign up" = ON.
NEXT_PUBLIC_SUPABASE_URL=… NEXT_PUBLIC_SUPABASE_ANON_KEY=… SUPABASE_SERVICE_ROLE_KEY=… \
  scripts/verify-panel-auth.sh http://localhost:8080 -a dt-agent-fleet-panel
#    EXPECT exit 1 — "A signUp SUCCEEDED — public signups are ENABLED. Release BLOCKED."
#    (the gate deletes the probe account it created via the admin API)
# 2. Turn signups back OFF in the dashboard, then re-run:
NEXT_PUBLIC_SUPABASE_URL=… NEXT_PUBLIC_SUPABASE_ANON_KEY=… \
  scripts/verify-panel-auth.sh http://localhost:8080 -a dt-agent-fleet-panel
#    EXPECT exit 0 again.
```

Record both the failing and the reverted-passing runs. The unit suite
`panel/tests/unit/panel-auth-check.test.ts` already demonstrates **every** violation direction
(200-on-protected-path, 200-on-SSE, successful signup, missing env, fail-closed) deterministically on
fixtures, and `workstream/s122-negative-demos.md` records the both-directions evidence captured with
the live wrapper against a local mock — this live demo confirms it against the real deployed app.
