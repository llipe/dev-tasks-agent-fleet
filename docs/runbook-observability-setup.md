# Runbook: Observability Setup

This document records the observability infrastructure decisions and setup steps for the Agent Control Plane.

## 1. CloudWatch Transaction Search

### What

CloudWatch Transaction Search enables querying spans from the OpenTelemetry data collected by AgentCore's ADOT sidecar. Without it, spans exist only as raw log records.

### Steps to Enable

1. Open the AWS Console > CloudWatch > Settings > Traces and Metrics.
2. Under "Transaction Search", click **Edit**.
3. Set indexing to **1% sampling** (sufficient for our low-volume agent fleet; each agent runs at most once daily per repo).
4. Confirm and save.

### Why 1%

The agent fleet produces a small number of spans (one root span + child spans per run). Even at 1% indexing, all spans are retained in the log group — Transaction Search indexing only affects the indexed/searchable subset via the console's trace explorer. Our Logs Insights queries operate on the log group directly and see 100% of spans regardless of this setting.

## 2. Span Destination

### Decision

A single span log group is used for all agent spans:

```
/aws/vendedlogs/agentcore/dep-updater/spans
```

This is the AgentCore default span destination for the `dep-updater` agent runtime.

### Rationale

- Two span destinations would require two Logs Insights queries in the control plane, adding latency and complexity.
- The AgentCore default path is predictable and requires zero additional configuration.
- The path follows AWS vendored-logs conventions, which qualifies for standard CloudWatch pricing.

### Config Value

The `SPANS_LOG_GROUP` configuration constant is set to:

```
/aws/vendedlogs/agentcore/dep-updater/spans
```

This value is referenced by:

- The control plane's Logs Insights query builder
- The `SPAN_FIELDS` mapping in `packages/shared/src/span-fields.ts`

## 3. Log-Group Retention Period

### Decision

**30 days** retention on the spans log group.

### Rationale (Closes PRD Open Question #6)

- 30 days matches the maximum date-range filter in the control plane UI (runs view is capped at 30 days).
- Beyond 30 days, operational value of individual run spans diminishes — aggregated cost data is stored in DynamoDB.
- 30 days keeps CloudWatch Logs storage costs minimal for the expected span volume.
- This is the **real bound** on how far back any view can look: the UI cannot show runs older than the retention window even if DynamoDB retains the metadata.

### Configuration

Set via the AWS Console or CLI:

```bash
aws logs put-retention-policy \
  --log-group-name /aws/vendedlogs/agentcore/dep-updater/spans \
  --retention-in-days 30
```

## 4. Verification

After setup, verify:

1. **Transaction Search active**: Console > CloudWatch > Settings shows "Transaction Search: On".
2. **Span log group exists**: `aws logs describe-log-groups --log-group-name-prefix /aws/vendedlogs/agentcore/dep-updater/spans` returns the group.
3. **Retention set**: The `retentionInDays` field shows `30`.
4. **Spans arriving**: After one triggered agent run, `aws logs filter-log-events --log-group-name /aws/vendedlogs/agentcore/dep-updater/spans --limit 5` returns span records.
