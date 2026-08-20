/**
 * Bounded concurrency pool.
 * Processes items with a maximum number of concurrent executions.
 */

/** Default concurrency limit */
export const ORCHESTRATOR_CONCURRENCY = 4;

/**
 * Run tasks with bounded concurrency.
 * Each task is independent — one failure does not stop others.
 *
 * @param items - Items to process
 * @param fn - Async function to apply to each item
 * @param concurrency - Maximum concurrent executions (default: ORCHESTRATOR_CONCURRENCY)
 * @returns Array of results in the same order as items
 */
export async function pool<T, R>(
  items: T[],
  fn: (item: T) => Promise<R>,
  concurrency: number = ORCHESTRATOR_CONCURRENCY,
): Promise<R[]> {
  const results: R[] = new Array(items.length);
  let nextIndex = 0;

  async function worker(): Promise<void> {
    while (nextIndex < items.length) {
      const index = nextIndex++;
      const item = items[index];
      if (item === undefined) break;
      results[index] = await fn(item);
    }
  }

  const workers = Array.from({ length: Math.min(concurrency, items.length) }, () => worker());
  await Promise.all(workers);

  return results;
}
