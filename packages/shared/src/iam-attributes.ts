/**
 * DynamoDB attribute allowlists for IAM `dynamodb:Attributes` conditions.
 *
 * These define which DynamoDB attributes each role is allowed to write,
 * enforcing write separation at the IAM layer.
 *
 * Key attributes (pk, sk) are always included in write sets because
 * DynamoDB requires them for conditional expressions and key references.
 */

/** Key attributes always required for DynamoDB operations */
export const KEY_ATTRIBUTES = ["pk", "sk"] as const;

/**
 * Control-plane role: manages scope configuration.
 * Can write `enabled` and `params` attributes.
 */
export const CONTROL_PLANE_WRITE_ATTRIBUTES = [...KEY_ATTRIBUTES, "enabled", "params"] as const;

/**
 * Orchestrator role: stamps run lifecycle metadata.
 * Can write `last_session_id`, `last_run_at`, `last_status`.
 */
export const ORCHESTRATOR_WRITE_ATTRIBUTES = [
  ...KEY_ATTRIBUTES,
  "last_session_id",
  "last_run_at",
  "last_status",
] as const;

/**
 * Agent execution role: stamps outcome only.
 * Can write `last_status` and `last_outcome_url` ONLY.
 * NO `PutItem` allowed (would replace entire item).
 */
export const AGENT_EXEC_WRITE_ATTRIBUTES = [
  ...KEY_ATTRIBUTES,
  "last_status",
  "last_outcome_url",
] as const;

/** All readable attributes (no restriction on reads, but listed for completeness) */
export const ALL_ITEM_ATTRIBUTES = [
  "pk",
  "sk",
  "subject_id",
  "created_at",
  "enabled",
  "params",
  "last_session_id",
  "last_run_at",
  "last_status",
  "last_outcome_url",
  "agent_name",
  "domain",
  "default_params",
] as const;

export type ControlPlaneWriteAttribute = (typeof CONTROL_PLANE_WRITE_ATTRIBUTES)[number];
export type OrchestratorWriteAttribute = (typeof ORCHESTRATOR_WRITE_ATTRIBUTES)[number];
export type AgentExecWriteAttribute = (typeof AGENT_EXEC_WRITE_ATTRIBUTES)[number];
