# Pending Manual Configuration — dependency-update Agent

> Manual, out-of-code setup required before the agent can run end-to-end.
> Code (S-001, #71) does not create any of these — they are infrastructure/console/DB actions.
> Sourced from spec §15.4, §5 (technical-guidelines), and the implemented `config.py` / `credentials.py`.

## Legend

- **When:** the earliest task that needs it (`#71` credentials, `#77` deploy/E2E)
- **Owner:** who performs it (all are human/operator actions — agent has no permission)

---

## 1. Environment Variables (AgentCore runtime config)

Set on the AgentCore runtime (not baked into the image, not committed). Read by `config.py` / `agent_reporter.py` at startup.

| Variable | Required | Default (if unset) | Purpose | When |
|----------|----------|--------------------|---------|------|
| `SUPABASE_URL` | **Yes** | `""` (empty → fails) | Supabase project base URL for PostgREST | #71 |
| `SUPABASE_KEY_SECRET_ID` | No | `agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY` | Secrets Manager ID for the Supabase service role key | #71 |
| `RUN_ID` | **Yes** | — (injected per-invocation by control plane) | Execution ID | #77 |
| `RUN_PARAMS` | **Yes** | `{}` | JSON invocation params (injected per-invocation) | #77 |
| `MODEL_ID` | No | `us.anthropic.claude-sonnet-4-6` | Bedrock model for LLM fix loop | #75/#77 |
| `AGENT_LOG_LEVEL` | No | `INFO` | Minimum log level captured by the SDK handler | #77 |
| `TEST_TIMEOUT` | No | `600` | Validation timeout (seconds) | #72 |
| `TOOL_COMMAND_TIMEOUT` | No | `180` | Per-command timeout for fix-agent tools (seconds) | #75 |
| `IDLE_SESSION_TIMEOUT` | No | `900` | Mirror of `agentcore.json` `idleRuntimeSessionTimeout`; used by the clock-consistency check | #98 |
| `MAX_LIFETIME` | No | `3600` | Mirror of `agentcore.json` `maxLifetime`; used by the clock-consistency check | #98 |
| `REAPER_THRESHOLD_SECONDS` | No | `3720` | Mirror of Supabase `max_runtime_seconds` (3600) + `grace_seconds` (120) | #98 |
| `HEARTBEAT_INTERVAL` | No | `120` | Cadence (seconds) of keep-alive heartbeat chunks during long steps; must be `≤ IDLE_SESSION_TIMEOUT/2` | #98 |

> Note: `SUPABASE_SERVICE_ROLE_KEY` is NOT set as an env var. The agent fetches it from
> Secrets Manager at startup (D15/D24) and sets it into the environment in-process.

---

## 2. AWS Secrets Manager

| Secret | Required | Value | When |
|--------|----------|-------|------|
| `agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY` | **Yes** | The Supabase service role key (plaintext `SecretString`) | #71 |
| GitHub App PEM secret | **Yes** | The GitHub App private key PEM. Stored at the ARN referenced by `github_installations.private_key_secret_arn` | #71 |

- Create in `us-east-1` (matches `aws-targets.json`).
- The GitHub PEM secret's ARN goes into the DB row (see §4), never into code.

---

## 3. IAM (agent execution role)

Add to the AgentCore agent execution role — scoped, never `*`:

| Permission | Resource | When |
|------------|----------|------|
| `secretsmanager:GetSecretValue` | `arn:aws:secretsmanager:us-east-1:<account>:secret:agent-fleet/prod/*` | #71/#77 |
| `bedrock:InvokeModel` | Claude Sonnet model ARN (`us.anthropic.claude-sonnet-4-6`) | #75/#77 |

---

## 4. Supabase Database

| Action | Detail | When |
|--------|--------|------|
| Run `001_schema.sql` | Tables, enums, indexes, `v_runs` view, `reap_stale_runs()`, RLS | #77 |
| Run `002_seed.sql` | Installation row, repositories, `dependency-update` agent row | #77 |
| `github_installations` row | Must contain: `github_org_slug`, `app_id`, `installation_id`, `private_key_secret_arn`, `is_enabled=true` | #71 |
| pg_cron reaper | **Done in #94** — the `create extension` + `cron.schedule('reap-stale-runs', '* * * * *', …)` block now ships inside `001_schema.sql`, so running that file registers it. Verification: [`docs/runbooks/issue-94-reaper-verification.md`](../docs/runbooks/issue-94-reaper-verification.md) §1 | #94 |

> The credential lookup query (`credentials._get_installation`) depends on the
> `github_installations` row existing with `is_enabled=true` and matching `github_org_slug`.
> Without it → `NO_INSTALLATION` error.

---

## 5. GitHub App

| Action | Detail | When |
|--------|--------|------|
| Create GitHub App | Permissions: Contents (read/write), Pull Requests (read/write), Metadata (read) | #71 |
| Install org-wide | Generates the `installation_id` used in the DB row | #71 |
| Generate private key | Download PEM → store in Secrets Manager (see §2) | #71 |
| Record `app_id` + `installation_id` | Into the `github_installations` DB row (see §4) | #71 |

---

## 6. Bedrock

| Action | Detail | When |
|--------|--------|------|
| Enable model access | Claude Sonnet (`us.anthropic.claude-sonnet-4-6`) in Bedrock console, `us-east-1` | #75/#77 |

---

## 7. CDK / Deployment

| Action | Detail | When |
|--------|--------|------|
| `cdk bootstrap` | `cdk bootstrap aws://<account>/us-east-1` (once per account/region) | #77 |
| `agentcore deploy -y` | From `agents/dependency-update/` | #77 |
| Record `runtime_arn` | From `agentcore status` → fill into `002_seed.sql` | #77 |

---

## 8. Local Development (this machine only)

| Action | Detail | When |
|--------|--------|------|
| Netskope CA cert | Pass `--build-arg EXTRA_CA_CERT=nscacert.pem` when building locally behind the proxy. Copy from `/Library/Application Support/Netskope/STAgent/data/nscacert.pem` into the build context first. Never committed. | now |
| AWS credentials | SSO profile / `~/.aws/credentials` for local `agentcore` commands | #77 |

---

## Step-by-Step Runbook

> Execute in this order. Steps 1–6 are one-time credential/infra setup (needed before
> the credential path in #71 can work against real services). Steps 7–9 are deploy + E2E (#77).
> All AWS actions target `us-east-1`, account `755641879575` (confirm before running).
> Replace placeholders in `<angle brackets>`.

### Prerequisites (local machine)

```bash
# Confirm tooling is present
aws --version
gh --version
agentcore --version
docker info >/dev/null && echo "docker ok"

# Confirm AWS identity/region point at the intended account
aws sts get-caller-identity
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo "Account: $AWS_ACCOUNT_ID  Region: $AWS_REGION"
```

If behind Netskope, trust the corporate CA for local AWS/gh/curl calls:

```bash
export AWS_CA_BUNDLE="/Library/Application Support/Netskope/STAgent/data/nscacert.pem"
export NODE_EXTRA_CA_CERTS="/Library/Application Support/Netskope/STAgent/data/nscacert.pem"
```

---

### Step 1 — Create the GitHub App

1. Go to GitHub → Org **Settings → Developer settings → GitHub Apps → New GitHub App**.
2. Set:
   - **Name:** `dep-update-agent` (or similar)
   - **Homepage URL:** any placeholder
   - **Webhook:** uncheck **Active** (no webhook needed).
3. **Repository permissions:**
   - **Contents:** Read and write
   - **Pull requests:** Read and write
   - **Metadata:** Read-only (auto-selected)
4. **Where can this GitHub App be installed?** → **Only on this account**.
5. Click **Create GitHub App**.
6. On the App's page, note the **App ID** (numeric) — this is `app_id`.
7. Scroll to **Private keys → Generate a private key**. A `.pem` downloads. Keep it safe; you will store it in Secrets Manager (Step 3).
8. Left sidebar → **Install App → Install** on the org. Choose **All repositories** (or select the fixture repos).
9. After install, the browser URL is `.../installations/<installation_id>` — note `installation_id` (numeric).

**Record for later:** `app_id`, `installation_id`, path to the downloaded `<app>.private-key.pem`.

---

### Step 2 — (If not already done) get the Supabase service role key

1. Supabase dashboard → your project → **Project Settings → API**.
2. Copy the **`service_role`** secret (NOT the `anon` key).
3. Note the **Project URL** (e.g. `https://abcdxyz.supabase.co`) — this becomes `SUPABASE_URL` (Step 7).

---

### Step 3 — Store secrets in AWS Secrets Manager (`us-east-1`)

```bash
# 3a. Supabase service role key (default secret ID expected by config.py)
aws secretsmanager create-secret \
  --name "agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY" \
  --description "Supabase service role key for dependency-update agent" \
  --secret-string "<paste-service-role-key>" \
  --region "$AWS_REGION"

# 3b. GitHub App private key PEM
aws secretsmanager create-secret \
  --name "agent-fleet/prod/GITHUB_APP_PRIVATE_KEY" \
  --description "GitHub App PEM for dependency-update agent" \
  --secret-string "file://<path-to>/<app>.private-key.pem" \
  --region "$AWS_REGION"

# Capture the PEM secret ARN — it goes into the DB row (Step 5)
export GH_PEM_ARN=$(aws secretsmanager describe-secret \
  --secret-id "agent-fleet/prod/GITHUB_APP_PRIVATE_KEY" \
  --region "$AWS_REGION" --query ARN --output text)
echo "PEM ARN: $GH_PEM_ARN"
```

> If a secret already exists, use `put-secret-value --secret-id <name> --secret-string ...` instead of `create-secret`.

---

### Step 4 — Enable Bedrock model access

1. Bedrock console (`us-east-1`) → **Model access → Manage model access**.
2. Enable **Anthropic → Claude Sonnet** (the model behind `us.anthropic.claude-sonnet-4-6`).
3. Submit and wait until status is **Access granted**.

```bash
# Verify the inference profile is reachable
aws bedrock list-inference-profiles --region "$AWS_REGION" \
  --query "inferenceProfileSummaries[?contains(inferenceProfileId,'claude-sonnet')].inferenceProfileId"
```

---

### Step 5 — Apply schema + seed to Supabase and insert the installation row

1. Supabase → **SQL Editor**.
2. Paste and run `docs/reference/001_schema.sql` (schema, view, reaper, RLS).
3. Paste and run `docs/reference/002_seed.sql` (installation, repositories, agent row).
   - The `dependency-update` agent row's `runtime_arn` is filled later in Step 7; leaving it null is fine until then.
4. Insert / update the GitHub installation row (values from Steps 1 and 3):

```sql
-- Run in Supabase SQL Editor. Adjust column names to match 001_schema.sql.
insert into github_installations
  (github_org_slug, app_id, installation_id, private_key_secret_arn, is_enabled)
values
  ('<org-slug>', <app_id>, <installation_id>, '<GH_PEM_ARN>', true)
on conflict (github_org_slug) do update
  set app_id = excluded.app_id,
      installation_id = excluded.installation_id,
      private_key_secret_arn = excluded.private_key_secret_arn,
      is_enabled = true;
```

5. ~~Schedule the reaper (once):~~ **Superseded by issue #94.** The schedule now ships **inside**
   `docs/reference/001_schema.sql` (the `create extension if not exists pg_cron;` +
   `cron.schedule('reap-stale-runs', …)` block at the file tail was uncommented in #94), so step 2
   above already registers it. Do not run the command separately.

   For enabling the extension, verifying the job (`cron.job`, `cron.job_run_details`), and the
   stale-run verification procedures, follow
   [`docs/runbooks/issue-94-reaper-verification.md`](../docs/runbooks/issue-94-reaper-verification.md)
   §1 — that runbook is the current source of truth. The command is retained here only as history:

   ```sql
   -- superseded — now part of 001_schema.sql
   select cron.schedule('reap-stale-runs', '* * * * *', 'select reap_stale_runs()');
   ```

> Sanity check the credential lookup path (#71) will resolve:
> `select github_org_slug, app_id, installation_id from github_installations where is_enabled;`

---

### Step 6 — CDK bootstrap (once per account/region)

```bash
cd agents/dependency-update/agentcore/cdk
cdk bootstrap "aws://$AWS_ACCOUNT_ID/$AWS_REGION"
```

> Known constraint (technical-guidelines §13): `cdk` under Node 26 with `aws-cdk-lib@2.266.0`
> has a documented `cdk destroy` incompatibility. Validate the `aws-cdk-lib` version against
> the active Node version before relying on `cdk destroy`/`cdk deploy`.

---

### Step 7 — Deploy the agent runtime + set env vars

> **Issue #98 — redeploy required for the lifecycle change.** `agentcore/agentcore.json`
> now sets `idleRuntimeSessionTimeout: 900` (raised from 300) so a bounded `TEST_TIMEOUT`
> (600 s) validation run, kept alive by a 120 s heartbeat, cannot trip idle reclamation
> mid-`validate`. This value lives in the runtime's `lifecycleConfiguration` and only takes
> effect after **re-running `agentcore deploy -y`** below. The mirror constants
> (`IDLE_SESSION_TIMEOUT`, `MAX_LIFETIME`, `REAPER_THRESHOLD_SECONDS`, `HEARTBEAT_INTERVAL`)
> are enforced consistent in-code by `assert_clock_invariant()` at entrypoint start; if you
> override any of them via env var, keep the ordering
> `TOOL_COMMAND_TIMEOUT ≤ TEST_TIMEOUT ≤ IDLE_SESSION_TIMEOUT ≤ MAX_LIFETIME ≤ REAPER_THRESHOLD_SECONDS`
> and `HEARTBEAT_INTERVAL ≤ IDLE_SESSION_TIMEOUT/2`, or the agent will refuse to start
> (`ClockConsistencyError`).

```bash
cd agents/dependency-update
agentcore deploy -y
agentcore status          # wait until the runtime reports Ready
```

Set the runtime environment variables (via `agentcore` runtime config or the AgentCore
console — `SUPABASE_URL` is required, the rest are optional overrides):

| Variable | Value |
|----------|-------|
| `SUPABASE_URL` | `<https://your-project.supabase.co>` |
| `SUPABASE_KEY_SECRET_ID` | leave unset unless you renamed the secret in Step 3a |
| `MODEL_ID` | leave unset unless overriding Claude Sonnet |
| `AGENT_LOG_LEVEL` | `INFO` (optional) |

> `SUPABASE_SERVICE_ROLE_KEY`, `RUN_ID`, `RUN_PARAMS` are NOT set here — the key is pulled
> from Secrets Manager in-process, and `RUN_ID`/`RUN_PARAMS` are injected per invocation.

Record the runtime ARN and write it back to the seed:

```bash
export RUNTIME_ARN=$(agentcore status --json 2>/dev/null | jq -r '.runtimes[0].arn')
echo "runtime_arn: $RUNTIME_ARN"
# Update docs/reference/002_seed.sql agents row with this ARN, then re-run that UPDATE
# in the Supabase SQL Editor (Step 5).
```

---

### Step 8 — Attach IAM permissions to the execution role

Find the execution role AgentCore created for the runtime (from `agentcore status`/console),
then attach a scoped inline policy:

```bash
export EXEC_ROLE_NAME="<agentcore-execution-role-name>"

cat > /tmp/dep-update-policy.json <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadAgentSecrets",
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": "arn:aws:secretsmanager:${AWS_REGION}:${AWS_ACCOUNT_ID}:secret:agent-fleet/prod/*"
    },
    {
      "Sid": "InvokeClaudeSonnet",
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": "arn:aws:bedrock:${AWS_REGION}::foundation-model/anthropic.claude-sonnet-*"
    }
  ]
}
JSON

aws iam put-role-policy \
  --role-name "$EXEC_ROLE_NAME" \
  --policy-name "dep-update-agent-runtime" \
  --policy-document file:///tmp/dep-update-policy.json
```

> The `bedrock:InvokeModel` resource may also need the inference-profile ARN
> (`arn:aws:bedrock:${AWS_REGION}:${AWS_ACCOUNT_ID}:inference-profile/us.anthropic.claude-sonnet-*`)
> depending on how the model is invoked. Add it if invocation returns AccessDenied.

---

### Step 9 — End-to-end validation (#77)

Requires the two fixture repos (see Open Question 1). Once they exist:

```bash
cd agents/dependency-update

# 9a. audit_only on a clean repo → succeeded/no_vulnerabilities, Supabase rows written
agentcore invoke '{"run_id":"<uuid>","params":{"repository":{"full_name":"<org>/fixture-dep-update-clean"},"fix_mode":"audit_only"}}'

# 9b. llm_fix on a repo with available updates → PR opened
agentcore invoke '{"run_id":"<uuid>","params":{"repository":{"full_name":"<org>/fixture-dep-update-breaking"},"fix_mode":"llm_fix"}}'

# 9c. second invoke while PR open → succeeded/not_applicable (idempotency)
# 9d. invalid payload → failed/INVALID_PARAMS, no clone
agentcore invoke '{"params":{}}'
```

Verify in Supabase after each: `runs`, `run_steps`, `run_events`, `run_artifacts`, and
`runs.metrics` (llm_used, fix_attempts, vuln counts).

---

## Open Questions (from spec §17, still unresolved)

1. **Fixture repos for E2E (#77):** Who creates/maintains `fixture-dep-update-clean` and
   `fixture-dep-update-breaking`? These block E2E acceptance criteria 7.7–7.10.
2. **`SUPABASE_URL` source at deploy time:** confirm the exact project URL to set as the
   runtime env var.
3. **Account ID:** deployment account is `755641879575` (from `aws sts get-caller-identity`
   during S-001). Confirm this is the intended target account.
