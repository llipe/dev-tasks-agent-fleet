/**
 * DynamoDB GSI1 query to discover enabled repos for an agent.
 */

import { type DynamoDBDocumentClient, QueryCommand, GetCommand } from "@aws-sdk/lib-dynamodb";
import { GSI1_NAME, TABLE_NAME, PREFIXES } from "@fleet/shared";
import type { AgentConfig, ScopeEntry } from "./types.js";

/**
 * Query GSI1 for all subjects associated with an agent, filtering to enabled only.
 *
 * GSI1 key: pk = sk (from base table) = "AGENT#<name>"
 *           sk = pk (from base table) = "SUBJECT#<repo>"
 */
export async function queryEnabledSubjects(
  client: DynamoDBDocumentClient,
  agentName: string,
): Promise<ScopeEntry[]> {
  const entries: ScopeEntry[] = [];
  let exclusiveStartKey: Record<string, unknown> | undefined;

  do {
    const result = await client.send(
      new QueryCommand({
        TableName: TABLE_NAME,
        IndexName: GSI1_NAME,
        KeyConditionExpression: "sk = :sk",
        FilterExpression: "enabled = :enabled",
        ExpressionAttributeValues: {
          ":sk": `${PREFIXES.AGENT}${agentName}`,
          ":enabled": true,
        },
        ExclusiveStartKey: exclusiveStartKey,
      }),
    );

    for (const item of result.Items ?? []) {
      const pk = item["pk"] as string | undefined;
      if (!pk?.startsWith(PREFIXES.SUBJECT)) continue;

      const subjectId = pk.slice(PREFIXES.SUBJECT.length);
      entries.push({
        subjectId,
        enabled: (item["enabled"] as boolean) ?? false,
        params: (item["params"] as Record<string, unknown>) ?? {},
      });
    }

    exclusiveStartKey = result.LastEvaluatedKey as Record<string, unknown> | undefined;
  } while (exclusiveStartKey);

  return entries;
}

/**
 * Get the global agent config item (pk=CONFIG, sk=AGENT#<name> in base table,
 * which means in GSI1: pk=AGENT#<name>, sk=CONFIG).
 *
 * Actually the CONFIG item is: pk=CONFIG, sk=AGENT#<name> in the base table.
 * For a direct get, we query the base table with pk=CONFIG, sk=AGENT#<name>.
 */
export async function getAgentConfig(
  client: DynamoDBDocumentClient,
  agentName: string,
): Promise<AgentConfig | null> {
  const result = await client.send(
    new GetCommand({
      TableName: TABLE_NAME,
      Key: {
        pk: "CONFIG",
        sk: `${PREFIXES.AGENT}${agentName}`,
      },
    }),
  );

  if (!result.Item) return null;

  return {
    agentName: (result.Item["agent_name"] as string) ?? agentName,
    defaultParams: (result.Item["default_params"] as Record<string, unknown>) ?? {},
  };
}
