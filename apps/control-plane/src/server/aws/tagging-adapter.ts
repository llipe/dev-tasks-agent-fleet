/**
 * Resource Groups Tagging API adapter.
 *
 * Discovers agent runtimes via the `agent:managed=true` tag filter.
 * Returns domain types — no AWS SDK types escape this module.
 */

import {
  ResourceGroupsTaggingAPIClient,
  GetResourcesCommand,
  type ResourceTagMapping,
} from "@aws-sdk/client-resource-groups-tagging-api";
import { credentialsProvider, awsRegion } from "./credentials.js";
import { withRetry } from "../retry.js";
import { TtlCache } from "../cache/ttl-cache.js";

/** Domain type representing a discovered agent */
export interface DiscoveredAgent {
  name: string;
  domain: string;
  arn: string;
}

const CACHE_KEY = "agent-inventory";

let client: ResourceGroupsTaggingAPIClient | undefined;

function getClient(): ResourceGroupsTaggingAPIClient {
  if (!client) {
    client = new ResourceGroupsTaggingAPIClient({
      region: awsRegion,
      credentials: credentialsProvider,
    });
  }
  return client;
}

/** Shared cache instance for tagging adapter (agents rarely change) */
const inventoryCache = new TtlCache<string, DiscoveredAgent[]>();

function extractAgentFromTags(resource: ResourceTagMapping): DiscoveredAgent | null {
  const arn = resource.ResourceARN;
  if (!arn) return null;

  const tags = resource.Tags ?? [];
  const tagMap = new Map(tags.map((t) => [t.Key, t.Value]));

  const name = tagMap.get("agent:name");
  const domain = tagMap.get("agent:domain") ?? "unknown";

  if (!name) return null;

  return { name, domain, arn };
}

/**
 * List all agents tagged with `agent:managed=true`.
 * Results are cached for 5 minutes (agents rarely change).
 */
export async function listManagedAgents(): Promise<DiscoveredAgent[]> {
  return inventoryCache.get(CACHE_KEY, async () => {
    return withRetry(async () => {
      const agents: DiscoveredAgent[] = [];
      let paginationToken: string | undefined;

      do {
        const command = new GetResourcesCommand({
          TagFilters: [{ Key: "agent:managed", Values: ["true"] }],
          PaginationToken: paginationToken,
        });

        const response = await getClient().send(command);
        const mappings = response.ResourceTagMappingList ?? [];

        for (const mapping of mappings) {
          const agent = extractAgentFromTags(mapping);
          if (agent) {
            agents.push(agent);
          }
        }

        paginationToken = response.PaginationToken;
      } while (paginationToken);

      return agents;
    });
  });
}

/** Clear the inventory cache (useful for testing) */
export function clearInventoryCache(): void {
  inventoryCache.clear();
}

/** Replace the client for testing */
export function _setClient(c: ResourceGroupsTaggingAPIClient): void {
  client = c;
}
