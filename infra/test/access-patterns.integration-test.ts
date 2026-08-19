/**
 * Integration tests for DynamoDB access patterns.
 *
 * These tests run against DynamoDB Local (http://localhost:8000).
 * Start DynamoDB Local before running:
 *   docker run -d --rm -p 8000:8000 amazon/dynamodb-local:latest
 *
 * Run with: pnpm --filter @fleet/infra run test:integration
 *
 * Tests verify:
 * - A1: repos for an agent (GSI1 pk=AGENT#name)
 * - A3: agents for a repo (base table pk=SUBJECT#repo, sk begins_with AGENT#)
 * - A4: all subjects via GSI1 (pk=META)
 * - Idempotent re-seed (sub-task 3.9)
 * - Transaction rollback when item exists (sub-task 3.10)
 * - AC verification: Query GSI1 pk="META" returns all subjects (3.11)
 * - AC verification: Query GSI1 pk="AGENT#dep-updater" filtered enabled=true (3.12)
 */

import { describe, it, expect, beforeAll, afterAll } from "vitest";
import {
  DynamoDBClient,
  CreateTableCommand,
  DeleteTableCommand,
  waitUntilTableExists,
} from "@aws-sdk/client-dynamodb";
import {
  DynamoDBDocumentClient,
  TransactWriteCommand,
  QueryCommand,
  PutCommand,
} from "@aws-sdk/lib-dynamodb";
import { TABLE_NAME, GSI1_NAME, subjectPk, agentSk, META, PREFIXES } from "@fleet/shared";
import { buildSeedItems, groupIntoTransactions } from "../seed/seed-logic.js";
import type { SeedItem } from "../seed/seed-logic.js";

const TEST_TABLE = `${TABLE_NAME}-integration-test`;
const ENDPOINT = process.env["AWS_ENDPOINT_URL"] ?? "http://localhost:8000";

let client: DynamoDBClient;
let docClient: DynamoDBDocumentClient;

function buildPutItem(item: SeedItem, tableName: string) {
  return {
    Put: {
      TableName: tableName,
      Item: item,
      ConditionExpression: "attribute_not_exists(pk)",
    },
  };
}

async function seedTable(repos: string[], agentName: string): Promise<number> {
  const items = buildSeedItems(repos, agentName);
  const transactions = groupIntoTransactions(items);
  let written = 0;

  for (const [metaItem, agentItem] of transactions) {
    try {
      await docClient.send(
        new TransactWriteCommand({
          TransactItems: [buildPutItem(metaItem, TEST_TABLE), buildPutItem(agentItem, TEST_TABLE)],
        }),
      );
      written++;
    } catch (error: unknown) {
      if (
        error &&
        typeof error === "object" &&
        "name" in error &&
        (error as { name: string }).name === "TransactionCanceledException"
      ) {
        // Item already exists — idempotent skip
      } else {
        throw error;
      }
    }
  }
  return written;
}

beforeAll(async () => {
  client = new DynamoDBClient({
    endpoint: ENDPOINT,
    region: "us-east-1",
    credentials: {
      accessKeyId: "test",
      secretAccessKey: "test",
    },
  });
  docClient = DynamoDBDocumentClient.from(client);

  // Create test table
  try {
    await client.send(
      new CreateTableCommand({
        TableName: TEST_TABLE,
        KeySchema: [
          { AttributeName: "pk", KeyType: "HASH" },
          { AttributeName: "sk", KeyType: "RANGE" },
        ],
        AttributeDefinitions: [
          { AttributeName: "pk", AttributeType: "S" },
          { AttributeName: "sk", AttributeType: "S" },
        ],
        GlobalSecondaryIndexes: [
          {
            IndexName: GSI1_NAME,
            KeySchema: [
              { AttributeName: "sk", KeyType: "HASH" },
              { AttributeName: "pk", KeyType: "RANGE" },
            ],
            Projection: { ProjectionType: "ALL" },
          },
        ],
        BillingMode: "PAY_PER_REQUEST",
      }),
    );
    await waitUntilTableExists({ client, maxWaitTime: 30 }, { TableName: TEST_TABLE });
  } catch (error: unknown) {
    if (
      error &&
      typeof error === "object" &&
      "name" in error &&
      (error as { name: string }).name === "ResourceInUseException"
    ) {
      // Table already exists
    } else {
      throw error;
    }
  }

  // Seed the table with test data
  await seedTable(["llipe/dev-tasks-agent-fleet", "llipe/llipe.github.io"], "dep-updater");
}, 30000);

afterAll(async () => {
  try {
    await client.send(new DeleteTableCommand({ TableName: TEST_TABLE }));
  } catch {
    // Ignore cleanup errors
  }
  client.destroy();
});

describe("Access Pattern A1: repos for agent (GSI1)", () => {
  it("Query GSI1 pk=AGENT#dep-updater returns all repos for that agent", async () => {
    const result = await docClient.send(
      new QueryCommand({
        TableName: TEST_TABLE,
        IndexName: GSI1_NAME,
        KeyConditionExpression: "sk = :sk",
        ExpressionAttributeValues: {
          ":sk": agentSk("dep-updater"),
        },
      }),
    );

    expect(result.Items).toBeDefined();
    const items = result.Items ?? [];
    expect(items.length).toBe(2);

    const pks = items.map((item) => item["pk"]);
    expect(pks).toContain(subjectPk("llipe/dev-tasks-agent-fleet"));
    expect(pks).toContain(subjectPk("llipe/llipe.github.io"));
  });
});

describe("Access Pattern A3: agents for repo (base table)", () => {
  it("Query base table pk=SUBJECT#repo, sk begins_with AGENT# returns agents", async () => {
    const result = await docClient.send(
      new QueryCommand({
        TableName: TEST_TABLE,
        KeyConditionExpression: "pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues: {
          ":pk": subjectPk("llipe/dev-tasks-agent-fleet"),
          ":prefix": PREFIXES.AGENT,
        },
      }),
    );

    expect(result.Items).toBeDefined();
    const items = result.Items ?? [];
    expect(items.length).toBe(1);
    expect(items[0]?.["sk"]).toBe(agentSk("dep-updater"));
    expect(items[0]?.["enabled"]).toBe(true);
  });
});

describe("Access Pattern A4: all subjects via GSI1 META", () => {
  it("Query GSI1 pk=META returns every seeded subject", async () => {
    const result = await docClient.send(
      new QueryCommand({
        TableName: TEST_TABLE,
        IndexName: GSI1_NAME,
        KeyConditionExpression: "sk = :sk",
        ExpressionAttributeValues: {
          ":sk": META,
        },
      }),
    );

    expect(result.Items).toBeDefined();
    const items = result.Items ?? [];
    expect(items.length).toBe(2);

    const subjectIds = items.map((item) => item["subject_id"]);
    expect(subjectIds).toContain("llipe/dev-tasks-agent-fleet");
    expect(subjectIds).toContain("llipe/llipe.github.io");
  });
});

describe("Idempotent re-seed (sub-task 3.9)", () => {
  it("second seed makes zero writes", async () => {
    const written = await seedTable(
      ["llipe/dev-tasks-agent-fleet", "llipe/llipe.github.io"],
      "dep-updater",
    );
    expect(written).toBe(0);
  });
});

describe("Transaction rollback when agent item exists (sub-task 3.10)", () => {
  it("fails the transaction when the agent item already exists for a new META", async () => {
    // Pre-insert just the agent item for a new repo
    await docClient.send(
      new PutCommand({
        TableName: TEST_TABLE,
        Item: {
          pk: subjectPk("test/rollback-repo"),
          sk: agentSk("dep-updater"),
          enabled: false,
          params: {},
        },
      }),
    );

    // Now try to seed the same repo — should fail because agent item exists
    const items = buildSeedItems(["test/rollback-repo"], "dep-updater");
    const transactions = groupIntoTransactions(items);

    let transactionCancelled = false;
    for (const [metaItem, agentItem] of transactions) {
      try {
        await docClient.send(
          new TransactWriteCommand({
            TransactItems: [
              buildPutItem(metaItem, TEST_TABLE),
              buildPutItem(agentItem, TEST_TABLE),
            ],
          }),
        );
      } catch (error: unknown) {
        if (
          error &&
          typeof error === "object" &&
          "name" in error &&
          (error as { name: string }).name === "TransactionCanceledException"
        ) {
          transactionCancelled = true;
        } else {
          throw error;
        }
      }
    }

    expect(transactionCancelled).toBe(true);

    // Verify the META item was NOT created (transaction rolled back)
    const result = await docClient.send(
      new QueryCommand({
        TableName: TEST_TABLE,
        KeyConditionExpression: "pk = :pk AND sk = :sk",
        ExpressionAttributeValues: {
          ":pk": subjectPk("test/rollback-repo"),
          ":sk": META,
        },
      }),
    );
    const items2 = result.Items ?? [];
    expect(items2.length).toBe(0);
  });
});

describe("AC Verification: GSI1 queries (sub-tasks 3.11, 3.12)", () => {
  it("Query GSI1 pk=META returns every seeded subject (AC 3.11)", async () => {
    const result = await docClient.send(
      new QueryCommand({
        TableName: TEST_TABLE,
        IndexName: GSI1_NAME,
        KeyConditionExpression: "sk = :sk",
        ExpressionAttributeValues: {
          ":sk": META,
        },
      }),
    );

    expect(result.Items).toBeDefined();
    const items = result.Items ?? [];
    // At least the 2 originally seeded subjects
    expect(items.length).toBeGreaterThanOrEqual(2);

    const subjectIds = items.map((item) => item["subject_id"]);
    expect(subjectIds).toContain("llipe/dev-tasks-agent-fleet");
    expect(subjectIds).toContain("llipe/llipe.github.io");
  });

  it("Query GSI1 pk=AGENT#dep-updater filtered enabled=true returns enabled subset (AC 3.12)", async () => {
    const result = await docClient.send(
      new QueryCommand({
        TableName: TEST_TABLE,
        IndexName: GSI1_NAME,
        KeyConditionExpression: "sk = :sk",
        FilterExpression: "enabled = :enabled",
        ExpressionAttributeValues: {
          ":sk": agentSk("dep-updater"),
          ":enabled": true,
        },
      }),
    );

    expect(result.Items).toBeDefined();
    const items = result.Items ?? [];
    // Only enabled items returned
    for (const item of items) {
      expect(item["enabled"]).toBe(true);
    }
    // The 2 originally seeded repos are enabled
    expect(items.length).toBeGreaterThanOrEqual(2);
  });

  it("disabled items are excluded from the enabled filter", async () => {
    // The rollback-repo agent item has enabled=false
    const result = await docClient.send(
      new QueryCommand({
        TableName: TEST_TABLE,
        IndexName: GSI1_NAME,
        KeyConditionExpression: "sk = :sk",
        FilterExpression: "enabled = :enabled",
        ExpressionAttributeValues: {
          ":sk": agentSk("dep-updater"),
          ":enabled": true,
        },
      }),
    );

    const items = result.Items ?? [];
    const pks = items.map((item) => item["pk"]);
    // test/rollback-repo should NOT be in the enabled results
    expect(pks).not.toContain(subjectPk("test/rollback-repo"));
  });
});
