/**
 * Orchestrator Lambda handler.
 * Reads scope from DynamoDB, merges params, invokes agents with bounded concurrency.
 */

import { DynamoDBClient } from "@aws-sdk/client-dynamodb";
import { DynamoDBDocumentClient } from "@aws-sdk/lib-dynamodb";
import { buildSessionId } from "@fleet/shared";
import type { OrchestratorEvent, InvocationPayload, InvocationResult } from "./types.js";
import { queryEnabledSubjects, getAgentConfig } from "./scope-reader.js";
import { mergeParams } from "./params-merge.js";
import { stampAndInvoke, type InvokerDeps } from "./invoker.js";
import { pool, ORCHESTRATOR_CONCURRENCY } from "./pool.js";
import * as logger from "./logger.js";

// SDK clients (cold-start reuse)
const ddbClient = new DynamoDBClient({});
const docClient = DynamoDBDocumentClient.from(ddbClient);

// Agent runtime ARN from environment
const AGENT_RUNTIME_ARN = process.env["AGENT_RUNTIME_ARN"] ?? "";

/**
 * Invoke AgentCore runtime (fire-and-forget).
 * Uses HTTP-based invocation to call InvokeAgentRuntime.
 * The response body is intentionally NOT consumed.
 *
 * Note: In production, this calls the AgentCore InvokeAgentRuntime API.
 * The actual client may be replaced with a proper SDK client when
 * @aws-sdk/client-bedrock-agentcore is published.
 */
async function invokeAgentRuntime(payload: InvocationPayload): Promise<void> {
  // Use Lambda invoke as proxy for AgentCore runtime invocation
  // InvocationType "Event" = fire-and-forget (async)
  const { LambdaClient, InvokeCommand } = await import("@aws-sdk/client-lambda");
  const client = new LambdaClient({});
  const command = new InvokeCommand({
    FunctionName: AGENT_RUNTIME_ARN,
    InvocationType: "Event",
    Payload: new TextEncoder().encode(JSON.stringify(payload)),
  });
  await client.send(command);
}

export async function handler(event: OrchestratorEvent): Promise<void> {
  const { agent, scheduledAt } = event;
  const scheduledDate = new Date(scheduledAt);

  logger.setLogContext({ agent, function: "orchestrator" });
  logger.info("Orchestration started", { scheduledAt });

  // 1. Query enabled repos for this agent
  const subjects = await queryEnabledSubjects(docClient, agent);

  if (subjects.length === 0) {
    logger.info("No enabled repos found — nothing to invoke", { agent });
    logger.summary(0, 0, 0);
    return;
  }

  // 2. Get global config for params defaults
  const config = await getAgentConfig(docClient, agent);
  const globalDefaults = config?.defaultParams ?? {};

  // 3. Build invocation payloads
  const payloads: InvocationPayload[] = subjects.map((entry) => ({
    session_id: buildSessionId(agent, entry.subjectId, scheduledDate),
    repo: entry.subjectId,
    params: mergeParams(globalDefaults, entry.params),
  }));

  // 4. Stamp-then-invoke with bounded concurrency
  const deps: InvokerDeps = {
    dynamoClient: docClient,
    invokeAgent: invokeAgentRuntime,
    agentName: agent,
  };

  const results: InvocationResult[] = await pool(
    payloads,
    (payload) => stampAndInvoke(deps, payload),
    ORCHESTRATOR_CONCURRENCY,
  );

  // 5. Log summary
  const invoked = results.filter((r) => r.status === "invoked").length;
  const failed = results.filter((r) => r.status === "failed").length;

  for (const result of results) {
    if (result.status === "failed") {
      logger.error("Invocation failed", {
        session_id: result.sessionId,
        repo: result.repo,
        error: result.error,
      });
    } else {
      logger.info("Invocation succeeded", {
        session_id: result.sessionId,
        repo: result.repo,
      });
    }
  }

  logger.summary(invoked, 0, failed);
}
