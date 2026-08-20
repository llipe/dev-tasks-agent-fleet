/**
 * Agent discovery tags.
 *
 * These tags are applied to agent runtime resources via CDK and are used
 * by the control plane to discover managed agents via `tag:GetResources`.
 *
 * - `agent:managed=true` is the primary discovery filter.
 * - `agent:name` is a join key that MUST match the `AGENT#<name>` sort key in DynamoDB.
 * - `agent:domain` classifies the agent for UI grouping.
 */

import { PREFIXES } from "./keys.js";

export interface AgentTagSet {
  /** Discovery filter — only `"true"` enables the agent in the control plane */
  readonly "agent:managed": string;
  /** Agent name — MUST equal the value after `AGENT#` prefix in DynamoDB */
  readonly "agent:name": string;
  /** Domain classification for UI grouping */
  readonly "agent:domain": string;
}

/**
 * Discovery tags for the dep-updater agent.
 * The `agent:name` value is derived from the AGENT# prefix constant
 * to ensure consistency with the DynamoDB key structure.
 */
export const DEP_UPDATER_TAGS: AgentTagSet = {
  "agent:managed": "true",
  "agent:name": "dep-updater",
  "agent:domain": "security",
} as const;

/**
 * Validates that an `agent:name` tag value is consistent with
 * the AGENT# prefix key pattern used in DynamoDB.
 *
 * @param tagValue - The value of the `agent:name` tag
 * @returns The expected DynamoDB sort key (e.g., `AGENT#dep-updater`)
 */
export function agentNameToSortKey(tagValue: string): string {
  return `${PREFIXES.AGENT}${tagValue}`;
}

/**
 * Extracts the agent name from a DynamoDB AGENT# sort key.
 *
 * @param sortKey - The DynamoDB sort key (e.g., `AGENT#dep-updater`)
 * @returns The agent name (e.g., `dep-updater`), or null if not an AGENT# key
 */
export function sortKeyToAgentName(sortKey: string): string | null {
  if (!sortKey.startsWith(PREFIXES.AGENT)) return null;
  return sortKey.slice(PREFIXES.AGENT.length);
}
