/**
 * Stamp-then-invoke logic.
 * Per repo: UpdateItem lifecycle fields, then InvokeAgentRuntime fire-and-forget.
 */

import { type DynamoDBDocumentClient, UpdateCommand } from "@aws-sdk/lib-dynamodb";
import { TABLE_NAME, subjectPk, agentSk } from "@fleet/shared";
import type { InvocationPayload, InvocationResult } from "./types.js";

export interface InvokerDeps {
  dynamoClient: DynamoDBDocumentClient;
  invokeAgent: (payload: InvocationPayload) => Promise<void>;
  agentName: string;
}

/**
 * Stamp lifecycle fields in DynamoDB then invoke the agent.
 * Fire-and-forget: never reads the response body.
 * If invoke throws, immediately stamps last_status="failed".
 */
export async function stampAndInvoke(
  deps: InvokerDeps,
  payload: InvocationPayload,
): Promise<InvocationResult> {
  const { dynamoClient, invokeAgent, agentName } = deps;
  const { repo, session_id } = payload;

  // Stamp running state
  await dynamoClient.send(
    new UpdateCommand({
      TableName: TABLE_NAME,
      Key: {
        pk: subjectPk(repo),
        sk: agentSk(agentName),
      },
      UpdateExpression: "SET last_session_id = :sid, last_run_at = :rat, last_status = :status",
      ExpressionAttributeValues: {
        ":sid": session_id,
        ":rat": new Date().toISOString(),
        ":status": "running",
      },
    }),
  );

  try {
    // Fire-and-forget: invoke agent, never read body
    await invokeAgent(payload);
    return { repo, sessionId: session_id, status: "invoked" };
  } catch (error: unknown) {
    // Failure walk-back: immediately stamp failed
    await stampFailed(dynamoClient, agentName, repo);
    const message = error instanceof Error ? error.message : String(error);
    return { repo, sessionId: session_id, status: "failed", error: message };
  }
}

/**
 * Walk-back: stamp last_status="failed" when invoke throws.
 */
async function stampFailed(
  client: DynamoDBDocumentClient,
  agentName: string,
  repo: string,
): Promise<void> {
  try {
    await client.send(
      new UpdateCommand({
        TableName: TABLE_NAME,
        Key: {
          pk: subjectPk(repo),
          sk: agentSk(agentName),
        },
        UpdateExpression: "SET last_status = :status",
        ExpressionAttributeValues: {
          ":status": "failed",
        },
      }),
    );
  } catch {
    // Best-effort: log but don't throw
  }
}
