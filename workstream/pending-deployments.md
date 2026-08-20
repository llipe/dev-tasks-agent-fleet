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


---

## 4. Agent Deployment to AgentCore (S-006 through S-010) — DEFERRED

**Stack:** `AgentFleetAgentStack` (runtime config added)
**What it delivers:**

- Full agent runtime with non-blocking entrypoint (S-007)
- Structured JSON logging keyed by `session_id` (S-008)
- Control-plane payload envelope parsing (S-009)
- `llipe.*` span attribute emission (S-010)
- `agentcore.json` with `dep-updater` name, `PYTHON_3_13`, lifecycle values

**Manual steps required:**

1. Start Docker daemon
2. Build container:
   ```bash
   cd agents/dep-updater && docker build --platform linux/arm64 -t dep-updater:local .
   ```
3. Deploy to AgentCore:
   ```bash
   cd agents/dep-updater && agentcore deploy
   ```
4. Trigger one run against a test repository to validate:
   - Pipeline behaviour unchanged (S-006 AC)
   - Logs continue past 5 min / run completes without idle timeout kill (S-007 AC)
   - JSON log output with `session_id` in CloudWatch (S-008 AC)
   - `llipe.*` span attributes on root span in span log group (S-010 AC)

**Verification commands post-deploy:**

```bash
# Confirm spans have llipe.* attributes
aws logs filter-log-events \
  --log-group-name /aws/vendedlogs/agentcore/dep-updater/spans \
  --limit 5

# Confirm structured JSON logs with session_id
aws logs filter-log-events \
  --log-group-name /aws/agentcore/dep-updater \
  --filter-pattern '{ $.session_id = "<session-id-from-run>" }' \
  --limit 5

# Confirm /ping returned HealthyBusy during run (check agent logs for lifecycle events)
```

**Sub-tasks deferred:**

- 6.7 (partial): Docker build requires running Docker daemon
- 6.8: Deploy to AgentCore and trigger one run
- 6.9: Verify pipeline behaviour unchanged
- 7.9: Run exceeding 10 min completes without idle timeout kill
- 8.9: `FilterLogEvents` by `session_id` returns only that run
- 10.9: Query span destination, confirm `llipe.*` attributes present

**lifecycleConfiguration (recorded per sub-task 6.10):**

- `maxLifetime`: 3600 (seconds — 1 hour max session)
- `idleRuntimeSessionTimeout`: 300 (seconds — 5 min idle before stop)
