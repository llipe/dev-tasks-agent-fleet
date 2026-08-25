# Runbook: Observability Setup

This document records the observability infrastructure decisions and setup steps for the Agent Control Plane.

## 1. CloudWatch Transaction Search

### What

CloudWatch Transaction Search enables querying spans from the OpenTelemetry data collected by AgentCore's ADOT sidecar. Without it, spans exist only as raw log records.

### Steps to Enable

> **Already enabled on this account (2026-08-24) at 100% sampling.** The steps below are
> retained for reference; no action is needed.

1. Open the AWS Console > CloudWatch > **Application Signals (APM)** > **Transaction search**.
2. Enable Transaction Search if not already active.
3. Sampling is set to **100%** on this account (the PRD assumed 1% would suffice; 100% is also fine given low volume and only affects X-Ray trace summary indexing, not log ingestion).
4. Confirm and save.

### Why 100% is acceptable

The agent fleet produces a small number of spans (one root span + child spans per run). Even at 100% indexing, cost is negligible given volume. All spans are retained in the log group regardless of the indexing rate — Transaction Search indexing only affects the indexed/searchable subset via the console's trace explorer. Our Logs Insights queries operate on the log group directly and see 100% of spans regardless of this setting.

## 2. Span Destination

### Decision

A single span log group is used for all agent spans:

```
aws/spans
```

This is the group CloudWatch Transaction Search creates, and it is where AgentCore's ADOT sidecar actually delivers spans — verified against the live account (`755641879575`, `us-east-1`). Note there is **no leading slash**: the group name is literally `aws/spans`, and Logs Insights `StartQuery` rejects anything that does not match exactly.

### Rationale

- Two span destinations would require two Logs Insights queries in the control plane, adding latency and complexity.
- One shared group covers the whole fleet. Queries scope to a single agent by filtering on the `llipe.agent` resource attribute rather than by group name, so adding an agent needs no new group and no config change.
- Transaction Search manages the group's lifecycle, so it requires no additional provisioning.

### Config Value

The `SPANS_LOG_GROUP` configuration constant is set to:

```
aws/spans
```

This value is referenced by:

- The control plane's Logs Insights query builder
- The `SPAN_FIELDS` mapping in `packages/shared/src/span-fields.ts`

> **Historical note.** This section and `packages/shared/src/observability-config.ts` both previously recorded `/aws/vendedlogs/agentcore/dep-updater/spans`, an AgentCore default path that does not exist in the account. Every control-plane Logs Insights query therefore targeted a nonexistent group and the runs view could only return nothing. Corrected in issue #56 (defect D2); the specification's resolution of PRD open question #1 was always "Shared `aws/spans` log group".

## 3. Log-Group Retention Period

### Decision

**30 days** retention on the spans log group.

### Rationale (Closes PRD Open Question #6)

- 30 days matches the maximum date-range filter in the control plane UI (runs view is capped at 30 days).
- Beyond 30 days, operational value of individual run spans diminishes — aggregated cost data is stored in DynamoDB.
- 30 days keeps CloudWatch Logs storage costs minimal for the expected span volume.
- This is the **real bound** on how far back any view can look: the UI cannot show runs older than the retention window even if DynamoDB retains the metadata.

### Configuration

`aws/spans` already carries 30-day retention in the live account, so this is a verification step rather than a change. Re-applying it is idempotent:

```bash
aws logs put-retention-policy \
  --log-group-name aws/spans \
  --retention-in-days 30
```

The agent's own **application** log group is separate, and AgentCore creates it with no retention set. Its name ends in an AgentCore-generated suffix that changes whenever the runtime is recreated, so discover it instead of hardcoding it:

```bash
LG=$(aws logs describe-log-groups \
  --log-group-name-prefix /aws/bedrock-agentcore/runtimes/depupdater_dep_updater \
  --query 'logGroups[0].logGroupName' --output text)

aws logs put-retention-policy --log-group-name "$LG" --retention-in-days 30
```

## 4. Verification

After setup, verify:

1. **Transaction Search active**: Console > CloudWatch > Application Signals (APM) > Transaction search shows active status.
2. **Span log group exists**: `aws logs describe-log-groups --log-group-name-prefix aws/spans` returns the group.
3. **Retention set**: The `retentionInDays` field shows `30`.
4. **Spans arriving**: After one triggered agent run, `aws logs filter-log-events --log-group-name aws/spans --limit 5` returns span records.

   > **As of 2026-08-25, spans are NOT arriving.** `aws/spans` has `storedBytes=0`. The agent
   > declares `opentelemetry-api` and `opentelemetry-sdk` but no exporter package, so spans are
   > created in-process and dropped. Tracked as [#62](https://github.com/llipe/dev-tasks-agent-fleet/issues/62).
   > This verification step will pass only after an OTLP exporter is installed.
5. **Spans belong to the expected agent**: `aws/spans` is fleet-wide, so confirm the records carry the right agent attribute rather than assuming every record is the dep-updater's.

   ```bash
   aws logs filter-log-events --log-group-name aws/spans \
     --filter-pattern '{ $.resource.attributes."llipe.agent" = "dep-updater" }' \
     --limit 5
   ```
