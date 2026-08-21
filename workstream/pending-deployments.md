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

## 3. Observability + Discovery Tags (S-005) — PENDING

**What it requires (manual console steps):**

1. Enable CloudWatch Transaction Search at 1% sampling (console only)
2. Set span log group retention to 30 days:
   ```bash
   aws logs put-retention-policy \
     --log-group-name /aws/vendedlogs/agentcore/dep-updater/spans \
     --retention-in-days 30
   ```

---

## 4. Agent Deployment to AgentCore (S-006 through S-011) — PENDING

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



---

## 5. Orchestrator Lambda (S-013) — PENDING

**Stack:** `AgentFleetOrchestrationStack`
**What it creates:**

- Lambda function `agent-fleet-orchestrator` (Node.js 20, 60s timeout)
- EventBridge Scheduler rule (every 6 hours for dep-updater)
- Uses the `orchestrator-role` from S-004

**Commands:**

```bash
cd infra
pnpm run cdk diff AgentFleetOrchestrationStack
pnpm run cdk deploy AgentFleetOrchestrationStack
```

**Verification:**

```bash
# Manual trigger
aws lambda invoke \
  --function-name agent-fleet-orchestrator \
  --payload '{"agent":"dep-updater","scheduledAt":"2025-01-28T10:00:00Z"}' \
  /tmp/orchestrator-output.json

cat /tmp/orchestrator-output.json
```

---

## 6. Control Plane on Fly.io (S-024) — PENDING

**See `docs/runbook-deployment.md` for full instructions.**

Quick steps:

```bash
# One-time setup
flyctl apps create agent-fleet-control-plane --org <your-org>
fly secrets set CF_ACCESS_TEAM_NAME="<team>" \
  CF_ACCESS_AUD="<aud>" \
  AWS_REGION="us-east-1" \
  --app agent-fleet-control-plane

# Deploy
flyctl deploy --config infra/control-plane.fly.toml --remote-only
```

**Also requires:**
- Cloudflare Access application configured
- Cloudflare Tunnel pointing to the Fly app
- IAM OIDC trust policy for Fly → AWS

---

## Deployment Order (Complete)

```
1. ✅ AgentFleetDataStack   (table + GSI) — DONE
2. ✅ Run seed script — DONE
3. ✅ AgentFleetIamStack    (IAM roles) — DONE
4. 🔲 Observability setup   (console: Transaction Search + retention)
5. 🔲 Agent deploy          (docker build + agentcore deploy)
6. 🔲 Trigger one agent run (validates S-006 through S-011)
7. 🔲 AgentFleetOrchestrationStack (Lambda + EventBridge)
8. 🔲 Fly app + secrets     (control plane deployment)
9. 🔲 Cloudflare Access + Tunnel (origin lockdown)
```

## Notes

- All CDK stacks use `RemovalPolicy.RETAIN` — deleting the stack will NOT delete the table.
- Deletion protection is enabled on the DynamoDB table.
- IAM roles use `dynamodb:Attributes` condition keys for write separation.
- The seed script is idempotent (uses `attribute_not_exists` conditions). Safe to re-run.
- The control plane is stateless — all state lives in DynamoDB and CloudWatch. Rollback is a simple image swap.
