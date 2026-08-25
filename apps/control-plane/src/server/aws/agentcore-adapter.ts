/**
 * AgentCore control adapter.
 *
 * Returns `lifecycleConfiguration.maxLifetime` for a given agent runtime.
 * Defaults to 28800 seconds when absent.
 *
 * TODO: Replace with actual `@aws-sdk/client-bedrock-agentcore` GetAgentRuntime
 * call once the SDK is published. For now, implements the interface and default behavior.
 */

import { TtlCache } from "../cache/ttl-cache.js";

/** Domain type for agent runtime lifecycle config */
export interface AgentLifecycle {
  /** Maximum lifetime in seconds (default: 28800 = 8 hours) */
  maxLifetime: number;
}

const DEFAULT_MAX_LIFETIME = 28800;

/** Cached agent lifecycle configs */
const lifecycleCache = new TtlCache<string, AgentLifecycle>();

/**
 * Get the lifecycle configuration for a given agent.
 *
 * Currently returns the default (28800s) since the AgentCore SDK
 * is not yet published. The important thing is the interface and default behavior.
 *
 * @param _agentName - Name of the agent (unused until SDK is available)
 */
export async function getAgentLifecycle(_agentName: string): Promise<AgentLifecycle> {
  return lifecycleCache.get(`lifecycle:${_agentName}`, async () => {
    // TODO: Once @aws-sdk/client-bedrock-agentcore is available:
    // const command = new GetAgentRuntimeCommand({ agentRuntimeId });
    // const response = await client.send(command);
    // const maxLifetime = response.lifecycleConfiguration?.maxLifetime ?? DEFAULT_MAX_LIFETIME;
    return { maxLifetime: DEFAULT_MAX_LIFETIME };
  });
}

/** Parse lifecycle from a hypothetical API response, applying default */
export function parseMaxLifetime(
  lifecycleConfig: { maxLifetime?: number } | undefined | null,
): number {
  return lifecycleConfig?.maxLifetime ?? DEFAULT_MAX_LIFETIME;
}

/** Clear cache (for testing) */
export function clearLifecycleCache(): void {
  lifecycleCache.clear();
}
