/**
 * Observability configuration constants.
 *
 * SPANS_LOG_GROUP: The CloudWatch Logs group where AgentCore delivers
 * OpenTelemetry spans for the dep-updater agent. All Logs Insights queries
 * in the control plane read from this value — never hardcode the group name.
 *
 * SPANS_RETENTION_DAYS: The retention period for the spans log group.
 * This is the real bound on how far back any view can look.
 */

/**
 * CloudWatch Logs group for agent spans.
 *
 * With `UNIFIED_TRACES_DESTINATION_ENABLED=true`, AgentCore delivers spans to
 * a `spans` log stream inside the agent's own log group, whose name follows the
 * pattern `/aws/bedrock-agentcore/runtimes/<agentId>-<endpointName>`.
 *
 * The previous value was the shared `aws/spans` group. That group is an
 * AWS-reserved name whose lifecycle is controlled by Transaction Search. It was
 * deleted from the account (cause unknown) and cannot be recreated — AWS rejects
 * `create-log-group` with `InvalidParameterException: Log groups starting with
 * AWS/ are reserved for AWS`. Since its existence cannot be guaranteed, the
 * per-agent destination is the robust path.
 *
 * For v1, there is exactly one agent. The constant is the actual group name,
 * which matches what `GetAgentRuntime` returns and what `AGENT_LOG_GROUP` is
 * set to on the control-plane Fly app. If a second agent is added, this becomes
 * a function or an array — at that point the Logs Insights adapter switches to
 * `logGroupIdentifiers` (supports up to 50 groups).
 *
 * History:
 *   - Original: `/aws/vendedlogs/agentcore/dep-updater/spans` (never existed)
 *   - Defect D2 fix (#56): corrected to `aws/spans`
 *   - Issue #62: `aws/spans` deleted from account; switched to per-agent group
 */
export const SPANS_LOG_GROUP =
  "/aws/bedrock-agentcore/runtimes/depupdater_dep_updater-M4gkuL4wSr-DEFAULT" as const;

/**
 * The log stream within SPANS_LOG_GROUP that carries span records.
 * Used to narrow FilterLogEvents queries when only spans are needed.
 */
export const SPANS_LOG_STREAM = "spans" as const;

/** Retention period in days for the spans log group */
export const SPANS_RETENTION_DAYS = 30 as const;
