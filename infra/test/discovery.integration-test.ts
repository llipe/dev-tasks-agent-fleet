/**
 * Integration tests for agent discovery via resource tags.
 *
 * These tests verify that:
 * - `tag:GetResources` filtered on `agent:managed=true` returns the agent stack
 * - An untagged control resource is absent from the results
 * - `agent:name` tag value is consistent with the `AGENT#<name>` DynamoDB sort key
 *
 * Prerequisites:
 * - AWS credentials available
 * - The AgentStack is deployed with discovery tags
 * - At least one untagged resource exists (e.g., DataStack or IamStack)
 *
 * Run with: pnpm --filter infra run test:integration -- discovery
 */

import { describe, it, expect, beforeAll } from "vitest";
import {
  ResourceGroupsTaggingAPIClient,
  GetResourcesCommand,
} from "@aws-sdk/client-resource-groups-tagging-api";
import { DEP_UPDATER_TAGS, agentNameToSortKey, PREFIXES } from "@fleet/shared";

const REGION = process.env["AWS_REGION"] ?? "us-east-1";
const ACCOUNT_ID = process.env["AWS_ACCOUNT_ID"] ?? "";

const taggingClient = new ResourceGroupsTaggingAPIClient({ region: REGION });

describe("Agent discovery via tags — integration", () => {
  beforeAll(() => {
    if (!ACCOUNT_ID) {
      throw new Error(
        "AWS_ACCOUNT_ID env var required for integration tests. " +
          "Set AWS_ACCOUNT_ID and ensure AWS credentials are available.",
      );
    }
  });

  describe("tag:GetResources filtered on agent:managed=true (sub-task 5.6)", () => {
    it("returns at least one resource with agent:managed=true", async () => {
      const response = await taggingClient.send(
        new GetResourcesCommand({
          TagFilters: [
            {
              Key: "agent:managed",
              Values: ["true"],
            },
          ],
        }),
      );

      expect(response.ResourceTagMappingList).toBeDefined();
      const resources = response.ResourceTagMappingList ?? [];
      expect(resources.length).toBeGreaterThan(0);
    });

    it("returned resources have all three discovery tags", async () => {
      const response = await taggingClient.send(
        new GetResourcesCommand({
          TagFilters: [
            {
              Key: "agent:managed",
              Values: ["true"],
            },
          ],
        }),
      );

      const resources = response.ResourceTagMappingList ?? [];
      expect(resources.length).toBeGreaterThan(0);

      for (const resource of resources) {
        const tags = resource.Tags ?? [];
        const tagMap = Object.fromEntries(tags.map((t) => [t.Key, t.Value]));

        expect(tagMap["agent:managed"]).toBe("true");
        expect(tagMap["agent:name"]).toBeDefined();
        expect(tagMap["agent:domain"]).toBeDefined();
      }
    });

    it("returned agent has agent:name=dep-updater", async () => {
      const response = await taggingClient.send(
        new GetResourcesCommand({
          TagFilters: [
            {
              Key: "agent:managed",
              Values: ["true"],
            },
            {
              Key: "agent:name",
              Values: ["dep-updater"],
            },
          ],
        }),
      );

      const resources = response.ResourceTagMappingList ?? [];
      expect(resources.length).toBeGreaterThan(0);

      const firstResource = resources[0];
      expect(firstResource).toBeDefined();
      const tags = firstResource?.Tags ?? [];
      const tagMap = Object.fromEntries(tags.map((t) => [t.Key, t.Value]));
      expect(tagMap["agent:name"]).toBe("dep-updater");
    });
  });

  describe("untagged control resource is absent (sub-task 5.7)", () => {
    it("DynamoDB table (DataStack) does NOT appear in agent:managed results", async () => {
      const response = await taggingClient.send(
        new GetResourcesCommand({
          TagFilters: [
            {
              Key: "agent:managed",
              Values: ["true"],
            },
          ],
          ResourceTypeFilters: ["dynamodb:table"],
        }),
      );

      const resources = response.ResourceTagMappingList ?? [];
      // The agent-fleet-config table should NOT have agent:managed=true
      const tableArns = resources
        .map((r) => r.ResourceARN ?? "")
        .filter((arn) => arn.includes("agent-fleet-config"));

      expect(tableArns.length).toBe(0);
    });

    it("IAM roles (IamStack) do NOT appear in agent:managed results", async () => {
      const response = await taggingClient.send(
        new GetResourcesCommand({
          TagFilters: [
            {
              Key: "agent:managed",
              Values: ["true"],
            },
          ],
          ResourceTypeFilters: ["iam:role"],
        }),
      );

      const resources = response.ResourceTagMappingList ?? [];
      // The fleet IAM roles should NOT have agent:managed=true
      const roleArns = resources
        .map((r) => r.ResourceARN ?? "")
        .filter((arn) => arn.includes("agent-fleet-"));

      expect(roleArns.length).toBe(0);
    });
  });

  describe("consistency: agent:name equals AGENT#<name> key (sub-task 5.8)", () => {
    it("agent:name from tag results matches the AGENT# sort key pattern", async () => {
      const response = await taggingClient.send(
        new GetResourcesCommand({
          TagFilters: [
            {
              Key: "agent:managed",
              Values: ["true"],
            },
          ],
        }),
      );

      const resources = response.ResourceTagMappingList ?? [];
      expect(resources.length).toBeGreaterThan(0);

      for (const resource of resources) {
        const tags = resource.Tags ?? [];
        const tagMap = Object.fromEntries(tags.map((t) => [t.Key, t.Value]));
        const agentName = tagMap["agent:name"];

        if (agentName) {
          // The tag value must produce a valid AGENT# sort key
          const sortKey = agentNameToSortKey(agentName);
          expect(sortKey).toBe(`${PREFIXES.AGENT}${agentName}`);
          expect(sortKey.startsWith(PREFIXES.AGENT)).toBe(true);

          // For dep-updater specifically
          if (agentName === "dep-updater") {
            expect(sortKey).toBe("AGENT#dep-updater");
          }
        }
      }
    });

    it("DEP_UPDATER_TAGS agent:name matches expected AGENT# key exactly", () => {
      const tagName = DEP_UPDATER_TAGS["agent:name"];
      const sortKey = agentNameToSortKey(tagName);
      expect(sortKey).toBe("AGENT#dep-updater");
    });
  });
});
