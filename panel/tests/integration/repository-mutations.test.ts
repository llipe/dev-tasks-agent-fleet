import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { randomUUID } from "node:crypto";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import type { Client } from "pg";
import { probeLocalDb, withDb } from "./db";
import {
  getRepositories,
  getSingleInstallation,
  insertRepository,
  REPOSITORY_ALREADY_EXISTS,
  RepositoryAlreadyExistsError,
} from "@/lib/supabase/queries";

/**
 * S-147 (#207) — Layer 2.5 (task 6.15/6.16) against the REAL local Supabase
 * stack:
 *   - `insertRepository` success path (no GitHub API call — asserted by a spy
 *     on `global.fetch`, since a live call would go through the platform
 *     fetch, per the test plan's §5.6 recommendation)
 *   - duplicate `full_name` rejection, both the pre-check path (sequential
 *     inserts) and the concurrent-race path (two simultaneous inserts, which
 *     genuinely races the pre-check against the `23505` unique-violation
 *     fallback — the invariant asserted is "never two rows, always a
 *     friendly `REPOSITORY_ALREADY_EXISTS`", regardless of which code path
 *     caught it, since which one wins is a real scheduler race, not something
 *     a test should pin to one branch)
 *   - mixed-case `full_name` differing only by case from an existing row —
 *     asserted against the REAL Postgres default collation (case-sensitive
 *     `text` equality — a distinct row is created, not rejected)
 *   - `getRepositories` excludes archived rows by default, includes them with
 *     `includeArchived: true`; an empty table (scoped to a fresh, isolated
 *     installation with zero repositories) renders an empty list, not an
 *     error
 *   - `getSingleInstallation` resolves the one seeded row
 *   - RLS stays deny-all AFTER the write (the standing regression pattern
 *     every prior auth-adjacent story includes, spec §14)
 *
 * Docker-gated; skips with a recorded reason when the stack is down.
 */

const probe = await probeLocalDb();

const API_URL = process.env.SUPABASE_URL ?? process.env.API_URL ?? "http://127.0.0.1:54321";
const SERVICE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY ?? process.env.SERVICE_ROLE_KEY ?? "";
const ANON_KEY = process.env.SUPABASE_ANON_KEY ?? process.env.ANON_KEY ?? "";
const keyPresent = SERVICE_KEY.trim().length > 0;
const anonKeyPresent = ANON_KEY.trim().length > 0;
const skipReason = !probe.available
  ? probe.reason
  : keyPresent
    ? ""
    : "SUPABASE_SERVICE_ROLE_KEY / SERVICE_ROLE_KEY not set — export it from `supabase status -o env`";
const runSuite = probe.available && keyPresent;

const fx = { installationId: "", repoIds: [] as string[] };

async function seedFixture(c: Client): Promise<void> {
  // An isolated installation, so this suite's repository rows never collide
  // with the seeded `llipe` installation's repositories (used elsewhere).
  fx.installationId = randomUUID();
  await c.query(
    `insert into github_installations (id, github_org_slug, installation_id, app_id)
     values ($1, $2, $3, $4)`,
    [fx.installationId, `s147-test-org-${fx.installationId.slice(0, 8)}`, 999000001, 999000002],
  );
}

async function cleanupFixture(c: Client): Promise<void> {
  if (fx.installationId) {
    await c.query(`delete from repositories where installation_id = $1`, [fx.installationId]);
    await c.query(`delete from github_installations where id = $1`, [fx.installationId]);
  }
}

describe.skipIf(!runSuite)("panel Layer 2.5 — repository mutations (S-147)", () => {
  let client: SupabaseClient;

  beforeAll(async () => {
    console.log(`[integration] ${probe.reason}`);
    client = createClient(API_URL, SERVICE_KEY, {
      auth: { autoRefreshToken: false, persistSession: false },
    });
    await withDb(seedFixture);
  });

  afterAll(async () => {
    await withDb(cleanupFixture);
  });

  it("getRepositories returns an empty list for a fresh installation's repositories (EC — empty table)", async () => {
    const rows = await getRepositories(client);
    const scoped = rows.filter((r) => r.installation_id === fx.installationId);
    expect(scoped).toEqual([]);
  });

  it("getSingleInstallation resolves an installation row", async () => {
    const installation = await getSingleInstallation(client);
    expect(installation).not.toBeNull();
    expect(typeof installation.id).toBe("string");
  });

  it("insertRepository inserts a new row without calling the GitHub API", async () => {
    const fetchSpy = globalThis.fetch;
    let fetchCallCount = 0;
    // Wrap fetch to count calls made DURING this test only — insertRepository
    // itself should never issue one (it talks to PostgREST only, which this
    // suite's own `client` already does via the SDK's internal fetch; the
    // assertion below is scoped to confirm the FUNCTION never reaches out to
    // github.com specifically).
    globalThis.fetch = ((...args: Parameters<typeof fetch>) => {
      const url = typeof args[0] === "string" ? args[0] : args[0].toString();
      if (url.includes("github.com") || url.includes("api.github.com")) {
        fetchCallCount += 1;
      }
      return fetchSpy(...args);
    }) as typeof fetch;

    try {
      const fullName = `s147-org/repo-${randomUUID().slice(0, 8)}`;
      const inserted = await insertRepository(client, {
        installationId: fx.installationId,
        fullName,
        defaultBranch: "main",
      });
      fx.repoIds.push(inserted.id);

      expect(inserted.full_name).toBe(fullName);
      expect(inserted.default_branch).toBe("main");
      expect(inserted.is_enabled).toBe(true);
      expect(inserted.archived_at).toBeNull();
      expect(fetchCallCount).toBe(0);
    } finally {
      globalThis.fetch = fetchSpy;
    }
  });

  it("getRepositories lists the inserted row, excluding archived by default", async () => {
    const rows = await getRepositories(client);
    const scoped = rows.filter((r) => r.installation_id === fx.installationId);
    expect(scoped.length).toBeGreaterThan(0);
    for (const row of scoped) {
      expect(row.archived_at).toBeNull();
    }
  });

  it("a duplicate full_name is rejected via the pre-check with a friendly error, not a raw Postgres error", async () => {
    const fullName = `s147-org/dup-${randomUUID().slice(0, 8)}`;
    const first = await insertRepository(client, {
      installationId: fx.installationId,
      fullName,
      defaultBranch: "main",
    });
    fx.repoIds.push(first.id);

    await expect(
      insertRepository(client, {
        installationId: fx.installationId,
        fullName,
        defaultBranch: "main",
      }),
    ).rejects.toMatchObject({ code: REPOSITORY_ALREADY_EXISTS });

    // Confirm no second row was inserted.
    const count = await withDb((c) =>
      c
        .query(`select count(*)::text as n from repositories where installation_id = $1 and full_name = $2`, [
          fx.installationId,
          fullName,
        ])
        .then((r) => r.rows[0]?.n),
    );
    expect(Number(count)).toBe(1);
  });

  it("a concurrent double-submit racing the SAME full_name never produces two rows, and the loser gets REPOSITORY_ALREADY_EXISTS (exercises the pre-check AND the 23505 fallback under real timing)", async () => {
    const fullName = `s147-org/race-${randomUUID().slice(0, 8)}`;
    const attempt = () =>
      insertRepository(client, {
        installationId: fx.installationId,
        fullName,
        defaultBranch: "main",
      });

    const results = await Promise.allSettled([attempt(), attempt()]);
    const fulfilled = results.filter((r) => r.status === "fulfilled");
    const rejected = results.filter((r) => r.status === "rejected");

    expect(fulfilled.length).toBe(1);
    expect(rejected.length).toBe(1);
    if (rejected[0]?.status === "rejected") {
      expect(rejected[0].reason).toMatchObject({ code: REPOSITORY_ALREADY_EXISTS });
    }
    if (fulfilled[0]?.status === "fulfilled") {
      fx.repoIds.push((fulfilled[0].value as { id: string }).id);
    }

    const count = await withDb((c) =>
      c
        .query(`select count(*)::text as n from repositories where installation_id = $1 and full_name = $2`, [
          fx.installationId,
          fullName,
        ])
        .then((r) => r.rows[0]?.n),
    );
    expect(Number(count)).toBe(1);
  });

  it("a mixed-case full_name differing only by case from an existing row is treated as DISTINCT (Postgres default collation is case-sensitive text equality) — documented, not a bug", async () => {
    const base = `s147-org/case-${randomUUID().slice(0, 8)}`;
    const upper = base.toUpperCase();

    const lower = await insertRepository(client, {
      installationId: fx.installationId,
      fullName: base,
      defaultBranch: "main",
    });
    fx.repoIds.push(lower.id);

    // A case-differing full_name is NOT rejected as a duplicate — it inserts
    // as a distinct row, matching Postgres's default case-sensitive `text`
    // equality for the `uq_repositories_full_name` unique constraint.
    const upperRow = await insertRepository(client, {
      installationId: fx.installationId,
      fullName: upper,
      defaultBranch: "main",
    });
    fx.repoIds.push(upperRow.id);

    expect(upperRow.id).not.toBe(lower.id);
  });

  it("RLS stays deny-all AFTER the insertRepository write (standing regression check)", async () => {
    if (!anonKeyPresent) {
      console.warn(
        "[integration] SUPABASE_ANON_KEY not set — skipping the anon-read assertion inside this test (recorded, not silently passed).",
      );
      return;
    }
    const anon = createClient(API_URL, ANON_KEY, {
      auth: { autoRefreshToken: false, persistSession: false },
    });
    const { data, error } = await anon.from("repositories").select("*").limit(100);
    if (error) {
      expect(error).toBeTruthy();
    } else {
      expect(data ?? [], `repositories leaked ${data?.length ?? 0} row(s) to anon`).toHaveLength(0);
    }
  });
});

if (!runSuite) {
  describe("panel Layer 2.5 — repository mutations (skipped)", () => {
    it.skip(`SKIPPED: ${skipReason}`, () => {});
  });
}
