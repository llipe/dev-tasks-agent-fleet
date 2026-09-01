# Operator Runbook — Issue #77: Deployment, IAM, Seed Apply & E2E Validation

> **Audience:** the human operator with AWS + Supabase + GitHub App access.
> **Why this exists:** these steps require live infrastructure credentials,
> carry migration/IAM blast radius, and cannot be performed by the developer
> agent autonomously. The code + seed + docs portions of issue #77 (sub-tasks
> 7.1, 7.11, 7.12, 7.13) are already done on branch
> `issue/77-seed-deployment-e2e-validation` (PR #88). Execute the steps below in
> order, then report results back so the remaining checklist items can be marked
> complete.

| Field | Value |
|-------|-------|
| Issue | [#77](https://github.com/llipe/dev-tasks-agent-fleet/issues/77) |
| PR | [#88](https://github.com/llipe/dev-tasks-agent-fleet/pull/88) (draft) |
| Branch | `issue/77-seed-deployment-e2e-validation` |
| Agent dir | `agents/dependency-update/` |
| Seed file | `docs/reference/002_seed.sql` |
| Region | `us-east-1` |

---

## Prerequisites (verify before starting)

- [x] AWS CLI authenticated to the target account (`aws sts get-caller-identity`).
- [x] `agentcore` CLI installed and on PATH (`agentcore --version`).
- [x] Docker running with ARM64 build support (the runtime image is ARM64).
- [x] Supabase schema already applied (`001_schema.sql`) with RLS deny-all.
- [x] `github_installations` row exists (real `installation_id`, `app_id`,
      `private_key_secret_arn`) — see block 1 of `002_seed.sql`.
- [x] Secrets Manager entries exist:
  - `agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY` (Supabase service role key)
  - the GitHub App private key referenced by `private_key_secret_arn`
- [x] Bedrock model access granted for `MODEL_ID`
      (default `us.anthropic.claude-sonnet-4-6`).

---

## Secrets Manager format

The agent reads two secrets from AWS Secrets Manager, both as **plaintext
`SecretString`** values (no JSON wrapper, no base64). Grounded in
`agents/dependency-update/app/dependencyUpdate/credentials.py`:
`fetch_supabase_key()` and `_fetch_pem()` both return `SecretString` verbatim,
and the PEM is passed straight into `jwt.encode(..., pem, algorithm="RS256")`.

### GitHub App private key (PEM)

Store the secret value as the **raw PEM exactly as GitHub emits it** — the full
text including the header/footer lines and all newlines:

```
-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEA1c3f...
...many base64 lines...
-----END RSA PRIVATE KEY-----
```

- **Do NOT** store it as JSON (e.g. `{"private_key": "..."}`) — the code does
  not parse JSON; the whole value is fed to the RS256 signer and signing fails.
- **Do NOT** base64-encode it — it must be the literal PEM text.
- Preserve the embedded newlines. A PKCS#8 `-----BEGIN PRIVATE KEY-----` block
  also works; store whatever GitHub gave you as-is.

Create it (CLI reads from the file so newlines are preserved and the key never
lands in shell history):

```bash
aws secretsmanager create-secret \
  --name "agent-fleet/prod/GITHUB_APP_PRIVATE_KEY" \
  --description "GitHub App private key (PEM) for dependency-update agent" \
  --secret-string "file://my-app.private-key.pem" \
  --region us-east-1
```

Rotate/update an existing one:

```bash
aws secretsmanager put-secret-value \
  --secret-id "agent-fleet/prod/GITHUB_APP_PRIVATE_KEY" \
  --secret-string "file://my-app.new.private-key.pem" \
  --region us-east-1
```

Then put this secret's **ARN** into `github_installations.private_key_secret_arn`
(block 1 of `002_seed.sql`) — the DB stores only the ARN, never the key. Name the
secret under `agent-fleet/prod/*` so it is covered by the IAM grant in step 7.6.

Verify it is a clean PEM (not JSON-wrapped):

```bash
aws secretsmanager get-secret-value \
  --secret-id "agent-fleet/prod/GITHUB_APP_PRIVATE_KEY" \
  --query SecretString --output text --region us-east-1 | head -1
# expect: -----BEGIN RSA PRIVATE KEY-----
```

### Supabase service role key

Separate secret at `agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY` (read by
`fetch_supabase_key`), also a plaintext `SecretString` — the raw service role
key string, nothing wrapped. Both secrets are covered by the same
`agent-fleet/prod/*` IAM grant in step 7.6.

- [x] GitHub App PEM stored as raw plaintext `SecretString` under `agent-fleet/prod/*`.
- [x] Its ARN placed in `github_installations.private_key_secret_arn`.
- [x] Supabase service role key stored as plaintext `SecretString`.

---

## 7.2 — Deploy the agent

```bash
cd agents/dependency-update
agentcore deploy -y
```

Expected: build succeeds, image pushed, runtime created/updated. Capture the
full console output in case of failure.

- [x] `agentcore deploy -y` completed without error.

---

## 7.3 — Confirm runtime ready + record the ARN

```bash
cd agents/dependency-update
agentcore status
```

Expected: runtime status `READY`. Copy the **runtime ARN** — it looks like:

```
arn:aws:bedrock-agentcore:us-east-1:<ACCOUNT_ID>:runtime/dependency_update-<suffix>
```

- [x] Status reports runtime `READY`.
- [x] `runtime_arn` recorded: `arn:aws:bedrock-agentcore:us-east-1:755641879575:runtime/dependencyupdate_dependency_update-UsQc5U5Yz0`

---

## 7.4 — Put the real ARN into the seed

Edit `docs/reference/002_seed.sql`, block 3, replacing the placeholder ARN
(`arn:aws:bedrock-agentcore:us-east-1:000000000000:runtime/dependency-update`)
with the ARN from step 7.3. Leave every other value as-is — timeouts are already
correct (`max_runtime_seconds=3600`, `grace_seconds=120`,
`start_timeout_seconds=300`), and `params_schema` / `default_params` already
carry `max_fix_attempts` (0..5) and `base_branch`.

> Ask the developer agent to make this one-line edit and commit it to the branch
> once you have the ARN, or edit it yourself and push.

- [x] `runtime_arn` in `002_seed.sql` updated to the real value.

---

## 7.5 — Apply the seed to Supabase  ⚠️ migration apply

> **Confirmation gate:** this writes to the production Supabase database. The
> seed is idempotent (`ON CONFLICT ... DO UPDATE`) — it upserts one installation,
> the repo list, and the `dependency-update` agent row. It does **not** drop or
> truncate anything.

1. Open the Supabase project → **SQL Editor**.
2. Paste the full contents of `docs/reference/002_seed.sql` (with the real ARN).
3. Confirm blocks 1 and 2 (installation slug + repo list) match your real org
   and repositories before running — those are the "EDIT ONLY" blocks.
4. Run it.

**Rollback / impact notes:** re-running with different values re-upserts the same
rows (safe). To revert the agent row, re-run an earlier seed or
`update agents set runtime_arn = '<old>' where slug = 'dependency-update';`. No
destructive DDL is involved.

**Verify applied state** (block 4 of the seed prints counts):

```sql
select slug, runtime_arn, max_runtime_seconds, grace_seconds, start_timeout_seconds,
       default_params, params_schema
from agents where slug = 'dependency-update';
```

- [x] Seed applied; the `agents` row shows the real ARN and
      `max_runtime_seconds=3600`, `grace_seconds=120`, `start_timeout_seconds=300`.

---

## 7.6 — IAM permissions on the execution role  ⚠️ infra change

Grant the AgentCore **execution role** (the role the runtime assumes) exactly:

- `secretsmanager:GetSecretValue` on `arn:aws:secretsmanager:us-east-1:<ACCOUNT_ID>:secret:agent-fleet/prod/*`
- `bedrock:InvokeModel` on the Claude Sonnet model ARN for `MODEL_ID`

Example policy statement (scope the resources — do **not** use `*`):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadAgentFleetSecrets",
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": "arn:aws:secretsmanager:us-east-1:<ACCOUNT_ID>:secret:agent-fleet/prod/*"
    },
    {
      "Sid": "InvokeClaudeSonnet",
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-4-*"
    }
  ]
}
```

> Adjust the model resource ARN to match your exact `MODEL_ID` / inference
> profile. If using a cross-region inference profile, also allow
> `bedrock:InvokeModel` on the profile ARN and the underlying regional model ARNs.

- [x] Execution role can read `agent-fleet/prod/*` secrets.
- [x] Execution role can invoke the configured Bedrock model.

---

## E2E validation

> ⚠️ **Read before running 7.7–7.10 — two invocation gotchas found after these steps were
> executed** (details in
> [`issue-94-reaper-verification.md`](issue-94-reaper-verification.md) §4.0 and §4.1):
>
> 1. **`agentcore` CLI ≥ 0.28.0 wraps the prompt argument itself** — so the pre-wrapped
>    `'{"prompt": "{...}"}'` form used in the commands below arrived **double-wrapped** and died
>    with a generic `INVALID_PARAMS` when this runbook was executed.
>    **Resolved in [#97](https://github.com/llipe/dev-tasks-agent-fleet/issues/97):**
>    `unwrap_payload()` now strips nested `prompt` wrappers in a loop, so the pre-wrapped commands
>    below work verbatim again against CLI ≥ 0.28.0 (and a still-wrapper-only payload now fails with
>    a specific "appears double-wrapped" message instead of the generic one). The commands are kept
>    as the record of what was executed; the equivalent bare-JSON form
>    (`agentcore invoke --prompt-file /tmp/invoke.json`, file has no `prompt` key) also works.
> 2. **A direct `agentcore invoke` does not create the `runs` row.** Per D1 the control plane
>    (front-end, Phase 2) inserts the `queued` row and the agent only PATCHes it, so a run invoked
>    by hand stays invisible in `runs`/`v_runs` with no error anywhere. Insert the `queued` row
>    first — see §4.0 of the reaper runbook. Tracked as
>    [#100](https://github.com/llipe/dev-tasks-agent-fleet/issues/100).

Generate a UUID per run (`uuidgen` or `python3 -c "import uuid;print(uuid.uuid4())"`).
The payload is wrapped in a `prompt` key (JSON string); as of #97 the CLI ≥ 0.28.0 double-wrap is
handled, so the commands below are usable as written.

### 7.7 — audit_only on a clean repo

```bash
agentcore invoke '{"prompt": "{\"run_id\":\"<uuid>\",\"repository_org\":\"<org>\",\"repository_name\":\"<clean-repo>\",\"params\":{\"fix_mode\":\"audit_only\"}}"}'
```

Verify in Supabase:

```sql
select status, outcome, error_code, metrics from runs where id = '<uuid>';
select seq, key, status from run_steps where run_id = '<uuid>' order by seq;
select count(*) from run_events where run_id = '<uuid>';
select type from run_artifacts where run_id = '<uuid>';
```

- [x] `runs`: `status=succeeded`, `outcome=no_vulnerabilities`.
- [x] `run_steps`: `resolve_credentials, checkout, detect_toolchain, install, audit` present.
- [x] `run_events`: rows present (non-zero).
- [x] `run_artifacts`: an `audit_report` row present; **no** `pull_request`.

### 7.8 — llm_fix on a repo with available updates

```bash
agentcore invoke '{"prompt": "{\"run_id\":\"<uuid2>\",\"repository_org\":\"<org>\",\"repository_name\":\"<repo-with-vulns>\",\"params\":{\"fix_mode\":\"llm_fix\",\"max_fix_attempts\":3}}"}'
```

- [x] A PR was opened on the target repo (branch `deps/update-YYYYMMDD-HHMMSS`).
- [x] `run_artifacts` has a `pull_request` row with the PR URL.
- [x] `runs.outcome` is one of `fixed` / `partial` (or `needs_review` if a major
      bump remains — the PR is still opened first).

### 7.9 — Idempotency: second invoke while the PR is open

Re-run the **same** command as 7.8 with a new `run_id` while the PR from 7.8 is
still open.

```bash
agentcore invoke '{"prompt": "{\"run_id\":\"<uuid3>\",\"repository_org\":\"<org>\",\"repository_name\":\"<repo-with-vulns>\",\"params\":{\"fix_mode\":\"llm_fix\",\"max_fix_attempts\":3}}"}'
```

- [ ] `runs`: `status=succeeded`, `outcome=not_applicable`.
- [ ] **No** second PR opened; `run_artifacts` records the **existing** PR URL.

### 7.10 — Invalid payload

```bash
agentcore invoke '{"prompt": "{\"run_id\":\"<uuid4>\"}"}'   # missing org + name
```

- [x] `runs`: `status=failed`, `error_code=INVALID_PARAMS`.
- [x] No `checkout` step (no clone happened).

### 7.11 — Metrics populated

For the 7.8 (llm_fix) run:

```sql
select metrics from runs where id = '<uuid2>';
```

Expect a JSON object containing:

- [x] `llm_used` (bool) — `true` if the fix loop ran.
- [x] `fix_attempts` (int, 0..5).
- [x] `vulnerabilities_before`, `vulnerabilities_after`.
- [x] `advisories_fixed`, `advisories_major_required`, `advisories_unknown`.
- [x] `packages_changed`.

---

## Related — stale-run reaper

Scheduling the `pg_cron` reaper and verifying stale-run detection (`timed_out` /
`failed_to_start`) were **not** part of issue #77 and are covered separately in
[`issue-94-reaper-verification.md`](issue-94-reaper-verification.md). That runbook
also documents two gotchas discovered while verifying, which affect the invocation
steps in **E2E validation** above (repeated as a warning there, since a reader working
top-down reaches 7.7 before this section):

- **A direct `agentcore invoke` does not create the `runs` row** — the control plane
  (front-end, Phase 2) inserts it; the agent SDK only updates it. Insert the `queued`
  row first or the run stays invisible.
- **`agentcore` CLI ≥ 0.28.0 wraps the prompt itself**, so the pre-wrapped
  `'{"prompt": "..."}'` form used in steps 7.7–7.10 arrives double-wrapped and
  fails with `INVALID_PARAMS`. Pass the bare inner JSON via `--prompt-file` instead.

## After completing all steps

Report back to the developer agent with:

1. The recorded `runtime_arn`.
2. Confirmation the seed was applied (and the block-4 counts).
3. The per-check results of 7.7–7.11 (pass/fail + observed `status`/`outcome`).
4. The PR URL opened in 7.8 (if any).

The developer agent will then mark sub-tasks 7.2–7.11 complete, sync the GitHub
issue checklist, run the completion-gate agents (qa-engineer, verifier,
technical-writer), and convert PR #88 to Ready for Review.
