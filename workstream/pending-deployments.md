# Pending Deployments — Agent Control Plane v1

Deployment steps deferred during implementation. Each requires your explicit confirmation before executing.

---

## 1. DynamoDB Table + GSI1 (S-003)

**Stack:** `AgentFleetDataStack`
**What it creates:**

- DynamoDB table `agent-fleet-config` (on-demand, PITR, deletion protection)
- GSI1 inverted index (pk=sk, sk=pk, ALL projection)

**Commands:**

```bash
cd infra
pnpm run cdk diff AgentFleetDataStack   # review changes
pnpm run cdk deploy AgentFleetDataStack  # deploy
```

**Post-deploy: run seed script**

```bash
pnpm --filter @fleet/infra run seed
```

**Verification:**

```bash
aws dynamodb describe-table --table-name agent-fleet-config --query "Table.TableStatus"
# Expected: "ACTIVE"

aws dynamodb query \
  --table-name agent-fleet-config \
  --index-name GSI1 \
  --key-condition-expression "sk = :meta" \
  --expression-attribute-values '{":meta": {"S": "META"}}' \
  --select COUNT
# Expected: Count matches number of repos in infra/seed/repos.json
```

---

## 2. IAM Roles (S-004)

**Stack:** `AgentFleetIamStack`
**What it creates:**

- `agent-fleet-control-plane-role` — read + write scope config, deny InvokeAgentRuntime
- `agent-fleet-orchestrator-role` — read + write run lifecycle, InvokeAgentRuntime
- `agent-fleet-agent-exec-role` — UpdateItem on `last_status`/`last_outcome_url` only, deny PutItem

**Depends on:** DynamoDB table deployed first (cross-stack reference for table ARN).

**Commands:**

```bash
cd infra
pnpm run cdk diff AgentFleetIamStack   # review changes
pnpm run cdk deploy AgentFleetIamStack  # deploy
```

**Verification:**

```bash
# Verify roles exist
aws iam get-role --role-name agent-fleet-control-plane-role --query "Role.Arn"
aws iam get-role --role-name agent-fleet-orchestrator-role --query "Role.Arn"
aws iam get-role --role-name agent-fleet-agent-exec-role --query "Role.Arn"

# Run integration tests to validate denials
pnpm --filter @fleet/infra run test:integration -- iam
```

---

## 3. Observability + Discovery Tags (S-005) — upcoming

**Stack:** `AgentFleetAgentStack` (tags added)
**What it adds:**

- Tags: `agent:managed=true`, `agent:name=dep-updater`, `agent:domain=security`
- CloudWatch Transaction Search enabled (manual console step)
- `SPANS_LOG_GROUP` configured

_This deployment will be documented after S-005 implementation._

---

## Deployment Order

```
1. AgentFleetDataStack  (table + GSI)
2. Run seed script
3. AgentFleetIamStack   (IAM roles — requires table ARN from step 1)
4. Verify integration tests pass with live resources
```

## Notes

- All stacks use `RemovalPolicy.RETAIN` — deleting the stack will NOT delete the table.
- Deletion protection is enabled on the table — you must disable it manually before any destructive action.
- IAM roles use `dynamodb:Attributes` condition keys for write separation. The integration tests (`pnpm --filter @fleet/infra run test:integration -- iam`) validate these denials against live AWS.
- The seed script is idempotent (uses `attribute_not_exists` conditions). Safe to re-run.
