#!/usr/bin/env tsx
/**
 * Seed script for the agent-fleet-config DynamoDB table.
 *
 * Reads repos.json, normalizes inputs, and writes META + AGENT items
 * using TransactWriteItems with attribute_not_exists for idempotency.
 *
 * Usage: pnpm --filter @fleet/infra run seed
 */

import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { DynamoDBClient } from "@aws-sdk/client-dynamodb";
import { DynamoDBDocumentClient, TransactWriteCommand } from "@aws-sdk/lib-dynamodb";
import { TABLE_NAME } from "@fleet/shared";
import { parseSeedInput, buildSeedItems, groupIntoTransactions } from "./seed-logic.js";
import type { SeedItem } from "./seed-logic.js";

const __dirname = dirname(fileURLToPath(import.meta.url));

async function main(): Promise<void> {
  // Read repos.json
  const reposPath = resolve(__dirname, "repos.json");
  const rawInput = JSON.parse(readFileSync(reposPath, "utf-8")) as unknown;

  // Parse and normalize
  const repos = parseSeedInput(rawInput);
  console.log(`Parsed ${repos.length} repositories from repos.json`);

  // Build items
  const items = buildSeedItems(repos, "dep-updater");
  const transactions = groupIntoTransactions(items);

  // Connect to DynamoDB
  const client = new DynamoDBClient({});
  const docClient = DynamoDBDocumentClient.from(client);

  let writtenCount = 0;
  let skippedCount = 0;

  for (const [metaItem, agentItem] of transactions) {
    try {
      await docClient.send(
        new TransactWriteCommand({
          TransactItems: [buildPutItem(metaItem), buildPutItem(agentItem)],
        }),
      );
      writtenCount++;
      console.log(`  ✓ Seeded: ${metaItem.subject_id as string}`);
    } catch (error: unknown) {
      if (isConditionalCheckFailed(error)) {
        skippedCount++;
        console.log(`  → Skipped (already exists): ${metaItem.subject_id as string}`);
      } else {
        throw error;
      }
    }
  }

  console.log(
    `\nSeed complete: ${writtenCount} written, ${skippedCount} skipped (already existed)`,
  );
}

function buildPutItem(item: SeedItem) {
  return {
    Put: {
      TableName: TABLE_NAME,
      Item: item,
      ConditionExpression: "attribute_not_exists(pk)",
    },
  };
}

function isConditionalCheckFailed(error: unknown): boolean {
  if (error && typeof error === "object" && "name" in error) {
    const name = (error as { name: string }).name;
    return name === "TransactionCanceledException" || name === "ConditionalCheckFailedException";
  }
  return false;
}

main().catch((err: unknown) => {
  console.error("Seed failed:", err);
  process.exit(1);
});
