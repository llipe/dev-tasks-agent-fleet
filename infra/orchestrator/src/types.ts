/**
 * Shared types for the orchestrator Lambda.
 */

/** EventBridge event payload */
export interface OrchestratorEvent {
  agent: string;
  scheduledAt: string;
}

/** Subject (repo) info from DynamoDB query */
export interface ScopeEntry {
  subjectId: string;
  enabled: boolean;
  params: Record<string, unknown>;
}

/** Global agent config from DynamoDB */
export interface AgentConfig {
  agentName: string;
  defaultParams: Record<string, unknown>;
}

/** The payload sent to InvokeAgentRuntime */
export interface InvocationPayload {
  session_id: string;
  repo: string;
  params: Record<string, unknown>;
}

/** Result of a single invocation attempt */
export interface InvocationResult {
  repo: string;
  sessionId: string;
  status: "invoked" | "failed";
  error?: string;
}
