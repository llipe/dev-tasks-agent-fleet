/**
 * Integration tests for agent DynamoDB outcome stamping (S-011).
 *
 * These tests assume the IAM roles and DynamoDB table are deployed.
 * They verify that the agent-exec-role can write last_status and last_outcome_url
 * without changing enabled or params, and that writes to enabled are denied.
 *
 * Prerequisites:
 * - AWS credentials available that can assume the agent-exec-role
 * - The DynamoDB table `agent-fleet-config` exists
 * - The IAM roles are deployed
 *
 * Run with: pnpm --filter infra run test:integration -- agent-writes
 */

import { describe, it, expect, beforeAll } from "vitest";
import { STSClient, AssumeRoleCommand } from "@aws-sdk/client-sts";
import {
  DynamoDBClient,
  PutItemCommand,
  UpdateItemCommand,
  GetItemCommand,
} from "@aws-sdk/client-dynamodb";
import { TABLE_NAME, subjectPk, agentSk } from "@fleet/shared";

const REGION = process.env["AWS_REGION"] ?? "us-east-1";
const ACCOUNT_ID = process.env["AWS_ACCOUNT_ID"] ?? "";

const TEST_REPO = "test-org/agent-writes-test-repo";
const TEST_AGENT = "dep-updater";
const TEST_PK = subjectPk(TEST_REPO);
const TEST_SK = agentSk(TEST_AGENT);

// The test item's fixed values that MUST NOT change
const FIXED_ENABLED = true;
const FIXED_PARAMS = { allow_fixes: { BOOL: true }, max_fix_attempts: { N: "3" } };

const AGENT_EXEC_ROLE_ARN = `arn:aws:iam::${ACCOUNT_ID}:role/agent-fleet-agent-exec-role`;

const stsClient = new STSClient({ region: REGION });

async function assumeAgentRole(): Promise<DynamoDBClient> {
  const response = await stsClient.send(
    new AssumeRoleCommand({
      RoleArn: AGENT_EXEC_ROLE_ARN,
      RoleSessionName: "agent-writes-integration-test",
      DurationSeconds: 900,
    }),
  );

  const credentials = response.Credentials;
  if (!credentials?.AccessKeyId || !credentials.SecretAccessKey) {
    throw new Error(`Failed to assume role: ${AGENT_EXEC_ROLE_ARN}`);
  }

  return new DynamoDBClient({
    region: REGION,
    credentials: {
      accessKeyId: credentials.AccessKeyId,
      secretAccessKey: credentials.SecretAccessKey,
      sessionToken: credentials.SessionToken,
    },
  });
}

async function ensureTestItem(): Promise<void> {
  // Use default credentials to set up/reset the test item
  const client = new DynamoDBClient({ region: REGION });

  // Delete and recreate to ensure known state
  await client.send(
    new PutItemCommand({
      TableName: TABLE_NAME,
      Item: {
        pk: { S: TEST_PK },
        sk: { S: TEST_SK },
        enabled: { BOOL: FIXED_ENABLED },
        params: { M: FIXED_PARAMS },
        last_status: { S: "running" },
        last_outcome_url: { S: "" },
        last_session_id: { S: "session-before-test" },
        last_run_at: { S: "2024-01-01T00:00:00Z" },
      },
    }),
  );
}

async function getItem(): Promise<Record<string, Record<string, unknown>>> {
  const client = new DynamoDBClient({ region: REGION });
  const result = await client.send(
    new GetItemCommand({
      TableName: TABLE_NAME,
      Key: {
        pk: { S: TEST_PK },
        sk: { S: TEST_SK },
      },
    }),
  );
  return result.Item ?? {};
}

describe("Agent DynamoDB outcome stamping — integration (S-011)", () => {
  beforeAll(async () => {
    if (!ACCOUNT_ID) {
      throw new Error("AWS_ACCOUNT_ID env var required for integration tests");
    }
    await ensureTestItem();
  });

  describe("11.8: Real write under agent-exec-role; enabled and params unchanged", () => {
    it("updates last_status and last_outcome_url successfully", async () => {
      const client = await assumeAgentRole();

      const result = await client.send(
        new UpdateItemCommand({
          TableName: TABLE_NAME,
          Key: {
            pk: { S: TEST_PK },
            sk: { S: TEST_SK },
          },
          UpdateExpression: "SET last_status = :status, last_outcome_url = :url",
          ExpressionAttributeValues: {
            ":status": { S: "success" },
            ":url": { S: "https://github.com/test-org/agent-writes-test-repo/pull/42" },
          },
          ConditionExpression: "attribute_exists(pk)",
          ReturnValues: "ALL_NEW",
        }),
      );

      expect(result.Attributes).toBeDefined();
      const attrs = result.Attributes ?? {};

      // Written attributes updated correctly
      expect(attrs["last_status"]?.S).toBe("success");
      expect(attrs["last_outcome_url"]?.S).toBe(
        "https://github.com/test-org/agent-writes-test-repo/pull/42",
      );

      // Orchestrator-owned attributes NOT changed
      expect(attrs["enabled"]?.BOOL).toBe(FIXED_ENABLED);
      expect(attrs["params"]?.M).toEqual(FIXED_PARAMS);
      expect(attrs["last_session_id"]?.S).toBe("session-before-test");
      expect(attrs["last_run_at"]?.S).toBe("2024-01-01T00:00:00Z");
    });

    it("second write (failed status) still leaves enabled and params unchanged", async () => {
      const client = await assumeAgentRole();

      await client.send(
        new UpdateItemCommand({
          TableName: TABLE_NAME,
          Key: {
            pk: { S: TEST_PK },
            sk: { S: TEST_SK },
          },
          UpdateExpression: "SET last_status = :status, last_outcome_url = :url",
          ExpressionAttributeValues: {
            ":status": { S: "failed" },
            ":url": { S: "" },
          },
          ConditionExpression: "attribute_exists(pk)",
        }),
      );

      // Verify using admin credentials
      const item = await getItem();
      expect(item["last_status"]?.S).toBe("failed");
      expect(item["last_outcome_url"]?.S).toBe("");

      // MUST NOT be changed by agent writes
      expect(item["enabled"]?.BOOL).toBe(FIXED_ENABLED);
      expect(item["params"]?.M).toEqual(FIXED_PARAMS);
    });
  });

  describe("11.9: Attempted write to enabled is denied", () => {
    it("UpdateItem touching enabled attribute is denied by IAM", async () => {
      const client = await assumeAgentRole();

      await expect(
        client.send(
          new UpdateItemCommand({
            TableName: TABLE_NAME,
            Key: {
              pk: { S: TEST_PK },
              sk: { S: TEST_SK },
            },
            UpdateExpression: "SET enabled = :val",
            ExpressionAttributeValues: {
              ":val": { BOOL: false },
            },
          }),
        ),
      ).rejects.toThrow(/AccessDenied|not authorized/i);

      // Verify enabled was NOT changed
      const item = await getItem();
      expect(item["enabled"]?.BOOL).toBe(FIXED_ENABLED);
    });

    it("UpdateItem combining last_status with enabled is denied", async () => {
      const client = await assumeAgentRole();

      // Attempting to sneak enabled update alongside a legitimate one
      await expect(
        client.send(
          new UpdateItemCommand({
            TableName: TABLE_NAME,
            Key: {
              pk: { S: TEST_PK },
              sk: { S: TEST_SK },
            },
            UpdateExpression: "SET last_status = :status, enabled = :enabled",
            ExpressionAttributeValues: {
              ":status": { S: "success" },
              ":enabled": { BOOL: false },
            },
          }),
        ),
      ).rejects.toThrow(/AccessDenied|not authorized/i);
    });

    it("UpdateItem touching params attribute is denied", async () => {
      const client = await assumeAgentRole();

      await expect(
        client.send(
          new UpdateItemCommand({
            TableName: TABLE_NAME,
            Key: {
              pk: { S: TEST_PK },
              sk: { S: TEST_SK },
            },
            UpdateExpression: "SET params = :p",
            ExpressionAttributeValues: {
              ":p": { M: {} },
            },
          }),
        ),
      ).rejects.toThrow(/AccessDenied|not authorized/i);
    });
  });
});
