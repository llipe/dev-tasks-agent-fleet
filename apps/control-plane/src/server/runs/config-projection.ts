/**
 * Config-row-to-Run projection — S-018.
 *
 * Projects a SubjectAgentItem (from DynamoDB) into a Run object
 * by applying deriveStatus with per-agent maxLifetime.
 *
 * The result represents the "latest run" state as DynamoDB knows it,
 * even before spans have been ingested or when spans are unavailable.
 */

import { deriveStatus } from "@fleet/shared";
import type { SubjectAgent } from "../repository/scope-repository.js";
import type { ModelUsage } from "./span-to-run-mapper.js";

/**
 * A run projected from a DynamoDB config row.
 * Same shape as Run but with source: "config".
 */
export interface ConfigRun {
  sessionId: string;
  subjectId: string;
  agentName: string;
  status: string;
  outcomeType: string;
  outcomeUrl: string;
  startedAt: string;
  durationMs: number;
  perModel: ModelUsage[];
  source: "config";
}

/**
 * Project a SubjectAgent item into a ConfigRun.
 *
 * @param agent - The DynamoDB SubjectAgent row
 * @param maxLifetimeSeconds - The agent's maxLifetime in seconds (from agentcore.json); undefined → default
 * @param now - Current time in ms (for testability); defaults to Date.now()
 * @returns ConfigRun or null if essential fields are missing
 */
export function projectConfigRun(
  agent: SubjectAgent,
  maxLifetimeSeconds: number | undefined,
  now?: number,
): ConfigRun | null {
  // Cannot project without session ID or run timestamp
  if (!agent.lastSessionId || !agent.lastRunAt) {
    return null;
  }

  const maxLifetimeMs = maxLifetimeSeconds != null ? maxLifetimeSeconds * 1000 : undefined;
  const currentTime = now ?? Date.now();

  const status = deriveStatus(
    agent.lastStatus ?? "running",
    agent.lastRunAt,
    maxLifetimeMs,
    currentTime,
  );

  return {
    sessionId: agent.lastSessionId,
    subjectId: agent.subjectId,
    agentName: agent.agentName,
    status,
    outcomeType: "",
    outcomeUrl: agent.lastOutcomeUrl ?? "",
    startedAt: agent.lastRunAt,
    durationMs: 0, // Unknown from config — spans provide this
    perModel: [], // Unknown from config — spans provide this
    source: "config",
  };
}
