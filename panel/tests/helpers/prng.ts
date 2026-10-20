/**
 * Seeded PRNG for reproducible randomized tests (test plan §6 seed policy).
 * Replay a failure with `TEST_SEED=<seed> pnpm --filter panel exec vitest run <file> -t "<RT-id>"`.
 */

export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** The seed for a tactic: `TEST_SEED` when set, else the tactic's fixed default. */
export function testSeed(defaultSeed: number): number {
  const fromEnv = Number(process.env.TEST_SEED);
  return Number.isFinite(fromEnv) && process.env.TEST_SEED !== undefined ? fromEnv : defaultSeed;
}
