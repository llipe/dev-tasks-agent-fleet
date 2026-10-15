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

## OIDC token probe (#280) — non-root socket access + the deploy-time regression guard

> **Added by #280.** This section documents how the deployed panel — which runs as a **non-root**
> user (uid 1001, `nextjs`) — gets access to the Fly Machine OIDC socket, and the deploy-time probe
> that fails the release if that access breaks. It supersedes the "root `fly ssh console` curl" probe
> in Impl Step 5 above as the **operator** procedure (that step's AWS-side `sub`/duration checks still
> apply; only the socket-connect probe moves to the runtime user).

**Root cause recap (D-01/D-02).** Fly creates `/.fly/api` at Machine boot as `srwxr-xr-x 0:0`
(root-owned, mode `0755`). Connecting to a unix socket requires **write** permission, which "other"
lacks — so uid 1001 gets `EACCES` and cannot obtain an OIDC token, while root connects (and gets a
plain HTTP 404 on the probe path, which *hid* the problem when probing from a root `ssh console`).
The image build cannot change the mode: the socket does not exist until boot. Since release v12 this
broke every invoke from the deployed panel (`CREDENTIALS_UNAVAILABLE`).

**The runtime fix (D-03/D-04).** The container now **starts as root** (`Dockerfile.panel` no longer
sets `USER nextjs`) and `panel/scripts/docker-entrypoint.sh` runs:

1. If `/.fly/api` exists as a socket, `chgrp nodejs /.fly/api && chmod g+w /.fly/api` — **group write
   for `nodejs` only, never world-writable**. On failure it logs a warning and continues (it never
   fails startup).
2. Always `exec setpriv --reuid=1001 --regid=1001 --init-groups node panel/server.js` — so node is
   **PID 1** running as uid 1001, and `--init-groups` gives it the `nodejs` group that now owns the
   socket. `setpriv` is from util-linux in `node:26-slim` (#217); **nothing is installed** for it
   (corepack, which `node:26-slim` no longer bundles, is installed via npm in the build stages only).

Off Fly (local `docker run`, CI) the socket is absent, the grant is skipped, and the server still
drops to uid 1001 — verified by the CI image smoke test (`.github/workflows/ci.yml`, `panel-quality`).

**Probe the socket AS THE RUNTIME USER (operator).** Because root always got a 404 (it could connect
regardless of mode), the only meaningful probe is one that runs **as uid 1001**, exactly as the
server does. `flyctl ssh console` has been returning a WebSocket **502** on this app, so use
`flyctl machine exec` to run the **same unit-tested probe that ships in the image**
(`/app/fly-oidc-probe.mjs`, Issue #280 / PR #295 review):

```bash
flyctl machine list -a dt-agent-fleet-panel --json        # find started Machine id(s)
flyctl machine exec <machine-id> \
  "setpriv --reuid=1001 --regid=1001 --init-groups node /app/fly-oidc-probe.mjs" \
  -a dt-agent-fleet-panel
# EXPECT: status=200 token=present   (the token VALUE is never printed — only presence.)
```

> **TRAP — `flyctl machine exec`'s exit status is NOT the remote command's status.** `flyctl machine
> exec` returns **exit 0 even when the command it ran inside the Machine failed**; the remote
> command's real status is printed to stdout as a separate `Exit code: <n>` line. For example,
> `flyctl machine exec <id> 'false'` prints `Exit code: 1` yet `flyctl` itself exits `0`. So when you
> run the probe by hand, **read the `status=… token=…` OUTPUT line to judge pass/fail — do not trust
> `echo $?`.** `scripts/deploy-panel.sh` does exactly this: it greps the output for a line matching
> exactly `status=2XX token=present` and never gates on flyctl's own exit status (it keeps flyctl's
> nonzero status as a failure too, but a zero status is not treated as success on its own).

Also confirm the socket is now group-writable by `nodejs`:

```bash
flyctl machine exec <machine-id> 'ls -ln /.fly/api' -a dt-agent-fleet-panel
# EXPECT: srwxrwxr-x 0 1001   (group 1001 has write; AC1)
```

And confirm the server process is uid/gid 1001 (AC2):

```bash
flyctl machine exec <machine-id> 'grep -E "^(Uid|Gid):" /proc/1/status' -a dt-agent-fleet-panel
# EXPECT: Uid: 1001 1001 1001 1001 / Gid: 1001 1001 1001 1001  (node is PID 1, not root)
```

> **`flyctl ssh console` fallback.** If `ssh console` 502s (as it does on this app), use
> `flyctl machine exec <id> '<cmd>'` for every one of these checks — it reaches the Machine without
> the SSH/WebSocket path.

**Deploy-time token probe (D-05) — the regression guard.** `scripts/deploy-panel.sh`, after the auth
release gate passes, runs the shipped probe (`/app/fly-oidc-probe.mjs`) on **every started Machine**
(via `flyctl machine exec` as uid 1001) — the exact same code the unit tests cover
(`panel/tests/unit/fly-oidc-probe.test.ts`), not an inline copy. It is the exact same request
`panel/lib/aws/credentials.ts` makes, with the same token-presence rule (`extractOidcToken`: a raw
**JWT body** — three base64url segments separated by dots — OR a JSON object with a string `value`
or `token` key OR a JSON-encoded JWT string; see the raw-JWT note below and D-07). It does **no** STS
exchange — obtaining a token as uid 1001 is the only
thing that was broken.

Because `flyctl machine exec` exits 0 even when the remote probe fails (see the TRAP note above), the
script **decides pass/fail from the probe's OUTPUT, not from flyctl's exit status**:

- **PASS:** the captured output contains a line matching **exactly** `status=2XX token=present` on
  every Machine → the script continues and exits `0` (healthy deploy, AC6: `status=200 token=present`
  per Machine).
- **FAIL:** anything else — `token=absent`, a non-2xx status, an `Exit code: <nonzero>` echo, empty
  output, or a flyctl-level error (flyctl's own nonzero status is still a failure) → the probe prints
  `status=<code> token=absent` (**never** the token value) and `deploy-panel.sh` **exits 3** with the
  rollback hint and a pointer to this section. Exit 3 keeps the script's existing contract: `0` ok ·
  `1` error · `2` blocked · `3` verify-fail.

The release pipeline (`deploy-panel.yml` → `scripts/deploy-panel.sh`) therefore fails the release
instead of shipping a panel that silently cannot invoke. `scripts/deploy-panel.sh --dry-run`
describes the probe without running it.

**Residual risk (D-06).** The entrypoint grant happens at container start. If Fly **recreates or
re-modes** `/.fly/api` *after* start (e.g. a platform-agent restart), the group-write grant is lost
and uid 1001 would get `EACCES` again. The deploy-time probe catches this **at release time**, but
**not** in the window between releases. This is an accepted residual risk. If it ever manifests
(invoke fails on a long-running Machine with no recent deploy), re-run the runtime-user probe above;
a `status=0`/`EACCES` with an unchanged image means a post-boot re-mode — restart the Machine (which
re-runs the entrypoint) or redeploy, and consider revisiting the root-stays / sidecar alternatives.
If the entrypoint's grant itself failed, its warning (`warn: could not grant group write on
/.fly/api …`) is in the Machine logs (`flyctl logs -a dt-agent-fleet-panel`).

---

### OIDC → STS → InvokeAgentRuntime: what the live path actually requires (#280, 2026-10-14)

`#280` was four stacked failures. Each one was hidden until the previous one was fixed. Check all four when invoking from the deployed panel fails:

| Layer | Symptom (panel log / run `error_message`) | Requirement | Where it lives |
| --- | --- | --- | --- |
| 1. Socket access | `Fly OIDC socket is unreachable: connect EACCES /.fly/api` | uid 1001 needs group write on `/.fly/api` (Fly creates it `0755 root:root`) | `panel/scripts/docker-entrypoint.sh` (above) |
| 2. Token shape | `FlyOidcShapeError` | the socket returns a **raw JWT body**, not JSON (D-07) | `panel/lib/aws/credentials.ts` `extractOidcToken` |
| 3. Issuer / sub | `AssumeRoleWithWebIdentity failed …` (`CREDENTIALS_UNAVAILABLE`) | Fly signs with the **org slug**: `iss=https://oidc.fly.io/felipe-mallea`, `sub=felipe-mallea:dt-agent-fleet-panel:<machine>`, **not** the `personal` alias. The IAM OIDC provider **and** the role trust conditions must use the slug (D-08) | IAM provider `oidc.fly.io/felipe-mallea`; `infra/trust-policy.json` |
| 4. Invoke authz | `InvokeAgentRuntime failed.` (`INVOCATION_FAILED`) | with a runtime **qualifier** (both agents use `DEFAULT`), AgentCore authorizes against `…:runtime/<id>/runtime-endpoint/<qualifier>`, so the policy must list that endpoint ARN as well as the runtime ARN (D-09) | `infra/agentcore-invoke-policy.json` (inline policy `invoke-runtime` on role `panel-agentcore-invoke`) |

**Diagnosing layers 3–4 without printing secrets.** Run these on a Machine **as the runtime user** (`flyctl machine exec <id> "sh -c '… setpriv --reuid=1001 --regid=1001 --init-groups node /tmp/x.js'"`):

- **Claims:** POST `/v1/tokens/oidc` on `/.fly/api`, split the body on `.`, base64url-decode **only the payload**, and print `iss`/`aud`/`sub`. Never print the token.
- **STS:** send an unsigned POST `Action=AssumeRoleWithWebIdentity` to `sts.us-east-1.amazonaws.com` with `RoleArn=$AGENT_RUNTIME_ROLE_ARN`. Print only `AssumedRoleUser/Arn` or the error `Code`.
- **Invoke authz:** make a SigV4-signed `POST /runtimes/<url-encoded runtime ARN>/invocations?qualifier=DEFAULT` with a dummy body. A `403 AccessDeniedException` names the exact resource ARN being authorized. A `200` whose agent reply is `INVALID_PARAMS` means authorization passed.

`flyctl machine exec` exits 0 even when the remote command fails, so read the output. Change record: `infra/changes/20261014-fly-oidc-issuer-trust/`.

**Retired:** the IAM provider `oidc.fly.io/personal` was deleted on 2026-10-15 (change record `infra/changes/20261015-retire-fly-oidc-personal/`, recreate with its `rollback.sh` if ever needed). The only Fly provider is `oidc.fly.io/felipe-mallea`.

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

2. **Set the required secrets. `SUPABASE_URL` is REQUIRED — not optional. No AWS access key of any
   kind (D12/AC8):**

   ```bash
   fly secrets set \
     SUPABASE_URL='https://hegxeycmbmjfgzqpdiik.supabase.co' \
     SUPABASE_SERVICE_ROLE_KEY='<service_role key for hegxeycmbmjfgzqpdiik>' \
     AGENT_RUNTIME_ROLE_ARN='<role ARN from task 1.9>' \
     -a dt-agent-fleet-panel
   ```

   > **`SUPABASE_URL` is REQUIRED at runtime.** The server-side data client
   > (`panel/lib/supabase/server.ts` → `readSupabaseEnv`) reads `SUPABASE_URL` **and**
   > `SUPABASE_SERVICE_ROLE_KEY`, and throws `SupabaseConfigError` if `SUPABASE_URL` is missing.
   > It is a **server-only** name (deliberately NOT `NEXT_PUBLIC_`, SD2/D15) and is NOT declared in
   > `fly.toml [env]` (only `NODE_ENV`/`PORT`/`HOSTNAME`/`AWS_REGION` are), so it MUST be provided
   > here. Omitting it does not fail at startup — login and the middleware gate use the *auth* client
   > (`NEXT_PUBLIC_SUPABASE_URL`) and work fine — but the first authenticated page that touches the
   > data client (the dashboard) 500s with `SupabaseConfigError` / digest `3101215328`. It is fine as
   > a `fly secrets` value (the project URL is not itself a credential); setting it as a secret also
   > keeps it off the committed `fly.toml`. Note this is DISTINCT from `NEXT_PUBLIC_SUPABASE_URL`
   > (the auth-client URL, delivered per the auth-env note below) — both point at the same project
   > but are read by different clients under different names.

3. **Assert there is NO AWS key of any kind (AC8/D12):**

   ```bash
   fly secrets list -a dt-agent-fleet-panel
   # Expect the digest list to contain the app config names:
   #   SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, AGENT_RUNTIME_ROLE_ARN
   #   (plus the NEXT_PUBLIC_SUPABASE_* auth pair if delivered via secrets — see the auth-env note).
   # It MUST NOT contain AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, or AWS_SESSION_TOKEN.
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
   NEXT_PUBLIC_SUPABASE_URL=… NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=… \
     scripts/verify-panel-auth.sh http://localhost:8080 -a dt-agent-fleet-panel
   # (Legacy fallback for one release: NEXT_PUBLIC_SUPABASE_ANON_KEY=… also works.)
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

   **Record the response SHAPE only** — never the token value. As of **2026-10-14** (Machine
   `845de5f2e502e8`, release `panel-v1.1.0` / Fly v13) the socket returns **HTTP 200** with
   `content-type: application/json; charset=utf-8` but a body that is **NOT valid JSON** — it is a
   **raw JWT** (three base64url segments separated by dots, ~1613 bytes). The earlier **2026-09-11**
   note recorded a JSON object; the live platform now returns a bare JWT. The panel's
   `extractOidcToken` accepts **all** of: a raw JWT body (verbatim), a JSON object with a string
   `value`/`token` field, and a JSON-encoded JWT string; it throws `FlyOidcShapeError` (naming the
   keys received, never any value) for anything else (`{}`, an HTML error page, a two-segment string).
   See D-07 in `workstream/decisions-panel-fly-oidc.md`.

2. **Record AWS's normalized `sub` claim.** After the first successful assume-role (or from the OIDC
   token's decoded `sub`), record the exact `sub` string AWS matched against the trust policy
   `StringLike` (e.g. `<org>:dt-agent-fleet-panel:<machine-or-*>`). This is what the trust policy
   condition must match.

3. **Compare to SD9 and correct code ONLY if reality differs (task 1.14):**
   - If the socket returns a raw JWT body, `{"value": "<token>"}`, or `{"token": ...}` and `sub`
     matches the assumed `<org>:<app>:*` pattern → **no code change** (all three are accepted since
     D-07). Record "matches SD9" with the evidence.
   - If the shape differs again (a new key, or `sub` normalized differently) → correct
     `panel/lib/aws/credentials.ts` (`extractOidcToken` and/or the trust policy pattern) **and**
     `panel/scripts/fly-oidc-probe.mjs` (`tokenIsPresent`/`isJwtShaped` — they share the rule by
     duplication, guarded by the parity corpus test), re-run `pnpm --filter panel run test:unit`,
     and commit the correction.

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
| 6 | **Create a publishable API key** (#172) | Settings → API keys → new (`sb_publishable_…`) | Supabase treats the classic `anon` JWT as a **legacy** client key; the publishable key is the forward path and is **individually revocable** without a project-wide session bust. Deliver it as `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` (see the env-delivery note). Record by **name only**, never the value. Once the deployed panel is confirmed working on it, **revoke the legacy anon key** as a distinct, recorded step. |

> **Env delivery (spec OQ2 — auth):** the panel needs `NEXT_PUBLIC_SUPABASE_URL` and the client key.
> Prefer the new publishable name `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` (#172); the panel also accepts
> the **legacy** `NEXT_PUBLIC_SUPABASE_ANON_KEY` as a deprecated fallback for one release. Either
> publishable or anon key is **safe for the browser** (RLS-bound), so the recommended delivery is
> `panel/fly.toml [env]` (non-secret, visible in config). Delivering it via `fly secrets` also works and
> keeps it out of the committed file; either is acceptable. The **service-role** key stays a
> `fly secrets` secret and MUST NOT gain a `NEXT_PUBLIC_` twin (SD2/D15). The auth gate checks only that
> the two `NEXT_PUBLIC_*` **names** are present on the app (URL + **either** publishable or anon client
> key) — never their values.

---

## Phase A — deploy + verify the auth boundary (app stays PRIVATE)

**Goal:** ship the auth build, configure Supabase, and prove the login boundary holds **over the
private Fly network** — at no point is the app reachable from the internet. This removes the exposure
window entirely (spec §15.1, R10): a public app never exists without a proven gate.

**Ordering (do not reorder):**

1. **Supabase checklist above** — email on, **signups off**, 12h inactivity, operator user created.
2. **Set the auth env** on the app (per the OQ2 note above):
   ```bash
   # Recommended: publishable client key + URL in fly.toml [env] (publishable, non-secret). If you
   # prefer secrets:
   fly secrets set NEXT_PUBLIC_SUPABASE_URL='https://<project>.supabase.co' \
                   NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY='<sb_publishable_… key>' -a dt-agent-fleet-panel
   # (Legacy fallback for one release: NEXT_PUBLIC_SUPABASE_ANON_KEY='<publishable anon key>'.)
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
   NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY='<sb_publishable_… key>' \
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
   NEXT_PUBLIC_SUPABASE_URL=… NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=… SUPABASE_SERVICE_ROLE_KEY=… \
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

---

## Publishable-key credential cutover (#172) — for an ALREADY-DEPLOYED panel

Issue #172 migrated the panel's **client/auth** Supabase credential off the legacy `anon` JWT onto the
new **publishable** API key (`sb_publishable_…`), which is **individually revocable** without a
project-wide session bust. `readAuthEnv()` (`panel/lib/supabase/auth-env.ts`) resolves
`NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` **first** and falls back to `NEXT_PUBLIC_SUPABASE_ANON_KEY` for
one release, so the cutover has **no flag day** — the moment the publishable key is present, the panel
uses it.

> **Scope guardrails.** This is a **client-key** cutover only. It does **not** change the **server**
> data client (`panel/lib/supabase/server.ts`, SD2/D15) — leave `SUPABASE_URL` and
> `SUPABASE_SERVICE_ROLE_KEY` untouched (migrating the server client to a new **secret** key is a
> separate concern). No schema/data change; auth state stays in Supabase-managed `auth.*` + cookies.

**Preconditions:** the panel is already deployed and public behind the login boundary (see §13 / ADR-007),
running today on the legacy anon key. `fly.toml` already declares the public `[http_service]` — this is
**not** a go-public step, so no new IP allocation is involved.

**Steps (do not reorder):**

1. **Create the publishable key** (Supabase dashboard, operator — Supabase checklist #6 above):
   Project Settings → API keys → new → **publishable** (`sb_publishable_…`) for project
   `hegxeycmbmjfgzqpdiik`. Record it by **name only**, never the value.

2. **Re-confirm the Supabase Auth settings** (unchanged preconditions): Email provider **on**, public
   signups **OFF** (hard release blocker — the gate's check 4 fails on a successful signup), 12h
   inactivity timeout, operator user exists.

3. **Set the new key on the Fly app** (setting a secret triggers a rolling redeploy):
   ```bash
   fly secrets set NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY='sb_publishable_…' -a dt-agent-fleet-panel
   ```
   Keep `NEXT_PUBLIC_SUPABASE_ANON_KEY` set during the cutover — the fallback keeps the app working if
   anything about the publishable key is wrong. Confirm the name landed (names only):
   ```bash
   fly secrets list -a dt-agent-fleet-panel   # expect NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY present
   ```
   If that name is **absent**, the running app is still on the anon key — the secret did not take; set
   it again and let the redeploy finish before continuing.

4. **Run the auth release gate against the PUBLIC host.** The gate script reads the URL + client key
   from **your shell environment** (it POSTs a disposable `signUp` to the Auth endpoint for check 4),
   so the vars MUST be **exported** into the shell you launch it from — a plain `NAME=value` (not
   exported) or a value set only via `fly secrets` will NOT be seen by the script, and check 4
   **fail-closes** with `WARN — … not set … cannot confirm signups are off`.
   ```bash
   export NEXT_PUBLIC_SUPABASE_URL='https://hegxeycmbmjfgzqpdiik.supabase.co'
   export NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY='sb_publishable_…'
   export SUPABASE_SERVICE_ROLE_KEY='<service-role key>'   # optional: lets the gate auto-delete a stray signup account

   printenv NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY   # confirm it is EXPORTED (prints a value) before running

   ./scripts/verify-panel-auth.sh https://dt-agent-fleet-panel.fly.dev -a dt-agent-fleet-panel
   # PASS (exit 0): env names present, protected UI → 302 /login, SSE → 401, signUp REJECTED.
   ```
   > **Gotcha (recorded from a real run).** A fail-closed check 4 with the "not set" WARN almost always
   > means the vars were *set but not exported* into the gate's shell — not an app problem (checks 1–3
   > passing prove the deployed app is configured and enforcing). Use `export` (or the inline
   > single-command form `VAR=… VAR=… ./scripts/verify-panel-auth.sh …` with every assignment on the
   > invocation line, no blank lines/comments between them). Single-quote the values so `!`/`$` in the
   > key are not mangled. "Could not confirm rejection" ≠ "signups are open" — it means the check could
   > not run.

5. **Signed-in live walkthrough** at the public URL: sign in as the operator → dashboard renders
   seeded agents → open an agent's **run history** → a **run detail** → confirm the **live tail**
   streams on a running run → **Log out** returns to `/login`. This proves the publishable key drives a
   full authenticated session, not just the anonymous-boundary probes in step 4.

6. **Revoke the legacy anon key** (the payoff — only after steps 4–5 confirm the app works on the
   publishable key):
   - Revoke the legacy `anon` key in the Supabase dashboard (individual revocation — no project-wide
     session bust).
   - Drop the now-unused fallback secret so the app runs on the publishable key alone:
     ```bash
     fly secrets unset NEXT_PUBLIC_SUPABASE_ANON_KEY -a dt-agent-fleet-panel
     ```
   - Re-run the gate (step 4) once more to confirm it still passes on the publishable name alone, and
     update the evidence-log `fly secrets list` row below to replace `NEXT_PUBLIC_SUPABASE_ANON_KEY`
     with `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`.

**Containment.** If the gate ever fails after the cutover, this is still an internet-reachable app:
contain first with `fly ips release <addr> -a dt-agent-fleet-panel` (private in one command, no
redeploy — see "Phase B rollback / containment" above), then diagnose. If a bad publishable key is the
cause and the anon fallback is still set, re-setting/using the anon key restores service without a
build.

**Other environments.** Local dev (`panel/.env.local`) and CI cut over independently — set
`NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` when convenient; the anon fallback keeps them working until then.

---

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

## Routine releases (post-launch) — PR → Release → deploy

Once Phase A/B above have run once, an ordinary code change no longer needs the
full runbook. The release flow is:

1. PRs merge to `main` as usual, gated by `ci.yml`.
2. A human runs `scripts/release-panel.sh` from a clean, up-to-date `main`
   checkout. It reads the commits since the last `panel-v*` tag that touch
   panel-relevant paths, classifies the bump from Conventional Commits
   (`feat!`/`BREAKING CHANGE` → major, `feat:` → minor, anything else
   conventional → patch), prints the suggested next version and the commit
   list, and asks for confirmation before creating the annotated tag and the
   GitHub Release. It refuses outright in CI without `INFRA_HUMAN_APPROVED=1`
   and refuses to guess at confirmation with no TTY — tag/release creation
   stays a human decision. Use `--dry-run` to see the suggestion without
   changing anything.
   ```bash
   scripts/release-panel.sh --dry-run   # preview the suggested version + changelog
   scripts/release-panel.sh             # confirm interactively, then cut the release
   ```
   (Tag policy, unchanged: annotated, cut on `main` only, immutable, no
   prerelease. The `panel-` prefix keeps this scoped to the panel in a
   monorepo that also ships agent images.)
3. Publishing the release fires `.github/workflows/deploy-panel.yml`, which
   runs `scripts/deploy-panel.sh` inside the `production` GitHub Environment —
   configured with a **required reviewer**, so the job pauses for a manual
   approval click even though the tag/release already exists.
4. `scripts/deploy-panel.sh` deploys (`fly deploy --config panel/fly.toml
   --local-only`) and then re-runs `scripts/verify-panel-auth.sh` against the
   public host as part of the same run — a deploy that ships but leaves the
   auth boundary unverified is treated as a failed release (exit 3), with the
   containment (`fly ips release`) and rollback commands printed on failure.

Locally, the same script can be run by hand (from the repo root, with `fly
auth login` done and the auth-gate env exported):

```bash
export NEXT_PUBLIC_SUPABASE_URL='https://hegxeycmbmjfgzqpdiik.supabase.co'
export NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY='sb_publishable_…'
export SUPABASE_SERVICE_ROLE_KEY='<service role key>'   # optional, lets the gate clean up its probe account

scripts/deploy-panel.sh            # or --dry-run to print the commands without deploying
```

**One-time setup for the GitHub Actions path** (operator, in repo settings —
not code):

- Create a `production` Environment (Settings → Environments) with at least
  one required reviewer.
- Add environment secrets: `FLY_API_TOKEN`, `PANEL_SUPABASE_URL`,
  `PANEL_SUPABASE_PUBLISHABLE_KEY`, `PANEL_SUPABASE_SERVICE_ROLE_KEY` (names
  only recorded here, per this runbook's no-secrets-in-file rule).

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
| 1.4/1.5 | AC1 | `Dockerfile` + `fly.toml` committed; no `[http_service]`/public ports; SR2/D16 comment | committed on `story/S-115-fly-deploy-oidc`; image builds + boots (developer-verified) | ☑ |
| 1.9 | AC2 | OIDC IdP provider ARN | operator action (Impl Step 2) — not captured in this close-out | ☐ |
| 1.9 | AC2 | IAM role ARN; policy resource = runtime ARN (not `*`) | operator action (Impl Step 2) — not captured in this close-out | ☐ |
| 1.10 | AC3/AC8 | `fly secrets list` — names only; NO AWS key present | 2026-09-11: names present + Deployed — `AGENT_RUNTIME_ROLE_ARN`, `SUPABASE_SERVICE_ROLE_KEY`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_SUPABASE_URL`, `SUPABASE_URL`. No `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_SESSION_TOKEN` present. (#172: the auth client key was later migrated to prefer `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`; the gate accepts **either** name, and on the publishable-key cutover this row's `NEXT_PUBLIC_SUPABASE_ANON_KEY` is replaced by `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`.) | ☑ |
| A5 | S-122 | auth env NAMES present; **auth gate** exit 0 against PRIVATE host (`verify-panel-auth.sh`) | not recorded on the private host — exposure was enabled out of order in PR #174 before a private gate run (see Deviation below); superseded by the PUBLIC-host run below | ☐ (deviation) |
| A4 | S-122 | private, unauth: protected UI → 302 /login; SSE → 401; login+logout work | not recorded on the private host (see Deviation); public-host equivalents recorded in the Phase B rows below | ☐ (deviation) |
| A5 | AC17 | signUp REJECTED (signups OFF); any created probe account deleted | see Phase B row (verified live against the public Auth endpoint) | ☑ |
| A3 | S-122 | deployed app still PRIVATE — `fly ips list` shows only 6PN (no public IP) | N/A — the app is intentionally PUBLIC as of PR #174 (this is Phase B); see the go-public rows | n/a |
| 1.13 | AC4 | OIDC socket response shape (key names) | 2026-09-11: matched the shipped provider contract (`extractOidcToken` accepts the token key without a `FlyOidcShapeError`); OIDC→STS exchange succeeded | ☑ |
| 1.13 | AC4 | normalized `sub` claim string | 2026-09-11: matched the trust-policy `StringLike` (`AssumeRoleWithWebIdentity` succeeded — a mismatch would have been `AccessDenied`) | ☑ |
| 1.14 | AC4 | `credentials.ts` matches SD9 (no change) / corrected | matches SD9 — no code change needed | ☑ |
| 1.15 | AC5 | `DurationSeconds 900 ≤ MaxSessionDuration` (value) | 2026-09-11: 900 accepted (assume-role succeeded; no `ValidationError` on `DurationSeconds`) | ☑ |
| 1.16 | AC8 | live run `queued → running`; run id + timestamps; live log tail | earlier live invocation recorded in `issue-89-live-verification.md` (run `a7203345-…`, `running` 2026-09-06 20:12:31 UTC); OIDC path reconfirmed 2026-09-11 | ☑ |
| 1.16 | AC8 | deployed panel logs `credentialSource(): fly-oidc` | 2026-09-11: `fly-oidc` branch confirmed on the deployed Machine | ☑ |
| 1.17 | AC9 | OQ2 — cite #89 (settled 2026-09-06) or record residual | see `issue-89-live-verification.md` | ☑ (via #89) |
| — | SR9 | live service-role smoke read returns rows | corroborated by the signed-in walkthrough (dashboard renders seeded agents) — operator to confirm at 1.6 | ☐ |

### Phase B — go-public evidence (S-123 / #162)

Exposure was enabled by **PR #174** (`[http_service]` added on the `fix/logout-redirect-relative-location`
branch), with a dedicated public IPv4 **137.66.51.207** allocated. The boundary was then verified
retroactively (this close-out).

| Task | AC | Item | Evidence (no secrets) | Result |
|------|----|------|------------------------|--------|
| 1.1 | AC / checklist | Supabase config: Email ON, **public signups OFF**, 12h inactivity, operator user exists | operator-confirmed 2026-09-11; independently corroborated by gate check 4 | ☑ |
| 1.2 | AC17 | **auth release gate against the PUBLIC host** `https://dt-agent-fleet-panel.fly.dev` | 2026-09-11 — exit 0: (2/4) protected UI `/` → **302 /login** PASS; (3/4) SSE → **401** PASS; (4/4) signUp disposable probe → **REJECTED** PASS. Check 1 used the documented `PANEL_AUTH_ENV_NAMES` override due to the parser defect fixed in task 1.27 | ☑ |
| 1.4 | AC11 | `panel/fly.toml` declares a public HTTPS service; banner states **login** (not privacy) is the boundary, cites ADR-007 | committed on this branch (commit `3832e30`); `fly config validate` passes; `[http_service]` values byte-identical to deployed (no redeploy) | ☑ |
| 1.13 | — | public IPv4 allocated; app reachable over HTTPS | `137.66.51.207` (allocated via PR #174, ~23h before verification) | ☑ |
| 1.7 | — | unauthenticated public denial (raw `curl`) | operator to capture: `curl -i https://dt-agent-fleet-panel.fly.dev/` → 302 `/login?redirect=%2F`; `…/api/runs/00000000-…/events/stream` → 401 | ☐ (operator) |
| 1.6 | — | signed-in public walkthrough — dashboard, run history, run detail, live tail, logout | operator (browser, live) | ☐ (operator) |
| 1.17 | — | containment path documented + reversible in one command | `fly ips release 137.66.51.207 -a dt-agent-fleet-panel` (Phase B rollback §) | ☑ |

### Deviation from the prescribed Phase A → Phase B ordering (task 1.9)

The story and this runbook prescribe that exposure (Phase B) be an isolated, operator-confirmed step
taken **only after** the auth gate passes over the **private** network (Phase A), so that a public app
never exists without a proven gate (spec §15.1, R10). **That ordering did not hold in execution.**
Exposure was enabled in **PR #174** on the `fix/logout-redirect-relative-location` branch — not an
isolated go-public PR — and a public IPv4 was allocated at that time. The auth gate was **not** run
against the private host, and was first run against the **public** hostname on **2026-09-11** (task
1.2, exit 0).

**Residual risk, stated plainly:** for the window between the public-IP allocation (PR #174) and the
first recorded public gate run on 2026-09-11 (~23 h), the auth boundary on the internet-reachable app
was **unverified by the gate**. The middleware gate and login were deployed and in force during that
window (the auth wave shipped in Phase A), so the exposure was behind login the whole time — but the
mechanical release-gate confirmation (including the AC17 signups-rejected check on the public Auth
endpoint) was retroactive, not a precondition of exposure as designed. This is recorded here rather
than reconstructed as if the order held. The private-network Phase A gate run prescribed by the story
was never captured and **cannot be recreated retroactively** now that the app is public.

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
