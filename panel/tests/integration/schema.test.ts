import { beforeAll, describe, expect, it } from "vitest";
import { probeLocalDb, withDb } from "./db";

// Layer 2.5 harness proof (S-102 / issue #115 AC): confirms the Supabase CLI
// baseline migration produced a live schema on a REAL local Postgres — the
// `v_runs` view exists and `reap_stale_runs()` is callable. The data layer is
// never mocked here (TESTING.md Layer 2.5 boundary).
//
// Docker-gated: when the local stack is not running the whole suite is skipped
// with a recorded reason (printed to stdout so `SKIPPED(<reason>)` can be
// captured), rather than failing `make validate`.

const probe = await probeLocalDb();

describe.skipIf(!probe.available)("panel Layer 2.5 — baseline schema", () => {
  beforeAll(() => {
    // Surfaced in the test log as the positive counterpart to the skip reason.
    console.log(`[integration] ${probe.reason}`);
  });

  it("exposes the v_runs view", async () => {
    const rows = await withDb((c) =>
      c
        .query(
          `select 1 as ok
             from information_schema.views
            where table_schema = 'public'
              and table_name = 'v_runs'`,
        )
        .then((r) => r.rows),
    );
    expect(rows).toHaveLength(1);
  });

  it("has effective_status as a column on v_runs", async () => {
    // effective_status is the read-time contract the Phase 2 UI depends on
    // (FR11a). Assert the column is present on the view.
    const rows = await withDb((c) =>
      c
        .query(
          `select column_name
             from information_schema.columns
            where table_schema = 'public'
              and table_name = 'v_runs'
              and column_name = 'effective_status'`,
        )
        .then((r) => r.rows),
    );
    expect(rows).toHaveLength(1);
  });

  it("can call reap_stale_runs() and it returns an integer count", async () => {
    // On a freshly-reset DB with no stale runs this returns 0, but the point is
    // that the function exists, is callable, and returns the reaped-count int.
    const count = await withDb((c) =>
      c
        .query<{ reap_stale_runs: number }>(`select reap_stale_runs()`)
        .then((r) => r.rows[0]?.reap_stale_runs),
    );
    expect(typeof count).toBe("number");
    expect(count).toBeGreaterThanOrEqual(0);
  });
});

// When the stack is down, leave a visible breadcrumb so the skip is not silent.
if (!probe.available) {
  describe("panel Layer 2.5 — baseline schema (skipped)", () => {
    it.skip(`SKIPPED: ${probe.reason}`, () => {});
  });
}
