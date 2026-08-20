/**
 * Run query service — orchestrates: build query → execute → map → cache.
 *
 * Provides the public API for querying runs from spans:
 * - queryRuns(): run list with caching and single-flight
 * - querySessionTrace(): trace timeline (delegated to trace-query.ts)
 *
 * Cache key: serialized filter shape (JSON of { agentName?, from, to, limit })
 * TTL: 5 minutes
 * Single-flight: concurrent identical queries share one in-flight request via TtlCache
 */

import { TtlCache } from "../cache/ttl-cache.js";
import type { ReadOutcome } from "../repository/types.js";
import { buildRunListQueryParams, type RunListQueryInput } from "./query-builder.js";
import { executeRunQuery } from "./query-executor.js";
import { mapRowsToRuns, type Run } from "./span-to-run-mapper.js";

/** Cache TTL: 5 minutes */
const CACHE_TTL_MS = 5 * 60 * 1000;

/** Shared cache instance for run list queries */
const runListCache = new TtlCache<string, ReadOutcome<Run[]>>({
  ttlMs: CACHE_TTL_MS,
  maxEntries: 100,
});

/**
 * Build a deterministic cache key from the filter shape.
 */
function buildCacheKey(input: RunListQueryInput): string {
  return JSON.stringify({
    agentName: input.agentName ?? null,
    from: input.from.toISOString(),
    to: input.to.toISOString(),
    limit: input.limit ?? null,
  });
}

/**
 * Query runs from Logs Insights with caching and single-flight de-duplication.
 *
 * Flow: check cache → build query → execute → map → store in cache → return
 */
export async function queryRuns(input: RunListQueryInput): Promise<ReadOutcome<Run[]>> {
  const cacheKey = buildCacheKey(input);

  return runListCache
    .get(cacheKey, async () => {
      const params = buildRunListQueryParams(input);
      const outcome = await executeRunQuery(params);

      if (outcome.status !== "ok") {
        // Don't cache errors/timeouts/empty — let them retry
        // But we need to throw to prevent caching (TtlCache only caches resolved values)
        throw new CacheBypassError(outcome);
      }

      const runs = mapRowsToRuns(outcome.data.rows);

      if (runs.length === 0) {
        return { status: "empty", correlationId: outcome.correlationId } as ReadOutcome<Run[]>;
      }

      return { status: "ok", data: runs, correlationId: outcome.correlationId };
    })
    .catch((error: unknown) => {
      if (error instanceof CacheBypassError) {
        return error.outcome as ReadOutcome<Run[]>;
      }
      throw error;
    });
}

/**
 * Clear the run list cache (useful for testing or forced refresh).
 */
export function clearRunListCache(): void {
  runListCache.clear();
}

/** @internal Exposed for testing */
export function _getRunListCache(): TtlCache<string, ReadOutcome<Run[]>> {
  return runListCache;
}

/**
 * Sentinel error used to bypass cache storage for non-ok outcomes.
 * TtlCache only stores resolved values; by throwing, we prevent
 * errors/timeouts from being cached while still returning them to the caller.
 */
class CacheBypassError extends Error {
  constructor(public readonly outcome: ReadOutcome<unknown>) {
    super("cache-bypass");
  }
}
