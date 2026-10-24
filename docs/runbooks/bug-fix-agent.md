---
name: runbook-bug-fix-agent
trigger: Deploying or redeploying the bug-fix AgentCore runtime, rotating its Anthropic key or Projects token, or checking its permissions
owner: operator
last_verified: 2026-10-24
related: ["agents/bug-fix/agentcore/agentcore.json", "infra/changes/20261023-bug-fix-runtime/", "infra/agentcore-invoke-policy.json", "infra/environments.yaml"]
---

# Bug-fix agent: deploy, secrets, verification

How to deploy and verify the `bug-fix` AgentCore runtime (`bugfix_bug_fix-BiuPsdGSPK`, stack `AgentCore-bugfix-default`, account `755641879575`, `us-east-1`), and how to set or rotate its two dedicated secrets.

**Blast radius:**
- A deploy replaces the runtime's image and version.
- A secret change affects every subsequent run.
- The panel invoke policy is shared with the sibling agents. Change it only by adding resources.

> **Status (stub, S-181):** the runtime runs the S-180 scaffold. The panel can't invoke it until S-184 seeds the `agents` row. The `/bug-fix` webhook rule, the board, and live verification are documented in S-197. Follow-up #421 adds a panel Settings UI for the Projects token.

## Preconditions

- **Tools:**
  - AWS CLI 2.x, authenticated to account `755641879575` (the personal account, not Riel or ThinkFirst). Run `aws sts get-caller-identity`.
  - AgentCore CLI **0.28.0** (`npm i -g @aws/agentcore@0.28.0`; `agentcore --version`). Pinned to the version the fleet's CDK project (`@aws/agentcore-cdk` 0.1.0-alpha.49) was deployed with.
  - Node, Docker, yq 4.x.
- **Local target file (gitignored):** `agents/bug-fix/agentcore/aws-targets.json` = `[{"name":"default","account":"755641879575","region":"us-east-1"}]`.
- **CDK dependencies:** `cd agents/bug-fix/agentcore/cdk && npm ci`.
- **Infrastructure changes** go through `/infra-engineer` with a change record under `infra/changes/`.

## Design facts you need before changing anything

- **Imported execution role.** `agentcore.json` sets `executionRoleArn` = `arn:aws:iam::755641879575:role/agent-fleet-bug-fix-runtime`. With an imported role, the AgentCore construct attaches **no** permissions, so it never adds its default `bedrock:InvokeModel*` grant. **Do not remove `executionRoleArn`.**
- **The role's inline policy `bug-fix-runtime`** is versioned in `infra/changes/20261023-bug-fix-runtime/role-policy.json`. It grants:
  - runtime logs, X-Ray, and read-only configuration bundles;
  - ECR pull on `repository/bugfix/*`;
  - `kms:Decrypt` on the ECR repository key `429d9891-d1d3-4b6c-abe3-f8e8b5b6a2b8`, only through ECR;
  - `secretsmanager:GetSecretValue` on exactly four secret ARNs.

  It grants **no `bedrock:*`**.
- **Model:** the Anthropic API, through `ANTHROPIC_API_KEY` (D-50), not Bedrock.

## Steps

### Deploy or redeploy

1. Preview: `cd agents/bug-fix && agentcore deploy --diff -y`. Confirm the runtime keeps `RoleArnOutput = …/agent-fleet-bug-fix-runtime` and that no runtime role is created.
2. Deploy: `agentcore deploy -y`. This builds the image in CodeBuild and updates the runtime.
3. If a deploy recreates the ECR repository with a **new KMS key**, update `EcrImageDecrypt` in `role-policy.json` to the new key ARN, then `aws iam put-role-policy --role-name agent-fleet-bug-fix-runtime --policy-name bug-fix-runtime --policy-document file://infra/changes/20261023-bug-fix-runtime/role-policy.json`. Otherwise the runtime can't pull its image.
4. Commit the CLI's `agents/bug-fix/agentcore/.cli/deployed-state.json`.

### Set or rotate the Anthropic key (`agent-fleet/prod/ANTHROPIC_API_KEY`)

1. At console.anthropic.com, create a **dedicated** key with a **spend limit** (currently $30 USD/month).
2. Put it in from your own terminal, never through an agent session: `aws secretsmanager put-secret-value --region us-east-1 --secret-id agent-fleet/prod/ANTHROPIC_API_KEY --secret-string "$(pbpaste)"`, then clear the clipboard. Store it as a **plaintext** SecretString, not JSON.
3. Revoke the old key in the Anthropic console.

### Set or rotate the Projects token (`agent-fleet/prod/GITHUB_PROJECTS_TOKEN`)

1. On GitHub, create a **classic** PAT with **only the `project` scope**. The current token has no expiry, so rotation is manual.
2. Put it in the same way as the key (plaintext).
3. Revoke the old PAT. Board updates are best effort, so a missing or invalid token never fails a run (D-99).

### GitHub App permissions

The fleet App (`4687256`, installation `156226839`) needs **Issues: read and write**, plus contents and pull requests write. After any App permission change, accept it on every installation.

## Verification

- **Runtime:** `aws bedrock-agentcore-control get-agent-runtime --region us-east-1 --agent-runtime-id bugfix_bug_fix-BiuPsdGSPK` shows `READY`, and `roleArn` = `agent-fleet-bug-fix-runtime`.
- **Permissions:** `aws iam simulate-principal-policy --policy-source-arn arn:aws:iam::755641879575:role/agent-fleet-bug-fix-runtime --action-names secretsmanager:GetSecretValue bedrock:InvokeModel --resource-arns <the 4 secret ARNs> <a Sonnet foundation-model ARN>` shows the four secrets `allowed` and Bedrock `implicitDeny`. The reference evidence is `infra/changes/20261023-bug-fix-runtime/backup/simulation-8a.json`.
- **Panel invoke:** simulating `bedrock-agentcore:InvokeAgentRuntime` for role `panel-agentcore-invoke` on the bug-fix runtime ARN is `allowed`, and still `allowed` for both sibling runtimes.
- **Smoke invoke:** `aws bedrock-agentcore invoke-agent-runtime --region us-east-1 --agent-runtime-arn arn:aws:bedrock-agentcore:us-east-1:755641879575:runtime/bugfix_bug_fix-BiuPsdGSPK --runtime-session-id <≥33 chars> --payload "$(printf '{"run_id":"<uuid>","repository_org":"llipe","repository_name":"bug-fix-smoke","base_branch":"main","params":{}}' | base64)" out.json` returns HTTP 200. While it runs the stub, it answers `not_applicable` / `not yet implemented`.
- **App token:** minting an installation token shows `permissions.issues == "write"` (see `result.md`, step 10b). Print only the permissions, never the token.

## Rollback

`infra/changes/20261023-bug-fix-runtime/rollback.sh --from N` reverts steps N…1 in reverse order:
- 9: panel policy;
- 8: KMS scope;
- 7: stack;
- 5b and 5: role;
- 3 and 1: secrets.

Revoke the Anthropic key and the PAT at their providers as well. The panel policy rollback restores the four sibling resources exactly.

## Escalation

The operator (@llipe). AWS or Anthropic billing surprises: check the Anthropic key's spend limit and `runs.metrics` cost fields. The trace destination was set to CloudWatch Logs by the AgentCore CLI (X-Ray transaction search, account-wide).
