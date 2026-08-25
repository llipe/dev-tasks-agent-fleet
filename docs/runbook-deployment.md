# Deployment Runbook — Agent Fleet

Single consolidated deployment guide for the whole fleet: AWS infrastructure, the
`dep-updater` agent, the orchestrator, and the control plane on Fly.io behind Cloudflare
Access.

**Verified against live infrastructure:** AWS account `755641879575`, region `us-east-1`;
Fly org `personal`; Cloudflare account `6b28e7c684a09fb883843f96a34c76fc`.
**Last verified:** 2026-08-25.

Related runbooks:

- `docs/runbook-github-app.md` — GitHub App credential creation and rollback
- `docs/runbook-observability-setup.md` — span destination and log configuration

---

## Contents

1. [Deployment order and current state](#1-deployment-order-and-current-state)
2. [Prerequisites](#2-prerequisites)
3. [Stage 1 — AWS infrastructure stacks](#3-stage-1--aws-infrastructure-stacks)
4. [Stage 2 — dep-updater agent](#4-stage-2--dep-updater-agent)
5. [Stage 3 — Observability](#5-stage-3--observability)
6. [Stage 4 — Orchestrator](#6-stage-4--orchestrator)
7. [Stage 5 — Control plane IAM (blocking)](#7-stage-5--control-plane-iam-blocking)
8. [Stage 6 — Cloudflare Access](#8-stage-6--cloudflare-access)
9. [Stage 7 — DNS and TLS](#9-stage-7--dns-and-tls)
10. [Stage 8 — Fly deploy](#10-stage-8--fly-deploy)
11. [Verification](#11-verification)
12. [Rollback](#12-rollback)
13. [Cost](#13-cost)
14. [Troubleshooting](#14-troubleshooting)
15. [Corrections to earlier versions](#15-corrections-to-earlier-versions)

---

## 1. Deployment order and current state

Stages are ordered by dependency. Do not reorder — each stage assumes the previous one
landed.

| Stage | What                             | State                                      |
| ----- | -------------------------------- | ------------------------------------------ |
| 1     | Data + IAM CDK stacks            | ✅ Deployed                                |
| 2     | `dep-updater` agent + GitHub App | ✅ Deployed and verified (PR memo-cli#49)  |
| 3     | Observability (retention)        | ✅ 30-day retention on both log groups     |
| 4     | Orchestrator Lambda + schedule   | ✅ Deployed, invoked successfully          |
| 5     | Control-plane IAM (OIDC + logs)  | ✅ Deployed 2026-08-25 (#60)               |
| 6     | Cloudflare Access application    | ✅ App `fleet` exists, policy attached     |
| 7     | DNS + TLS for `fleet.llipe.com`  | ✅ Certificate issued 2026-08-25           |
| 8     | Fly deploy                       | ✅ Deployed 2026-08-25, 2 machines healthy |

All eight stages are deployed. `https://fleet.llipe.com/agents` redirects to the Cloudflare
Access login, and on `dt-agent-fleet-control-plane.fly.dev` `/healthz` returns 200 while every
protected route returns 401 as designed.

What remains is verification that needs a human in a browser: complete an Access login and
confirm the agents list renders with no `AccessDeniedException` in `fly logs`. Expect
`dep-updater` listed three times ([#61](https://github.com/llipe/dev-tasks-agent-fleet/issues/61))
and an empty runs view ([#62](https://github.com/llipe/dev-tasks-agent-fleet/issues/62));
neither is an IAM failure.

### Canonical names

Use these exact values. Earlier drafts of this runbook used placeholders and wrong names —
see [§15](#15-corrections-to-earlier-versions).

| Thing                  | Value                                                |
| ---------------------- | ---------------------------------------------------- |
| Fly app                | `dt-agent-fleet-control-plane`                       |
| Public hostname        | `fleet.llipe.com`                                    |
| Fly origin hostname    | `dt-agent-fleet-control-plane.fly.dev`               |
| Control-plane IAM role | `agent-fleet-control-plane-role`                     |
| Orchestrator IAM role  | `agent-fleet-orchestrator-role`                      |
| DynamoDB table / GSI   | `agent-fleet-config` / `GSI1`                        |
| Spans log group        | `aws/spans`                                          |
| Agent app log group    | discover it — see [§5](#5-stage-3--observability)    |
| Lambda                 | `agent-fleet-orchestrator`                           |
| CF Access app          | `fleet` (self-hosted), destination `fleet.llipe.com` |

---

## 2. Prerequisites

- `flyctl`, authenticated (`fly auth whoami`)
- `aws` CLI v2 with credentials for account `755641879575`
- `pnpm` (the repo is a pnpm workspace; do not use `npm`)
- `agentcore` CLI (for the agent only)
- Cloudflare Zero Trust enabled on the account
- `jq`

Uncommitted local changes that must be committed before a CI deploy, because CI deploys
from the branch, not the working tree:

```bash
git status --short
# fly.toml                                — app name set to dt-agent-fleet-control-plane
# agents/dep-updater/agentcore/agentcore.json — GitHub App secret id + bot committer identity
```

---

## 3. Stage 1 — AWS infrastructure stacks

Three stacks, defined in `infra/bin/app.ts`. All use `RemovalPolicy.RETAIN`; the DynamoDB
table has deletion protection on.

```bash
cd infra
pnpm run cdk deploy AgentFleetDataStack
pnpm run cdk deploy AgentFleetIamStack
```

`pnpm run cdk` wraps `cdk`, so pass the subcommand as part of the same argument — a bare
`--` is consumed by `cdk` itself and prints usage:

```bash
# Wrong — cdk receives `--` and prints help
pnpm run cdk -- deploy AgentFleetOrchestrationStack

# Correct
pnpm run cdk deploy AgentFleetOrchestrationStack
# or
npx cdk deploy AgentFleetOrchestrationStack
```

Seed the scope config (idempotent, guarded by `attribute_not_exists`):

```bash
# from repo root
pnpm run seed
```

### Write separation (do not weaken this)

`infra/lib/iam-stack.ts` creates three roles that partition write access to
`agent-fleet-config` by attribute. The allowlists live in
`packages/shared/src/iam-attributes.ts` and are the single source of truth:

| Role                             | May write                                       | Notably denied              |
| -------------------------------- | ----------------------------------------------- | --------------------------- |
| `agent-fleet-control-plane-role` | `enabled`, `params` (+ keys)                    | `InvokeAgentRuntime` (Deny) |
| `agent-fleet-orchestrator-role`  | `last_session_id`, `last_run_at`, `last_status` | —                           |
| `agent-fleet-agent-exec-role`    | `last_status`, `last_outcome_url` (+ keys)      | `PutItem` (Deny)            |

Any deployment shortcut that grants a principal unconditional `dynamodb:UpdateItem`
silently voids this control. Two such shortcuts have already been rejected on this
project; do not reintroduce them.

---

## 4. Stage 2 — dep-updater agent

Follow `docs/runbook-github-app.md` **first** and in full. `agentcore.json` points
`GITHUB_SECRET_ID` at `dep-agent/github-app`, which does not exist until that runbook's
step 4 creates it; deploying earlier fails every run with `ResourceNotFoundException`.

Then:

```bash
cd agents/dep-updater
agentcore deploy --dry-run   # validates envVars schema and synths; no AWS changes
agentcore deploy
```

The runtime execution role's grants are codified in
`agents/dep-updater/agentcore/cdk/lib/cdk-stack.ts`, derived from
`lib/fleet-iam-attributes.ts` — a mirror of the `@fleet/shared` allowlists that
`infra/test/vended-cdk-iam-drift.test.ts` fails CI on if it drifts. The vended CDK app
cannot import `@fleet/shared` (the AgentCore CLI stages it as a standalone npm project
outside the workspace), so the mirror plus the drift guard is the enforcement mechanism.

`agentcore deploy` may recreate the runtime, which changes the generated suffix on the app
log group. After any deploy, re-run the discovery in [§5](#5-stage-3--observability) and
update `AGENT_LOG_GROUP` on Fly.

Smoke test:

```bash
agentcore invoke '{"session_id": "smoke-001", "repo": "llipe/memo-cli"}'
```

Quote the JSON as a single argument or zsh will try to expand the braces. Expect 2–10
minutes. A 0.27s "success" means the pipeline threw early and the `finally` block completed
the async task — read the logs, do not trust the CLI's exit.

---

## 5. Stage 3 — Observability

The agent's application log group name carries an AgentCore-generated suffix
(`...-M4gkuL4wSr-DEFAULT`) that changes whenever the runtime is recreated. Always discover
it; never hardcode it.

```bash
APP_LG=$(aws logs describe-log-groups \
  --log-group-name-prefix /aws/bedrock-agentcore/runtimes/depupdater_dep_updater \
  --query 'logGroups[0].logGroupName' --output text)

echo "$APP_LG"   # must be non-empty before continuing
```

If this prints nothing, the prefix does not match a live runtime. Widen the search rather
than guessing:

```bash
aws logs describe-log-groups --log-group-name-prefix /aws/bedrock-agentcore/runtimes/ \
  --query 'logGroups[*].logGroupName' --output text
```

Set retention (spans already have 30 days):

```bash
aws logs put-retention-policy --log-group-name "$APP_LG" --retention-in-days 30
```

Spans land in the fleet-wide `aws/spans`, pinned in
`packages/shared/src/observability-config.ts`. It needs no configuration and no Fly secret.

### CloudWatch Transaction Search is required, and is already enabled

Per the
[AgentCore observability docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html):
"to view metrics, spans, and traces generated by the AgentCore service, you first need to
complete a one-time setup to turn on Amazon CloudWatch Transaction Search." Transaction
Search is what ingests AgentCore spans as structured logs into `aws/spans` — it is the
mechanism, not an unrelated X-Ray feature.

> An earlier revision of this runbook claimed Transaction Search was "not applicable
> because no X-Ray segments are emitted". That was wrong, and is corrected here.

It is already active on this account, enabled 2026-08-24:

```bash
aws xray get-trace-segment-destination
# { "Destination": "CloudWatchLogs", "Status": "ACTIVE" }

aws xray get-indexing-rules
# Default: Probabilistic, DesiredSamplingPercentage: 100.0
```

Console path, if it ever needs re-checking: CloudWatch → **Application Signals (APM)** →
**Transaction search**. The `CloudWatch → Settings → Traces and Metrics` path in older notes
does not exist.

**`aws/spans` is nevertheless still empty** — `storedBytes=0`, and its only stream has
`lastEventTimestamp=None`. The cause is on the agent side: no OTLP exporter or ADOT distro
is installed, so spans are created and attributed in-process and then dropped. Tracked as
[#62](https://github.com/llipe/dev-tasks-agent-fleet/issues/62). Until that lands, the
control plane's runs list and run detail views render empty regardless of IAM.

---

## 6. Stage 4 — Orchestrator

```bash
cd infra
pnpm run cdk diff AgentFleetOrchestrationStack
pnpm run cdk deploy AgentFleetOrchestrationStack
```

The Lambda is wired to `agent-fleet-orchestrator-role` in `orchestration-stack.ts`
(`role: orchestratorRole`), so unlike the agent runtime it genuinely runs under the
constrained role the IAM tests assert against. Confirm after deploy:

```bash
aws lambda get-function-configuration --function-name agent-fleet-orchestrator \
  --query Role --output text
# arn:aws:iam::755641879575:role/agent-fleet-orchestrator-role
```

Invoke it. AWS CLI v2 requires base64 or `fileb://` for `--payload`; a raw JSON string
fails with `Invalid base64`:

```bash
echo '{"agent":"dep-updater","scheduledAt":"2026-08-25T00:00:00Z"}' > /tmp/orch-payload.json

aws lambda invoke --function-name agent-fleet-orchestrator \
  --payload fileb:///tmp/orch-payload.json \
  /tmp/orchestrator-output.json && cat /tmp/orchestrator-output.json

rm -f /tmp/orch-payload.json /tmp/orchestrator-output.json
```

An EventBridge rule (`agent-fleet-dep-updater-schedule`) invokes it every 6 hours.

---

## 7. Stage 5 — Control-plane IAM (blocking)

**The control plane cannot obtain AWS credentials today.** Three gaps, all verified against
live AWS on 2026-08-25. All are code changes in `infra/lib/iam-stack.ts` and
`apps/control-plane/src/server/aws/credentials.ts`, tracked in
[#60](https://github.com/llipe/dev-tasks-agent-fleet/issues/60) — do not hand-patch the
live role.

### How Fly OIDC actually works

Confirmed against [Fly's OIDC docs](https://fly.io/docs/security/openid-connect/) and
[the announcement post](https://fly.io/blog/oidc-cloud-roles/). The mechanism is fully
automatic and requires **no application code**:

1. Fly's `init` detects the `AWS_ROLE_ARN` environment variable at machine boot.
2. It requests an OIDC token from the Machines API over the `/.fly/api` unix socket
   (`POST /v1/tokens/oidc`), with `aud` set to `sts.amazonaws.com`.
3. It writes the token to `/.fly/oidc_token`.
4. It sets `AWS_WEB_IDENTITY_TOKEN_FILE` and `AWS_ROLE_SESSION_NAME` for every process it
   launches.
5. The AWS SDK's default credential provider chain finds
   `AWS_WEB_IDENTITY_TOKEN_FILE` + `AWS_ROLE_ARN` and calls `AssumeRoleWithWebIdentity`
   itself.

Token claims, from the docs' example payload:

| Claim | Value for this app                                     |
| ----- | ------------------------------------------------------ |
| `iss` | `https://oidc.fly.io/personal`                         |
| `aud` | `sts.amazonaws.com`                                    |
| `sub` | `personal:dt-agent-fleet-control-plane:<machine-name>` |

`sub` is `<org-slug>:<app-name>:<machine-name>`, so it must be matched with `StringLike`
and a trailing wildcard. The org slug is `personal`, confirmed with `fly orgs list`.

### Gap 1 — role trust does not admit Fly

```bash
aws iam get-role --role-name agent-fleet-control-plane-role \
  --query 'Role.AssumeRolePolicyDocument'
# Principal: { "Service": "ecs-tasks.amazonaws.com" } only
```

No OIDC provider for Fly is registered either — the account has exactly one, for GitHub
Actions:

```bash
aws iam list-open-id-connect-providers
# token.actions.githubusercontent.com
```

So `AssumeRoleWithWebIdentity` from a Fly machine cannot succeed. The required provider is
`https://oidc.fly.io/personal` with audience `sts.amazonaws.com`, and the trust policy is:

```json
{
  "Effect": "Allow",
  "Principal": {
    "Federated": "arn:aws:iam::755641879575:oidc-provider/oidc.fly.io/personal"
  },
  "Action": "sts:AssumeRoleWithWebIdentity",
  "Condition": {
    "StringEquals": { "oidc.fly.io/personal:aud": "sts.amazonaws.com" },
    "StringLike": {
      "oidc.fly.io/personal:sub": "personal:dt-agent-fleet-control-plane:*"
    }
  }
}
```

### Gap 2 — role has no CloudWatch Logs or tagging permissions

`grep -n "logs:\|tag:" infra/lib/iam-stack.ts` returns nothing. The role's single inline
policy grants DynamoDB only. Every AWS call the control plane makes outside DynamoDB is
currently unauthorized:

| API                                          | Caller                             | Purpose                   |
| -------------------------------------------- | ---------------------------------- | ------------------------- |
| `StartQuery`, `GetQueryResults`, `StopQuery` | `server/aws/logs-insights-adapter` | Runs list and run detail  |
| `FilterLogEvents`                            | `server/aws/filter-logs-adapter`   | Run log panel             |
| `tag:GetResources`                           | `server/aws/tagging-adapter`       | Agent inventory discovery |

Fixing the log group _names_ (defects D2/D3) never granted permission to _read_ them.

The tagging call is the one that fails first — `listManagedAgents()` discovers agents by the
`agent:managed=true` tag filter, so without it the agents list is empty and nothing else
renders. The tags are live and correct:

```bash
aws resourcegroupstaggingapi get-resources \
  --tag-filters Key=agent:managed,Values=true \
  --query 'ResourceTagMappingList[*].ResourceARN' --output text
# arn:aws:bedrock-agentcore:us-east-1:755641879575:runtime/depupdater_dep_updater-M4gkuL4wSr ...
```

`tag:GetResources` does not support resource-level permissions and must be granted on
`Resource: "*"`. The `logs:` actions are scoped to the `aws/spans` and
`/aws/bedrock-agentcore/runtimes/depupdater_dep_updater*` group ARNs.

The app does **not** call `DescribeLogGroups` — `resolveAgentLogGroup()` reads
`AGENT_LOG_GROUP` and returns a configuration error when unset. Do not grant it.

### Gap 3 — `credentials.ts` invented env var names Fly never sets

`apps/control-plane/src/server/aws/credentials.ts` reads `FLY_OIDC_TOKEN_PATH` and
`FLY_AWS_ROLE_ARN`. **Neither is a real Fly variable.** Fly sets `AWS_ROLE_ARN` (operator
supplied), `AWS_WEB_IDENTITY_TOKEN_FILE` and `AWS_ROLE_SESSION_NAME` (both set by `init`).
The custom `fromWebToken` branch therefore never activates, and the app silently falls
through to the local-dev `fromEnv()` path with no credentials.

The fix is a deletion, not an addition: drop `createCredentialsProvider()` and use the
SDK's default chain, which already handles the web-identity file, environment variables and
local profiles.

```ts
import { fromNodeProviderChain } from "@aws-sdk/credential-providers";

export const credentialsProvider: AwsCredentialIdentityProvider = fromNodeProviderChain();
```

This also fixes the refresh bug for free. The previous code called `readFileSync` once at
module import and passed the result as a string, so the token was never re-read; Fly's OIDC
tokens are short-lived and STS credentials expire in 15 minutes. The default chain re-reads
the token file when it refreshes.

> Residual risk to verify on the first deploy: `init` writes `/.fly/oidc_token` at boot. The
> docs do not state whether it rewrites the file as the token ages. On a machine that stays
> up longer than the token's lifetime, a credential refresh could read a stale token. With
> `auto_stop_machines` enabled this may never surface. Watch `fly logs` for
> `InvalidIdentityToken` after the machine has been up for over an hour.

### Why not static access keys

`fromEnv()` is labelled "Local dev fallback" in `credentials.ts`. An IAM user with
DynamoDB grants attached directly would bypass the attribute conditions and the
`InvokeAgentRuntime` deny described in [§3](#write-separation-do-not-weaken-this) — the
same class of mistake as granting the agent runtime plain `UpdateItem`. If a temporary
static-credential path is ever needed, its policy must replicate every statement on the
role, including both `Deny`s, and carry a removal ticket.

Six secrets are currently **staged** on Fly, two of them static AWS keys:

```bash
fly secrets list --app dt-agent-fleet-control-plane
```

Remove the static keys once the OIDC path lands:

```bash
fly secrets unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY \
  --app dt-agent-fleet-control-plane
```

### After the fix deploys

```bash
cd infra && pnpm run cdk deploy AgentFleetIamStack
```

`AWS_ROLE_ARN` is a role ARN, not a credential — set it in `[env]` in
`fly.toml` rather than as a secret, so it is reviewable in git:

```toml
[env]
NODE_ENV = "production"
PORT = "3000"
AWS_ROLE_ARN = "arn:aws:iam::755641879575:role/agent-fleet-control-plane-role"
```

Confirm the mechanism engaged on the running machine:

```bash
fly ssh console --app dt-agent-fleet-control-plane -C "env" \
  | grep -E "AWS_ROLE_ARN|AWS_WEB_IDENTITY_TOKEN_FILE|AWS_ROLE_SESSION_NAME"
```

All three must be present. If only `AWS_ROLE_ARN` appears, `init` did not complete the
token dance and the SDK has no credentials.

---

## 8. Stage 6 — Cloudflare Access

The self-hosted application `fleet` already exists with destination `fleet.llipe.com` and
policy "Usuarios Autorizados".

Collect two values:

- **Team name** — Zero Trust → Settings; the hostname is `<team-name>.cloudflareaccess.com`.
  For this account it is **`round-mouse-afcf`**, confirmed from the Access login redirect on
  `https://fleet.llipe.com/agents`. `CF_ACCESS_TEAM_NAME` must match exactly — the middleware
  validates the JWT `iss` against `https://<team-name>.cloudflareaccess.com`, so a wrong value
  yields a 401 _after_ a successful Cloudflare login, which reads like a permissions bug.
- **Application Audience (AUD) tag** — open the `fleet` app → **Additional settings**. It is
  not on the Applications list view, and it is **not** the UUID in the dashboard URL — that
  is the application id. Confusing the two is the most likely misconfiguration.

  The reliable way to read it, no dashboard needed, is the Access login redirect itself. It
  is public information:

  ```bash
  curl -s -o /dev/null -w "%{redirect_url}" https://fleet.llipe.com/agents
  # .../cdn-cgi/access/login/fleet.llipe.com?kid=<AUD>&meta=<jwt>...
  ```

  The `kid` query parameter is the AUD tag, and decoding the `meta` JWT's payload shows the
  same value in its `aud` claim. For this account it is
  `3e104ede813452a73e7d350bad65ba9230c462c737add7ac963183a844a075f9`.

Via API, if the dashboard is uncooperative:

```bash
curl -s "https://api.cloudflare.com/client/v4/accounts/6b28e7c684a09fb883843f96a34c76fc/access/apps" \
  -H "Authorization: Bearer <cf-api-token>" | jq '.result[] | {name, aud}'
```

Set both on Fly:

```bash
fly secrets set \
  CF_ACCESS_TEAM_NAME="<team-name>" \
  CF_ACCESS_AUD="<aud-tag>" \
  --app dt-agent-fleet-control-plane
```

How enforcement works: Cloudflare authenticates the user at the edge and injects a signed
JWT in `Cf-Access-Jwt-Assertion`. `apps/control-plane/src/middleware.ts` verifies it
against the team's JWKS and returns 401 otherwise. The matcher exempts `/healthz`,
`/_next/static`, `/_next/image` and `/favicon.ico`; everything else requires a valid token.

**Security note.** Cloudflare Access protects `fleet.llipe.com` only. The Fly hostname
`dt-agent-fleet-control-plane.fly.dev` is publicly reachable and is not behind Access — the
middleware is the sole control there. That is by design and is what
[§11](#11-verification) tests, but it means any future route added outside the matcher is
exposed to the internet unauthenticated.

---

## 9. Stage 7 — DNS and TLS

**Status: certificate issued and verified 2026-08-25.** `fleet.llipe.com` serves through
Cloudflare Access with a Let's Encrypt certificate at the Fly origin, expiring in two months
and auto-renewing.

### Topology in use: Cloudflare proxy → Fly public hostname

No Cloudflare Tunnel is involved. Three DNS records on `llipe.com` are required, and all
three must be present — the two underscore records are what make validation work while the
apex record stays proxied:

| Type  | Name                    | Value                                  | Proxy    |
| ----- | ----------------------- | -------------------------------------- | -------- |
| CNAME | `fleet`                 | `dt-agent-fleet-control-plane.fly.dev` | Proxied  |
| CNAME | `_acme-challenge.fleet` | `fleet.llipe.com.<id>.flydns.net`      | DNS only |
| TXT   | `_fly-ownership.fleet`  | `app-<id>`                             | DNS only |

Get the exact values, including the app-specific `<id>`, from:

```bash
fly certs setup fleet.llipe.com --app dt-agent-fleet-control-plane
```

The **ownership TXT record is mandatory here.** Fly's own wording: "Required if your app
doesn't have an IPv6 address, or if traffic is routed through a CDN or proxy." Traffic is
proxied through Cloudflare, so Fly cannot see its own IPs on the hostname and uses this
record to prove ownership instead.

Verify all three from outside:

```bash
dig +short fleet.llipe.com                          # Cloudflare edge IPs (proxied)
dig +short _acme-challenge.fleet.llipe.com CNAME    # must return the flydns target
dig +short _fly-ownership.fleet.llipe.com TXT       # must return "app-<id>"

fly certs check fleet.llipe.com --app dt-agent-fleet-control-plane
```

### If the certificate stays `Not verified`

**Do not grey-cloud the record.** An earlier revision of this runbook advised temporarily
disabling the Cloudflare proxy to let the ACME challenge through. That is unnecessary when
the two underscore records exist, and it exposes the origin IP and drops Access protection
while in effect.

The real failure mode seen on this app: the certificate was created **before** the app had
public IPs, so `fly certs create` warned "Your app has no public IP addresses", the order
failed, and Fly never retried it. DNS was correct the whole time. Recreating the order fixed
it in under a minute:

```bash
fly certs delete fleet.llipe.com --app dt-agent-fleet-control-plane --yes
fly certs create fleet.llipe.com --app dt-agent-fleet-control-plane
fly certs check  fleet.llipe.com --app dt-agent-fleet-control-plane
```

This is safe while the certificate is unissued — nothing is being served on the hostname
yet, and the app stays reachable on `dt-agent-fleet-control-plane.fly.dev` throughout.
Allocate IPs first (`fly ips allocate-v4`, `fly ips allocate-v6`) so a fresh order has
something to validate against.

An empty `dig +short fleet.llipe.com.<id>.flydns.net TXT` means Fly is not running a
challenge — a stale order, not a DNS problem.

### `/healthz` is gated by Access on this hostname

Cloudflare Access fronts the entire hostname, so `https://fleet.llipe.com/healthz` returns a
302 to the Access login page rather than 200. The middleware's `/healthz` exemption only
applies at the origin. Fly's own health checks are unaffected — they hit the machine
directly on the internal network, bypassing Cloudflare. Only external uptime monitoring is
affected; probe `https://dt-agent-fleet-control-plane.fly.dev/healthz`, or add an Access
bypass policy scoped to `/healthz`, if external probing is wanted.

### Alternative: Cloudflare Tunnel (hardening, not yet implemented)

Running `cloudflared` inside the Fly machine pointed at `localhost:3000` would remove the
public `.fly.dev` surface entirely, make origin lockdown structural rather than
application-level, drop the Fly certificate requirement, and allow releasing the $2/mo
dedicated IPv4. It requires Dockerfile and `fly.toml` process changes, so it is a code
change and out of scope for this runbook. Do not run `cloudflared` from a laptop as a
production connector.

---

## 10. Stage 8 — Fly deploy

Blocked until [Stage 5](#7-stage-5--control-plane-iam-blocking) lands: without credentials
the app builds and serves `/healthz` but every DynamoDB and CloudWatch call fails.

App config is `fly.toml` (region `iad`, internal port 3000,
`force_https`, auto-stop/auto-start, `/healthz` check every 30s). The image is built by
`apps/control-plane/Dockerfile` — a multi-stage Next.js standalone build running as
non-root `nextjs`.

Required configuration. Secrets go in `fly secrets`; `AWS_ROLE_ARN` is a role ARN, not a
credential, so it belongs in `[env]` in `fly.toml` where it is
reviewable in git.

| Name                  | Where             | Source                                             |
| --------------------- | ----------------- | -------------------------------------------------- |
| `CF_ACCESS_TEAM_NAME` | `fly secrets`     | [§8](#8-stage-6--cloudflare-access)                |
| `CF_ACCESS_AUD`       | `fly secrets`     | [§8](#8-stage-6--cloudflare-access)                |
| `AGENT_LOG_GROUP`     | `fly secrets`     | discovered in [§5](#5-stage-3--observability)      |
| `AWS_REGION`          | `[env]` or secret | `us-east-1`                                        |
| `AWS_ROLE_ARN`        | `[env]`           | after [§7](#7-stage-5--control-plane-iam-blocking) |

`AWS_WEB_IDENTITY_TOKEN_FILE` and `AWS_ROLE_SESSION_NAME` are set by Fly's `init` when
`AWS_ROLE_ARN` is present — never set them yourself.

```bash
APP_LG=$(aws logs describe-log-groups \
  --log-group-name-prefix /aws/bedrock-agentcore/runtimes/depupdater_dep_updater \
  --query 'logGroups[0].logGroupName' --output text)

fly secrets set \
  AWS_REGION="us-east-1" \
  AGENT_LOG_GROUP="$APP_LG" \
  --app dt-agent-fleet-control-plane

fly secrets list --app dt-agent-fleet-control-plane   # confirm none left "Staged"
```

Deploy:

```bash
flyctl deploy --remote-only
```

CI (`.github/workflows/control-plane.yml`) runs the same command on `main` after `validate`
passes, using `FLY_API_TOKEN` from repository secrets.

---

## 11. Verification

Run after the first successful deploy and record the output.

```bash
FLY_HOST=dt-agent-fleet-control-plane.fly.dev

# 1. Health check — public by design, exempt from the middleware matcher
curl -s "https://$FLY_HOST/healthz"
# {"status":"ok"}

# 2. Protected route with no Access JWT
curl -s -o /dev/null -w "%{http_code}\n" "https://$FLY_HOST/agents"
# 401

# 3. Protected route with a forged JWT
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "Cf-Access-Jwt-Assertion: invalid-token" "https://$FLY_HOST/agents"
# 401

# 4. HTTPS redirect and HSTS
curl -s -o /dev/null -w "%{http_code}\n" "http://$FLY_HOST/healthz"     # 301
curl -s -I "https://$FLY_HOST/healthz" | grep -i strict-transport
```

Then, in a browser: `https://fleet.llipe.com/agents` must present the Cloudflare Access
login, and after authenticating must list agents with live DynamoDB data.

Two known deviations at this stage, neither an IAM failure:

- `dep-updater` appears **three times** — AgentCore tags three resources per agent and the
  inventory does not dedupe. [#61](https://github.com/llipe/dev-tasks-agent-fleet/issues/61).
- The **runs view is empty** — `aws/spans` has never received a record because no OTEL
  exporter is installed. [#62](https://github.com/llipe/dev-tasks-agent-fleet/issues/62).

What _would_ indicate an IAM failure is an `AccessDeniedException` in `fly logs` for
`StartQuery`, `GetQueryResults`, `FilterLogEvents` or `GetResources` — that points back to
[Stage 5](#7-stage-5--control-plane-iam-blocking) Gap 2.

Credential path actually in use:

```bash
fly ssh console --app dt-agent-fleet-control-plane -C "env" \
  | grep -E "AWS_ROLE_ARN|AWS_WEB_IDENTITY_TOKEN_FILE|AWS_ROLE_SESSION_NAME"
```

All three must be present — the latter two are set by Fly's `init`. If only `AWS_ROLE_ARN`
appears, the token dance did not run and the SDK has no credentials.

---

## 12. Rollback

**Control plane** is stateless — all state is in DynamoDB and CloudWatch, the TTL cache
rebuilds on demand, and sessions are re-authenticated by Cloudflare Access.

```bash
fly releases --app dt-agent-fleet-control-plane
fly releases rollback --app dt-agent-fleet-control-plane
curl -s https://dt-agent-fleet-control-plane.fly.dev/healthz
```

**Agent credential** — see `docs/runbook-github-app.md` §8. Flip `GITHUB_SECRET_ID` back to
`dep-agent/github-pat`, remove the `GIT_COMMITTER_*` entries, redeploy. Both secrets
coexist and the IAM grant spans `secret:dep-agent/github-*`, so no IAM change is needed in
either direction.

**CDK stacks** — all resources are `RETAIN` and the table has deletion protection, so
rollback is a redeploy of the previous template, never a destroy.

---

## 13. Cost

| Item                                     | Notes                                             |
| ---------------------------------------- | ------------------------------------------------- |
| Fly machines (2 × `shared-cpu-1x:256MB`) | Auto-stop enabled; billed while running           |
| Fly dedicated IPv4                       | $2.00/mo — allocated 2026-08-25                   |
| Fly dedicated IPv6                       | No charge                                         |
| Cloudflare Access + Tunnel               | $0 on the free tier (50 users)                    |
| DynamoDB on-demand                       | Negligible at dashboard volumes                   |
| CloudWatch Logs Insights                 | ~$0.005 per GB scanned                            |
| CloudWatch Logs storage                  | 30-day retention on `aws/spans` and the app group |

Target is under USD 10/month. `fly.toml` declares no `[[vm]]` block, so Fly's default size
applies — the first deploy provisioned `shared-cpu-1x:256MB`, confirmed with
`fly machines list`. The Dockerfile targets under 512 MB at runtime.

**Note the machine count.** Fly created **two** machines on the first deploy for high
availability, despite `min_machines_running = 0` — that setting governs idle stop, not the HA
pair. Both bill while running, so the machine line roughly doubles. Pass `--ha=false` on
deploy, or remove one with `fly machine destroy <id>`, if a single machine is preferred.
With `auto_stop_machines = "stop"` and low traffic the practical difference is small.

---

## 14. Troubleshooting

**`describe-log-groups` returns nothing.** The prefix does not match a live runtime; the
generated suffix changes when the runtime is recreated. Widen the prefix as shown in
[§5](#5-stage-3--observability).

**`aws lambda invoke` → `Invalid base64`.** CLI v2 requires `--payload fileb://<file>`.

**`pnpm run cdk -- deploy X` prints cdk usage.** Drop the `--`; see
[§3](#3-stage-1--aws-infrastructure-stacks).

**`Since this app includes more than a single stack, specify which stacks`.** Name the
stack explicitly; there are three.

**Heredoc produces no file.** Pasting multi-line blocks into zsh can collapse the newline
after `<< 'EOF'`, making the next token an argument to `cat`. Write the file with an editor
instead of pasting a heredoc.

**Fly cert stuck `Not verified`.** Orange-cloud proxy intercepting the ACME challenge; see
[§9](#9-stage-7--dns-and-tls).

**Deploy fails with `dockerfile ... not found`.** Fly resolves `[build].dockerfile` relative
to the `fly.toml` directory, not the working directory, and no CLI flag overrides it. The
toml lives at the repo root for this reason — the Dockerfile's `COPY` paths
(`package.json`, `apps/control-plane/`, `packages/shared/`) need the repo root as build
context. Run `flyctl deploy --remote-only` from the repo root.

**Build fails with `Module not found: Can't resolve './x.js'`.** The codebase uses
TypeScript ESM-style `.js` specifiers, which webpack only maps onto `.ts`/`.tsx` via
`resolve.extensionAlias` — configured in `apps/control-plane/next.config.ts`. Webpack
truncates this error list at five, so the named files are rarely the whole set.

**Build fails with `UnhandledSchemeError: Reading from "node:crypto"`.** A `"use client"`
component is importing the `@fleet/shared` barrel, which re-exports `buildSessionId` and so
drags `node:crypto` into the browser bundle. Import a narrow subpath instead
(`@fleet/shared/params-schemas`), adding an `exports` entry to the shared package if needed.

**Build fails with `Cannot find module '@tailwindcss/postcss'`.** In Tailwind v4 the PostCSS
plugin ships as a package separate from `tailwindcss`; both must be declared in
`apps/control-plane/package.json`.

**`{"error":"unauthorized","reason":"unexpected \"aud\" claim value"}` after a successful
Cloudflare login.** `CF_ACCESS_AUD` does not match the Access application's audience tag.
`jose` validates signature and issuer before audience, so this specific message is proof that
`CF_ACCESS_TEAM_NAME` is correct and the JWKS fetch succeeded — only the audience is wrong.
Read the real value from the login redirect's `kid` parameter (see
[§8](#8-stage-6--cloudflare-access)) and re-set the secret. The usual cause is using the
application UUID from the dashboard URL instead of the AUD tag.

The sibling failure, `unexpected "iss" claim value`, means `CF_ACCESS_TEAM_NAME` is wrong
instead. `missing or empty token` means the request never went through Cloudflare — expected
on the `.fly.dev` hostname.

**`fly ssh console` fails with `websocket: ... got 502`.** The SSH tunnel is being blocked,
typically by a corporate proxy or a network that disallows Fly's WireGuard/WebSocket
transport. Machine `env` cannot be inspected this way. `AWS_ROLE_ARN` is still verifiable
without SSH via `fly machine status <id> --display-config`, but the two variables Fly's
`init` injects at runtime (`AWS_WEB_IDENTITY_TOKEN_FILE`, `AWS_ROLE_SESSION_NAME`) are only
observable from inside the machine — re-run the check from an unproxied network.

**Secrets show `Staged`.** They are not live until a deploy, or `fly secrets deploy`.

**`AccessDeniedException` in the runs view.** Stage 5 Gap 2 — the role has no `logs:`
grants.

**Agent run "succeeds" in under a second.** The pipeline threw and `finally` completed the
async task. Read the app log group; do not trust the CLI result.

---

## 15. Corrections to earlier versions

Earlier revisions of this runbook contained instructions that do not work against this
account. They are recorded here so the errors are not repeated.

| Earlier text                                                      | Reality                                                                                                                                                                                                                                     |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| App `agent-fleet-control-plane`                                   | `dt-agent-fleet-control-plane`                                                                                                                                                                                                              |
| Hostname `controlplane.yourdomain.com`                            | `fleet.llipe.com`                                                                                                                                                                                                                           |
| Role `control-plane-role`                                         | `agent-fleet-control-plane-role`                                                                                                                                                                                                            |
| `fly secrets set AWS_ROLE_ARN=...`                                | Right variable, wrong home — it belongs in `[env]`, and `credentials.ts` reads neither it nor any real Fly variable                                                                                                                         |
| `flyctl deploy --config infra/control-plane.fly.toml`             | Fly resolves `[build].dockerfile` relative to the toml's directory, so this looked for `infra/apps/control-plane/Dockerfile`. The toml now lives at the repo root as `fly.toml`, matching the Dockerfile's build context                    |
| "Attach the trust policy to the role"                             | Role trusts `ecs-tasks.amazonaws.com`; no Fly OIDC provider exists                                                                                                                                                                          |
| Static access keys as an acceptable fallback                      | Bypasses write separation; needs full statement replication + removal ticket                                                                                                                                                                |
| Logs permissions unmentioned                                      | Role has **no** `logs:` or `tag:GetResources` grants — agent list and runs view both fail                                                                                                                                                   |
| `FLY_OIDC_TOKEN_PATH` / `FLY_AWS_ROLE_ARN` in `credentials.ts`    | Not Fly variables. Fly sets `AWS_WEB_IDENTITY_TOKEN_FILE` and `AWS_ROLE_SESSION_NAME` from `AWS_ROLE_ARN`                                                                                                                                   |
| CloudWatch Transaction Search at 1% sampling                      | Right requirement — it is the prerequisite that ingests AgentCore spans into `aws/spans`; already enabled at 100%                                                                                                                           |
| "Transaction Search is not applicable — no X-Ray segments"        | **Wrong**, written in an earlier revision of this file. It is exactly the ingestion mechanism for AgentCore spans                                                                                                                           |
| `CloudWatch → Settings → Traces and Metrics → Transaction Search` | Path does not exist. It is CloudWatch → Application Signals (APM) → Transaction search                                                                                                                                                      |
| Tunnel `agent-fleet-cp` → `.fly.dev` from an operator workstation | Not a production connector; tunnel-in-machine is the hardening path                                                                                                                                                                         |
| "Grey-cloud the DNS record so ACME can validate"                  | Unnecessary and harmful — it exposes the origin IP and drops Access. The `_acme-challenge` CNAME plus the `_fly-ownership` TXT validate fine behind the proxy; the real fault was a certificate order created before the app had public IPs |
| Span group `/aws/vendedlogs/agentcore/dep-updater/spans`          | `aws/spans` (defect D2)                                                                                                                                                                                                                     |
| App group `/aws/agentcore/dep-updater`                            | Discover it; the suffix is generated (defect D3)                                                                                                                                                                                            |
