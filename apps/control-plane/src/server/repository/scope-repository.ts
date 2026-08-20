/**
 * Scope Repository — DynamoDB queries with intent-named methods.
 *
 * Hard invariant: NO `Scan` anywhere. All access patterns use Query or GetItem.
 * Uses key builders from @fleet/shared.
 */

import {
  QueryCommand,
  GetCommand,
  UpdateCommand,
  TransactWriteCommand,
} from "@aws-sdk/lib-dynamodb";
import { TABLE_NAME, GSI1_NAME, subjectPk, agentSk, META, PREFIXES } from "@fleet/shared";
import { getDocClient } from "../aws/dynamodb-client.js";
import { withRetry } from "../retry.js";
import type { ReadOutcome } from "./types.js";
import { makeCorrelationId } from "./types.js";

/** Domain type for a subject-agent association */
export interface SubjectAgent {
  subjectId: string;
  agentName: string;
  enabled: boolean;
  params: Record<string, unknown>;
  lastSessionId?: string;
  lastRunAt?: string;
  lastStatus?: string;
  lastOutcomeUrl?: string;
}

/** Domain type for a subject (repository) */
export interface Subject {
  subjectId: string;
  createdAt: string;
}

/**
 * List all subjects associated with a given agent.
 * Access pattern: GSI1 pk = "AGENT#<name>", filter on sk starts with "SUBJECT#"
 */
export async function listAgentSubjects(agentName: string): Promise<ReadOutcome<SubjectAgent[]>> {
  const correlationId = makeCorrelationId();

  try {
    const items: SubjectAgent[] = [];
    let exclusiveStartKey: Record<string, unknown> | undefined;

    do {
      const response = await withRetry(() =>
        getDocClient().send(
          new QueryCommand({
            TableName: TABLE_NAME,
            IndexName: GSI1_NAME,
            KeyConditionExpression: "sk = :sk",
            ExpressionAttributeValues: {
              ":sk": agentSk(agentName),
            },
            ExclusiveStartKey: exclusiveStartKey,
          }),
        ),
      );

      for (const item of response.Items ?? []) {
        const pk = item["pk"] as string;
        if (pk.startsWith(PREFIXES.SUBJECT)) {
          items.push(mapToSubjectAgent(item));
        }
      }

      exclusiveStartKey = response.LastEvaluatedKey;
    } while (exclusiveStartKey);

    if (items.length === 0) {
      return { status: "empty", correlationId };
    }
    return { status: "ok", data: items, correlationId };
  } catch (error: unknown) {
    return { status: "error", error: errorMessage(error), correlationId };
  }
}

/**
 * Get a specific subject-agent association.
 * Access pattern: GetItem pk = "SUBJECT#<subjectId>", sk = "AGENT#<agentName>"
 */
export async function getSubjectAgent(
  subjectId: string,
  agentName: string,
): Promise<ReadOutcome<SubjectAgent>> {
  const correlationId = makeCorrelationId();

  try {
    const response = await withRetry(() =>
      getDocClient().send(
        new GetCommand({
          TableName: TABLE_NAME,
          Key: {
            pk: subjectPk(subjectId),
            sk: agentSk(agentName),
          },
        }),
      ),
    );

    if (!response.Item) {
      return { status: "empty", correlationId };
    }

    return { status: "ok", data: mapToSubjectAgent(response.Item), correlationId };
  } catch (error: unknown) {
    return { status: "error", error: errorMessage(error), correlationId };
  }
}

/**
 * List all subjects (repositories) in the system.
 * Access pattern: GSI1 pk = "META" (inverted index: GSI1 pk=sk, sk=pk)
 */
export async function listSubjects(): Promise<ReadOutcome<Subject[]>> {
  const correlationId = makeCorrelationId();

  try {
    const items: Subject[] = [];
    let exclusiveStartKey: Record<string, unknown> | undefined;

    do {
      const response = await withRetry(() =>
        getDocClient().send(
          new QueryCommand({
            TableName: TABLE_NAME,
            IndexName: GSI1_NAME,
            KeyConditionExpression: "sk = :sk",
            ExpressionAttributeValues: {
              ":sk": META,
            },
            ExclusiveStartKey: exclusiveStartKey,
          }),
        ),
      );

      for (const item of response.Items ?? []) {
        items.push({
          subjectId: (item["subject_id"] as string) ?? extractSubjectId(item["pk"] as string),
          createdAt: (item["created_at"] as string) ?? "",
        });
      }

      exclusiveStartKey = response.LastEvaluatedKey;
    } while (exclusiveStartKey);

    if (items.length === 0) {
      return { status: "empty", correlationId };
    }
    return { status: "ok", data: items, correlationId };
  } catch (error: unknown) {
    return { status: "error", error: errorMessage(error), correlationId };
  }
}

/**
 * Set the enabled state of a subject-agent pair.
 * Access pattern: UpdateItem on pk/sk, only writing `enabled`.
 */
export async function setSubjectEnabled(
  subjectId: string,
  agentName: string,
  enabled: boolean,
): Promise<ReadOutcome<void>> {
  const correlationId = makeCorrelationId();

  try {
    await withRetry(() =>
      getDocClient().send(
        new UpdateCommand({
          TableName: TABLE_NAME,
          Key: {
            pk: subjectPk(subjectId),
            sk: agentSk(agentName),
          },
          UpdateExpression: "SET enabled = :enabled",
          ExpressionAttributeValues: {
            ":enabled": enabled,
          },
          ConditionExpression: "attribute_exists(pk)",
        }),
      ),
    );

    return { status: "ok", data: undefined, correlationId };
  } catch (error: unknown) {
    return { status: "error", error: errorMessage(error), correlationId };
  }
}

/**
 * Set params for a subject-agent pair.
 * Access pattern: UpdateItem on pk/sk, only writing `params`.
 */
export async function setSubjectParams(
  subjectId: string,
  agentName: string,
  params: Record<string, unknown>,
): Promise<ReadOutcome<void>> {
  const correlationId = makeCorrelationId();

  try {
    await withRetry(() =>
      getDocClient().send(
        new UpdateCommand({
          TableName: TABLE_NAME,
          Key: {
            pk: subjectPk(subjectId),
            sk: agentSk(agentName),
          },
          UpdateExpression: "SET params = :params",
          ExpressionAttributeValues: {
            ":params": params,
          },
          ConditionExpression: "attribute_exists(pk)",
        }),
      ),
    );

    return { status: "ok", data: undefined, correlationId };
  } catch (error: unknown) {
    return { status: "error", error: errorMessage(error), correlationId };
  }
}

/**
 * Add a new subject to an agent's scope.
 * Uses TransactWriteItems to atomically create both the META item and the AGENT# item.
 * Uses attribute_not_exists on the AGENT# item to prevent duplicates.
 */
export async function addSubject(
  subjectId: string,
  agentName: string,
  enabled: boolean,
): Promise<ReadOutcome<void>> {
  const correlationId = makeCorrelationId();
  const now = new Date().toISOString();

  try {
    await withRetry(() =>
      getDocClient().send(
        new TransactWriteCommand({
          TransactItems: [
            {
              Put: {
                TableName: TABLE_NAME,
                Item: {
                  pk: subjectPk(subjectId),
                  sk: META,
                  subject_id: subjectId,
                  created_at: now,
                },
                // Allow META to already exist (idempotent for the META item)
                ConditionExpression: "attribute_not_exists(pk) OR (pk = :pk AND sk = :sk)",
                ExpressionAttributeValues: {
                  ":pk": subjectPk(subjectId),
                  ":sk": META,
                },
              },
            },
            {
              Put: {
                TableName: TABLE_NAME,
                Item: {
                  pk: subjectPk(subjectId),
                  sk: agentSk(agentName),
                  enabled,
                  params: {},
                },
                // Prevent duplicate: fail if AGENT# item already exists
                ConditionExpression: "attribute_not_exists(pk)",
              },
            },
          ],
        }),
      ),
    );

    return { status: "ok", data: undefined, correlationId };
  } catch (error: unknown) {
    const msg = errorMessage(error);
    // TransactionCanceledException with ConditionalCheckFailed means conflict
    if (msg.includes("ConditionalCheckFailed") || msg.includes("TransactionCanceled")) {
      return {
        status: "error",
        error: "conflict: subject-agent pair already exists",
        correlationId,
      };
    }
    return { status: "error", error: msg, correlationId };
  }
}

// --- Helpers ---

function mapToSubjectAgent(item: Record<string, unknown>): SubjectAgent {
  const pk = item["pk"] as string;
  const sk = item["sk"] as string;

  return {
    subjectId: extractSubjectId(pk),
    agentName: extractAgentName(sk),
    enabled: (item["enabled"] as boolean) ?? false,
    params: (item["params"] as Record<string, unknown>) ?? {},
    lastSessionId: item["last_session_id"] as string | undefined,
    lastRunAt: item["last_run_at"] as string | undefined,
    lastStatus: item["last_status"] as string | undefined,
    lastOutcomeUrl: item["last_outcome_url"] as string | undefined,
  };
}

function extractSubjectId(pk: string): string {
  return pk.startsWith(PREFIXES.SUBJECT) ? pk.slice(PREFIXES.SUBJECT.length) : pk;
}

function extractAgentName(sk: string): string {
  return sk.startsWith(PREFIXES.AGENT) ? sk.slice(PREFIXES.AGENT.length) : sk;
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}
