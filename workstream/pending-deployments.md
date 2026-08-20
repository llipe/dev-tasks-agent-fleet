# Pending Deployments — Agent Control Plane v1

Deployment steps deferred during implementation. Each requires your explicit confirmation before executing.

---

## 1. DynamoDB Table + GSI1 (S-003) ✅ DEPLOYED

**Stack:** `AgentFleetDataStack`
**Status:** Deployed and seeded.

---

## 2. IAM Roles (S-004) ✅ DEPLOYED

**Stack:** `AgentFleetIamStack`
**Status:** Deployed. Integration tests require `AWS_ACCOUNT_ID` env var to validate denials live.

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
