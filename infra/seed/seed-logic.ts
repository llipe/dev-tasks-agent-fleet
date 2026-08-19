/**
 * Seed logic — pure functions for parsing and building DynamoDB items.
 * Separated from the I/O layer for testability.
 */

import { normalizeSubjectId, subjectPk, agentSk, META } from "@fleet/shared";

/** Shape of the repos.json input file */
interface SeedInput {
  repositories?: string[];
}

/** A single DynamoDB item to write */
export interface SeedItem {
  pk: string;
  sk: string;
  [key: string]: unknown;
}

/**
 * Parse and validate the seed input, normalizing and deduplicating repos.
 * @returns Array of normalized repository identifiers
 */
export function parseSeedInput(input: unknown): string[] {
  const data = input as SeedInput;

  if (!data || !Array.isArray(data.repositories)) {
    throw new Error("Invalid seed input: missing or invalid 'repositories' array");
  }

  if (data.repositories.length === 0) {
    throw new Error("Invalid seed input: repositories array is empty");
  }

  const normalized = data.repositories.map((repo) => normalizeSubjectId(repo.trim()));

  // Deduplicate
  return [...new Set(normalized)];
}

/**
 * Build the DynamoDB items for seeding.
 * For each repo: one META item + one AGENT item.
 */
export function buildSeedItems(repos: string[], agentName: string): SeedItem[] {
  const now = new Date().toISOString();
  const items: SeedItem[] = [];

  for (const repo of repos) {
    // META item
    items.push({
      pk: subjectPk(repo),
      sk: META,
      subject_id: repo,
      created_at: now,
    });

    // AGENT item
    items.push({
      pk: subjectPk(repo),
      sk: agentSk(agentName),
      enabled: true,
      params: {},
    });
  }

  return items;
}

/**
 * Group items into transact-write batches.
 * Each batch writes one META + one AGENT item for a single repo (2 items per transaction).
 * DynamoDB TransactWriteItems supports up to 100 items, but we group by repo for atomicity.
 */
export function groupIntoTransactions(items: SeedItem[]): Array<[SeedItem, SeedItem]> {
  const transactions: Array<[SeedItem, SeedItem]> = [];
  for (let i = 0; i < items.length; i += 2) {
    const meta = items[i];
    const agent = items[i + 1];
    if (meta && agent) {
      transactions.push([meta, agent]);
    }
  }
  return transactions;
}
