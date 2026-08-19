/**
 * DynamoDB key builders and prefix constants.
 * Single source of truth for all key structure in the agent-fleet-config table.
 */

export const PREFIXES = {
  SUBJECT: "SUBJECT#",
  AGENT: "AGENT#",
} as const;

/** Sort-key value for subject metadata items */
export const META = "META" as const;

/** Sort-key value for agent global config items */
export const CONFIG = "CONFIG" as const;

/** Build a partition key for a subject (repository) */
export function subjectPk(repo: string): string {
  return `${PREFIXES.SUBJECT}${repo}`;
}

/** Build a sort key for an agent */
export function agentSk(name: string): string {
  return `${PREFIXES.AGENT}${name}`;
}
