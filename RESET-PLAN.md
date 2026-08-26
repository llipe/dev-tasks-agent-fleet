# Project Reset Plan — dev-tasks-agent-fleet

## Phase 1: AWS Resource Teardown

The project has resources in AWS account `755641879575` (us-east-1). Tear down in dependency order (reverse of creation).

> **Working directory for all commands below:** Any directory (all use AWS CLI directly).
>
> **Note:** `cdk destroy` does not work under Node.js v26 due to an incompatibility in
> `aws-cdk-lib@2.266.0`. Since we're tearing everything down, we use
> `aws cloudformation delete-stack` directly for all stacks.

### Step 1 — Delete AgentCore runtime stack

> Run from: any directory

The AgentCore CLI has no `destroy` command. Delete the CloudFormation stack directly.

```bash
# Delete the AgentCore-managed stack
aws cloudformation delete-stack --stack-name AgentCore-depupdater-default --region us-east-1

# Wait for deletion to complete
aws cloudformation wait stack-delete-complete --stack-name AgentCore-depupdater-default --region us-east-1
```

If the stack deletion fails (e.g., retained resources), delete the Bedrock runtime manually first:

```bash
# Check runtime status
aws bedrock-agent get-agent-runtime --agent-runtime-id depupdater_dep_updater-M4gkuL4wSr --region us-east-1

# Delete the runtime
aws bedrock-agent delete-agent-runtime --agent-runtime-id depupdater_dep_updater-M4gkuL4wSr --region us-east-1

# Retry stack deletion
aws cloudformation delete-stack --stack-name AgentCore-depupdater-default --region us-east-1
```

### Step 2 — Delete Orchestration stack

> Run from: any directory

```bash
aws cloudformation delete-stack --stack-name AgentFleetOrchestrationStack --region us-east-1
aws cloudformation wait stack-delete-complete --stack-name AgentFleetOrchestrationStack --region us-east-1
```

Removes: Lambda `agent-fleet-orchestrator`, EventBridge rule `agent-fleet-dep-updater-schedule`.

### Step 3 — Delete IAM stack

> Run from: any directory

```bash
aws cloudformation delete-stack --stack-name AgentFleetIamStack --region us-east-1
aws cloudformation wait stack-delete-complete --stack-name AgentFleetIamStack --region us-east-1
```

Removes: IAM roles (`agent-fleet-control-plane-role`, `agent-fleet-orchestrator-role`, `agent-fleet-agent-exec-role`), OIDC provider (`oidc.fly.io/felipe-mallea`).

### Step 4 — Delete Data stack

> Run from: any directory

The DynamoDB table has `DeletionProtection: enabled` and `RemovalPolicy: RETAIN`, so CloudFormation delete alone won't remove it.

```bash
# First, disable deletion protection on the table
aws dynamodb update-table --table-name agent-fleet-config --no-deletion-protection-enabled --region us-east-1

# Delete the table manually (since RemovalPolicy is RETAIN, CF won't delete it)
aws dynamodb delete-table --table-name agent-fleet-config --region us-east-1

# Now destroy the CDK stack (will succeed since the table is already gone)
aws cloudformation delete-stack --stack-name AgentFleetDataStack --region us-east-1
aws cloudformation wait stack-delete-complete --stack-name AgentFleetDataStack --region us-east-1
```

### Step 5 — Delete Secrets Manager secrets

> Run from: any directory

```bash
aws secretsmanager delete-secret \
  --secret-id dep-agent/github-app \
  --force-delete-without-recovery \
  --region us-east-1
```

### Step 6 — Clean up CloudWatch Log Groups

> Run from: any directory

```bash
aws logs delete-log-group --log-group-name /aws/lambda/agent-fleet-orchestrator --region us-east-1
aws logs delete-log-group --log-group-name aws/spans --region us-east-1

# AgentCore runtime logs (may have a generated suffix — list first)
aws logs describe-log-groups --log-group-name-prefix /aws/bedrock-agentcore/runtimes/depupdater --region us-east-1

# Then delete each one found:
# aws logs delete-log-group --log-group-name "<full-name-from-above>" --region us-east-1
```

### Step 7 — Delete ECR repository (if exists)

> Run from: any directory

```bash
# List repos to find any AgentCore-managed ones
aws ecr describe-repositories --region us-east-1 | grep -i "depupdater\|agentcore"

# If found, force-delete (removes all images):
# aws ecr delete-repository --repository-name <repo-name> --force --region us-east-1
```

### Step 8 — Verify all stacks are gone

> Run from: any directory

```bash
aws cloudformation list-stacks \
  --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE \
  --region us-east-1 \
  --query "StackSummaries[?contains(StackName, 'AgentFleet') || contains(StackName, 'AgentCore')]"
```

---

## Phase 2: Fly.io Teardown

> Run from: any directory

```bash
flyctl apps destroy dt-agent-fleet-control-plane --yes
```

## Phase 3: Git Repository Reset

| # | Action | Details |
|---|--------|---------|
| 1 | Create reset branch | `git checkout -b chore/project-reset` from main |
| 2 | Remove all application code | Delete `infra/`, `apps/`, `agents/`, `packages/`, `docs/` (workstream content), and deployment configs |
| 3 | Keep repo scaffolding | Retain `.gitignore`, `.nvmrc`, `.prettierrc`, `.github/` (stripped of deploy workflows), and essential root config |
| 4 | Add fresh foundation files | New `DESIGN.md`, `package.json` (pnpm workspace root), `README.md` with the new scope |
| 5 | Open PR to main | PR documents the reset rationale and new scope |
| 6 | Clean up old branches | After merge, delete all `story/*` and `issue/*` branches (local + remote) |

## Phase 4: Redefine Base Scope

Questions to answer before writing the new DESIGN.md:

1. **Are you keeping the same concept?** (autonomous agent fleet for dev tasks, orchestrated on a schedule)
2. **What's staying?** Do you want to keep any technology choices (pnpm monorepo, CDK, Python agents, Next.js control plane)?
3. **What's changing?** Did anything about the architecture feel wrong — e.g., Bedrock AgentCore complexity, Fly.io for the control plane, the DynamoDB config store?
4. **What agents do you want in v2?** Still starting with dep-updater, or different scope?
5. **What's the MVP?** What's the minimum you want working end-to-end before expanding?

## Execution Order Summary

```
1. Tear down AWS (Phase 1) — avoid ongoing costs
2. Tear down Fly.io (Phase 2)
3. Create reset branch & PR (Phase 3)
4. Define new scope together (Phase 4)
5. Start fresh implementation on a clean branch
```
