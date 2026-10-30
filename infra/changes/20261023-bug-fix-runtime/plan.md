# Change plan: 20261023-bug-fix-runtime

- **ChangeId:** `infra/changes/20261023-bug-fix-runtime/`
- **Story / issue:** S-181 (#363), planner run `bug-fix-agent-wave-a`, branch `story/S-181-infra-runtime` → draft PR into `integration/bug-fix-agent-wave-a`
- **Environment:** `prod` (`production: true`). AWS account `755641879575` (the personal account, not Riel or ThinkFirst), region `us-east-1`.
- **Identity:** `arn:aws:iam::755641879575:root`. **Root accepted explicitly by @llipe on 2026-10-23** ("use root"). Recommended against; recorded here by name.
- **Tools:** aws-cli 2.38.2, agentcore 0.28.0 (`@aws/agentcore`, pinned to match the 2026-10-13 deploys), yq 4.54.1, gh 2.102.0, docker 29.8.2.
- **Approval status:** plan and costs **approved by @llipe on 2026-10-23**. Each step still needs its own approval.

## Cost (threshold $0: any new recurring cost is approved by name)

| Item | Estimate / month | Source | Status |
| ---- | ---------------- | ------ | ------ |
| 2 new Secrets Manager secrets (`ANTHROPIC_API_KEY`, `GITHUB_PROJECTS_TOKEN`) | $0.80 ($0.40 each) + negligible API calls | https://aws.amazon.com/secrets-manager/pricing/ | **APPROVAL REQUIRED** |
| New ECR repository (`bugfix/bug_fix`), one image of about 1.5 GB (Node + Python + Claude Code) | about $0.15 ($0.10/GB) | https://aws.amazon.com/ecr/pricing/ | **APPROVAL REQUIRED** |
| AgentCore runtime (`bug_fix`), idle | $0 idle; billed per invocation (CPU and memory seconds) | https://aws.amazon.com/bedrock/agentcore/pricing/ | **APPROVAL REQUIRED** (usage-based) |
| CloudWatch Logs for the runtime log group | a few cents at low volume | https://aws.amazon.com/cloudwatch/pricing/ | **APPROVAL REQUIRED** (usage-based) |
| KMS customer-managed key for the ECR repository (found in the step-7 diff) | about $1.00 | https://aws.amazon.com/kms/pricing/ | **APPROVED by @llipe on 2026-10-23** |
| CodeBuild ARM build per deploy | a few cents per deploy | https://aws.amazon.com/codebuild/pricing/ | **APPROVED by @llipe on 2026-10-23** |
| Anthropic API usage | Billed by Anthropic, capped by the key's spend limit (operator-set) | console.anthropic.com | Operator decision (step 2) |

## Design note: removing the Bedrock grant (task 2.13, DF-180-04)

`@aws/agentcore-cdk` 0.1.0-alpha.49 (`AgentCoreRuntime.js:70-90, 328-341`) adds `bedrock:InvokeModel*` on all foundation models to the role it creates. When the agent spec sets **`executionRoleArn`**, the construct imports that role read-only and **attaches no permissions**. So this change creates a dedicated role `agent-fleet-bug-fix-runtime`, with the construct's runtime permissions **minus Bedrock**, plus read access to exactly four secrets, and points `agentcore.json` at it. A deploy can't re-add the Bedrock grant later. This replaces the sibling pattern (a CDK role plus a hand-added `agent-fleet-secrets-and-bedrock` inline policy).

## Steps

### Step 1: create secret `agent-fleet/prod/ANTHROPIC_API_KEY` (no value)
- **Kind:** set secret · **Tool:** aws · **Touches state:** yes (a new resource, with no prior state to back up)
- **Backup:** none needed (new). Pre-check: `describe-secret` must return NotFound.
- **Forward:** `aws secretsmanager create-secret --region us-east-1 --name agent-fleet/prod/ANTHROPIC_API_KEY --description "bug-fix agent: dedicated, spend-capped Anthropic API key (D-50, D-58). Value set by the operator." --tags Key=environment,Value=prod Key=owner,Value=llipe Key=ChangeId,Value=20261023-bug-fix-runtime Key=agent,Value=bug-fix`
- **Verify:** `describe-secret` shows the ARN and tags, with no versions yet.
- **Revert:** `aws secretsmanager delete-secret --region us-east-1 --secret-id agent-fleet/prod/ANTHROPIC_API_KEY --force-delete-without-recovery`

### Step 2: operator sets the Anthropic key value
- **Kind:** set secret (operator) · **Tool:** aws (run by @llipe) · **Touches state:** yes
- **Forward (operator only; the value never enters this session):** create a dedicated key at console.anthropic.com with a **spend limit**, then put the value through the AWS console, or with `! aws secretsmanager put-secret-value --region us-east-1 --secret-id agent-fleet/prod/ANTHROPIC_API_KEY --secret-string "$(pbpaste)"`.
- **Verify:** `describe-secret` shows a version with stage `AWSCURRENT`. The value is never read.
- **Revert:** `aws secretsmanager delete-secret` as in step 1, plus revoking the key in the Anthropic console.

### Step 3: create secret `agent-fleet/prod/GITHUB_PROJECTS_TOKEN` (no value)
- **Kind:** set secret · **Tool:** aws · **Touches state:** yes (new)
- **Forward:** like step 1, with `--name agent-fleet/prod/GITHUB_PROJECTS_TOKEN --description "bug-fix agent: classic PAT, project scope only, Projects v2 board updates (D-99). Value set by the operator."` and the same tags.
- **Verify / Revert:** as in step 1.

### Step 4: operator sets the Projects token value
- **Kind:** set secret (operator) · **Tool:** aws (run by @llipe) · **Touches state:** yes
- **Forward:** create a GitHub **classic** PAT with **only `project`**, then put the value as in step 2. Record the expiry date in `result.md`.
- **Verify / Revert:** as in step 2, plus revoking the PAT on GitHub.

### Step 5: create IAM role `agent-fleet-bug-fix-runtime` (no Bedrock)
- **Kind:** create IAM policy + attach · **Tool:** aws · **Touches state:** yes (new)
- **Backup:** none needed (new). Pre-check: `get-role` returns NoSuchEntity (confirmed in discover).
- **Forward:**
  1. `aws iam create-role --role-name agent-fleet-bug-fix-runtime --assume-role-policy-document file://infra/changes/20261023-bug-fix-runtime/role-trust.json --tags Key=environment,Value=prod Key=owner,Value=llipe Key=ChangeId,Value=20261023-bug-fix-runtime`
  2. `aws iam put-role-policy --role-name agent-fleet-bug-fix-runtime --policy-name bug-fix-runtime --policy-document file://infra/changes/20261023-bug-fix-runtime/role-policy.json`

  The trust allows `bedrock-agentcore.amazonaws.com` with `aws:SourceAccount = 755641879575`. The policy covers CloudWatch Logs on `/aws/bedrock-agentcore/runtimes/*`, X-Ray, the AgentCore configuration-bundle actions, ECR pull on `repository/bugfix/*` plus `GetAuthorizationToken`, and `secretsmanager:GetSecretValue` on exactly four secret ARNs. It has **no `bedrock:*`**.
- **Verify:** `get-role-policy` matches the file; the step 8 simulation.
- **Revert:** `aws iam delete-role-policy --role-name agent-fleet-bug-fix-runtime --policy-name bug-fix-runtime && aws iam delete-role --role-name agent-fleet-bug-fix-runtime`

### Step 5b: add `EcrImageDecrypt` to the role (found in the step-7 diff)
- **Kind:** attach IAM policy · **Tool:** aws · **Touches state:** yes
- **Why:** an imported role gets no `kms:Decrypt` on the repository's new KMS key from the construct, so the runtime couldn't pull its encrypted image.
- **Backup:** `backup/role-policy.step5.json`
- **Forward:** add `kms:Decrypt` on `arn:aws:kms:us-east-1:755641879575:key/*`, conditioned on `kms:ViaService = ecr.us-east-1.amazonaws.com`, then `put-role-policy`. It can be narrowed to the exact key after the deploy.
- **Verify:** the live policy equals the file, with 0 `bedrock:` actions.
- **Revert:** `put-role-policy` with `backup/role-policy.step5.json`.

### Step 6: point the agent at the role (repo + local target)
- **Kind:** pipeline change · **Tool:** git · **Touches state:** no (repo files only)
- **Forward:**
  - set `"executionRoleArn": "arn:aws:iam::755641879575:role/agent-fleet-bug-fix-runtime"` on runtime `bug_fix` in `agents/bug-fix/agentcore/agentcore.json`;
  - create the local, gitignored `agents/bug-fix/agentcore/aws-targets.json` with target `default` → `755641879575` / `us-east-1`;
  - commit on `story/S-181-infra-runtime`.
- **Verify:** `agentcore` validates the project (the deploy preview in step 7 shows the imported-role warning).
- **Revert:** `git revert <commit>`; delete the local `aws-targets.json`.

### Step 7: deploy the bug-fix runtime (CDK)
- **Kind:** build image + deploy app · **Tool:** agentcore (CDK) · **Touches state:** yes (a new CloudFormation stack, ECR repository, image and runtime)
- **Backup:** none needed (new stack). Pre-check: `list-agent-runtimes` shows no `bugfix_bug_fix`.
- **Forward:** `cd agents/bug-fix && agentcore deploy -y`
- **Verify:**
  - `agentcore status` shows READY;
  - `get-agent-runtime` shows `roleArn` equal to `agent-fleet-bug-fix-runtime`;
  - record the runtime ID and ARN;
  - the image is ARM64 and the digest is recorded.
- **Revert:** destroy the stack (`agentcore` remove/destroy for this project, or `aws cloudformation delete-stack --stack-name <stack>`), then `aws ecr delete-repository --repository-name bugfix/bug_fix --force` if the stack retains it.

### Step 8: verify the runtime role permissions (read-only)
- **Kind:** discover · **Tool:** aws · **Touches state:** no
- **Forward:** `aws iam simulate-principal-policy --policy-source-arn arn:aws:iam::755641879575:role/agent-fleet-bug-fix-runtime` with:
  - **allow** `secretsmanager:GetSecretValue` on the four ARNs;
  - **deny** it on another secret (`agent-fleet/prod/does-not-exist`);
  - **deny** `bedrock:InvokeModel` on a Sonnet foundation model.
- **Verify / Revert:** n/a (read-only); results go in `result.md`.

### Step 9: panel invoke policy (file + live IAM)
- **Kind:** attach IAM policy · **Tool:** aws · **Touches state:** yes
- **Backup:** `aws iam get-role-policy --role-name panel-agentcore-invoke --policy-name invoke-runtime > infra/changes/20261023-bug-fix-runtime/backup/panel-invoke-policy.before.json`
- **Forward:** add the new runtime ARN and `…/runtime-endpoint/DEFAULT` to `infra/agentcore-invoke-policy.json`, then `aws iam put-role-policy --role-name panel-agentcore-invoke --policy-name invoke-runtime --policy-document file://infra/agentcore-invoke-policy.json`
- **Verify:** `get-role-policy` lists six resources, and `simulate-principal-policy` allows `bedrock-agentcore:InvokeAgentRuntime` on the new ARN.
- **Revert:** `aws iam put-role-policy --role-name panel-agentcore-invoke --policy-name invoke-runtime --policy-document file://infra/changes/20261023-bug-fix-runtime/backup/panel-invoke-policy.before.json`

### Step 10: operator grants the GitHub App Issues read and write
- **Kind:** foundation change (GitHub App settings) · **Tool:** GitHub UI (run by @llipe) · **Touches state:** yes
- **Forward:** GitHub → Settings → Developer settings → GitHub Apps → (fleet App) → Permissions → **Issues: Read and write** → save. Then accept the permission update on every installation in `github_installations`.
- **Verify:** a token-mint probe (local; prints only the `permissions` object and the installation id, never the token or PEM) shows `issues: write` for each installation.
- **Revert:** set Issues back to the previous level in the App settings.

### Step 11: deployed smoke check (read-only on AWS)
- **Kind:** verification invocation · **Tool:** aws (`bedrock-agentcore invoke-agent-runtime`) · **Touches state:** no AWS state (CloudWatch logs only)
- **Forward:** invoke the runtime with a minimal payload.
- **Verify:** the stub answers. This proves the image runs under the new role and reads its config.
- **Note:** S-181 AC4's *panel* invoke needs the `agents` seed row, so it's deferred to S-184. That deferral is recorded.
- **Revert:** n/a.

### Step 12: environment declaration, runbook stub, records, draft PR
- **Kind:** repo and PR operation · **Tool:** git / gh · **Touches state:** no
- **Forward:**
  - add `bug-fix` to `infra/environments.yaml` (runtime ID, ECR repository, project dir, execution role);
  - create the runbook stub `docs/runbooks/bug-fix-agent.md` (deploy, verify, secrets, rotation) and index it;
  - commit `commands.sh`, `rollback.sh` and `result.md`;
  - `github-ops` opens a draft PR into `integration/bug-fix-agent-wave-a`.
- **Revert:** close the PR, revert the commits.

Order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 (task 2.13 = steps 5–6, done before the deploy in step 7).
