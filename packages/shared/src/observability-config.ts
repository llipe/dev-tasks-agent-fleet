/**
 * Observability configuration constants.
 *
 * SPANS_LOG_GROUP: The single CloudWatch Logs group where AgentCore delivers
 * OpenTelemetry spans for the dep-updater agent. All Logs Insights queries
 * in the control plane read from this value — never hardcode the group name.
 *
 * SPANS_RETENTION_DAYS: The retention period for the spans log group.
 * This is the real bound on how far back any view can look.
 */

/** CloudWatch Logs group for agent spans (AgentCore default path) */
export const SPANS_LOG_GROUP = "/aws/vendedlogs/agentcore/dep-updater/spans" as const;

/** Retention period in days for the spans log group */
export const SPANS_RETENTION_DAYS = 30 as const;
