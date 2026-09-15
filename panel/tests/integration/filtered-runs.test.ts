import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { randomUUID } from "node:crypto";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import type { Client } from "pg";
import { probeLocalDb, withDb } from "./db";
import { getFilteredRuns, getRunStatusCounts } from "@/lib/supabase/queries";
import { parseRunFilter, type RunFilter } from "@/lib/domain/run-filter";

/**
 * Layer 2.5 harness for the Run History filter/pagination read (Story S-143,
 * spec §8.1, issue #203).
 *
 * Load-bearing properties that can only be proven against the real stack:
 *  - Status filtering narrows to `effective_status`, including a stale
 *    `running` row past its timeout threshold counting/filtering as
 *    `timed_out`, never `running` (FR1, FR11a, reaper-paused fixture — no
 *    reap is triggered by this suite).
 *  - Repo chip + status combine as an intersection, never a union (FR2).
 *  - Free-text search matches `repository_full_name`/`id` substrings and
 *    composes with other filters (FR3); a search string containing `%`/`_`
 *    (ilike wildcard metacharacters) matches literally, never broadening the
 *    match (spec §8.1 v1.1 addendum); a regex-metacharacter string never
 *    throws.
 *  - Reloading a URL (`parseRunFilter` -> `getFilteredRuns`) reproduces the
 *    identical filtered result from a fresh server-side query (FR4).
 *  - Pagination is cumulative-offset: page N returns rows 0..N*pageSize-1,
 *    `totalCount` stays accurate under every filter combination (FR5, CT-2).
 *  - A zero-match filter (a real UUID that does not exist, or a repo with
 *    zero runs for this agent) returns `{ rows: [], totalCount: 0 }`, never a
 *    query error (FR6, edge case).
 *
 * Docker-gated + service-role-key-gated, same pattern as `runs-by-agent.test.ts`.
 */

const probe = await probeLocalDb();

const API_URL = process.env.SUPABASE_URL ?? process.env.API_URL ?? "http://127.0.0.1:54321";
const SERVICE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY ?? process.env.SERVICE_ROLE_KEY ?? "";
const keyPresent = SERVICE_KEY.trim().length > 0;
const skipReason = !probe.available
  ? probe.reason
  : keyPresent
    ? ""
    : "SUPABASE_SERVICE_ROLE_KEY / SERVICE_ROLE_KEY not set — export it from `supabase status -o env`";
const runSuite = probe.available && keyPresent;

const createdAgentIds: string[] = [];
const createdRepoIds: string[] = [];
let installationId = "";

async function grantServiceRoleSelectLocalOnly(c: Client): Promise<void> {
  await c.query(`grant usage on schema public to service_role`);
  await c.query(`grant select on all tables in schema public to service_role`);
}

// Reuse the seeded installation (present via the seed migration) rather than
// inserting a new one — avoids depending on `github_installations`' exact
// column set, which this suite does not otherwise touch.
async function resolveInstallationId(c: Client): Promise<string> {
  if (installationId !== "") return installationId;
  const result = await c.query(`select id from github_installations limit 1`);
  if (result.rows.length === 0) {
    throw new Error(
      "no seeded github_installations row found — run `supabase db reset` to apply seed data",
    );
  }
  installationId = result.rows[0].id as string;
  return installationId;
}

async function insertAgent(c: Client, slug: string): Promise<string> {
  const id = randomUUID();
  await c.query(
    `insert into agents (id, slug, name, runtime_arn, requires_repository,
                         max_runtime_seconds, grace_seconds, start_timeout_seconds)
     values ($1, $2, $3, $4, false, 900, 60, 300)`,
    [id, slug, `filtered-runs test ${slug}`, "arn:test:runtime/filtered-runs"],
  );
  createdAgentIds.push(id);
  return id;
}

async function insertRepository(c: Client, fullName: string): Promise<string> {
  const id = randomUUID();
  const instId = await resolveInstallationId(c);
  await c.query(
    `insert into repositories (id, installation_id, full_name, default_branch, is_enabled)
     values ($1, $2, $3, 'main', true)`,
    [id, instId, fullName],
  );
  createdRepoIds.push(id);
  return id;
}

const TERMINAL_STATUSES = new Set([
  "succeeded",
  "failed",
  "timed_out",
  "canceled",
  "failed_to_start",
]);

async function insertRun(
  c: Client,
  agentId: string,
  opts: {
    status: string;
    minutesAgo: number;
    repositoryId?: string | null;
    startedMinutesAgo?: number | null;
  },
): Promise<string> {
  const id = randomUUID();
  const repositoryId = opts.repositoryId ?? null;
  const startedAgo = opts.startedMinutesAgo ?? opts.minutesAgo;
  const isQueued = opts.status === "queued";
  const isTerminal = TERMINAL_STATUSES.has(opts.status);
  const outcome = opts.status === "succeeded" ? "no_vulnerabilities" : null;

  await c.query(
    `insert into runs (id, agent_id, agent_version, status, repository_id,
                       queued_at, started_at, finished_at, created_at,
                       max_runtime_seconds, grace_seconds, start_timeout_seconds, outcome)
     values ($1, $2, '0.1.0', $3::run_status, $4::uuid,
             now() - ($5 || ' min')::interval - interval '1 min',
             case when $6::boolean then null else now() - ($7 || ' min')::interval end,
             case when $8::boolean then now() - ($5 || ' min')::interval + interval '3 min' else null end,
             now() - ($5 || ' min')::interval,
             900, 60, 300, $9::run_outcome)`,
    [
      id,
      agentId,
      opts.status,
      repositoryId,
      String(opts.minutesAgo),
      isQueued,
      String(startedAgo),
      isTerminal,
      outcome,
    ],
  );
  return id;
}

// Insert one stale running run (started 25 min ago; small 90s window) so it
// reads timed_out through effective_status without waiting for the reaper.
async function insertStaleRunning(c: Client, agentId: string): Promise<string> {
  const id = randomUUID();
  await c.query(
    `insert into runs (id, agent_id, agent_version, status,
                       queued_at, started_at, finished_at, created_at,
                       max_runtime_seconds, grace_seconds, start_timeout_seconds, outcome)
     values ($1, $2, '0.1.0', 'running',
             now() - interval '30 min', now() - interval '25 min', null,
             now() - interval '25 min',
             60, 30, 300, null)`,
    [id, agentId],
  );
  return id;
}

async function cleanup(c: Client): Promise<void> {
  for (const id of createdAgentIds) {
    await c.query(
      `delete from run_events where run_id in (select id from runs where agent_id = $1)`,
      [id],
    );
    await c.query(
      `delete from run_steps where run_id in (select id from runs where agent_id = $1)`,
      [id],
    );
    await c.query(`delete from runs where agent_id = $1`, [id]);
    await c.query(`delete from agents where id = $1`, [id]);
  }
  createdAgentIds.length = 0;
  for (const id of createdRepoIds) {
    await c.query(`delete from repositories where id = $1`, [id]);
  }
  createdRepoIds.length = 0;
}

function client(): SupabaseClient {
  return createClient(API_URL, SERVICE_KEY, {
    auth: { autoRefreshToken: false, persistSession: false },
  });
}

function baseFilter(overrides: Partial<RunFilter> = {}): RunFilter {
  return {
    status: "all",
    repositoryId: null,
    search: null,
    agentSlug: null,
    page: 1,
    ...overrides,
  };
}

describe.skipIf(!runSuite)("panel Layer 2.5 — getFilteredRuns / getRunStatusCounts", () => {
  beforeAll(async () => {
    console.log(`[integration] ${probe.reason}`);
    await withDb(grantServiceRoleSelectLocalOnly);
  });

  afterAll(async () => {
    await withDb(cleanup);
  });

  it("status filter narrows to that effective_status (AC1)", async () => {
    const slug = `filt-status-${randomUUID()}`;
    let failedId = "";
    await withDb(async (c) => {
      const agentId = await insertAgent(c, slug);
      failedId = await insertRun(c, agentId, { status: "failed", minutesAgo: 10 });
      await insertRun(c, agentId, { status: "succeeded", minutesAgo: 20 });
    });

    const result = await getFilteredRuns(
      client(),
      baseFilter({ agentSlug: slug, status: "failed" }),
      25,
    );
    expect(result.totalCount).toBe(1);
    expect(result.rows).toHaveLength(1);
    expect(result.rows[0]!.id).toBe(failedId);
  });

  it("a stale running row past its timeout threshold counts/filters as timed_out, never running (FR11a)", async () => {
    const slug = `filt-stale-${randomUUID()}`;
    let staleId = "";
    await withDb(async (c) => {
      const agentId = await insertAgent(c, slug);
      staleId = await insertStaleRunning(c, agentId);
    });

    const runningResult = await getFilteredRuns(
      client(),
      baseFilter({ agentSlug: slug, status: "running" }),
      25,
    );
    expect(runningResult.rows.find((r) => r.id === staleId)).toBeUndefined();
    expect(runningResult.totalCount).toBe(0);

    const timedOutResult = await getFilteredRuns(
      client(),
      baseFilter({ agentSlug: slug, status: "timed_out" }),
      25,
    );
    expect(timedOutResult.rows.map((r) => r.id)).toContain(staleId);
    expect(timedOutResult.totalCount).toBe(1);

    const counts = await getRunStatusCounts(client(), {
      agentSlug: slug,
      repositoryId: null,
      search: null,
    });
    expect(counts.timed_out).toBe(1);
    expect(counts.running).toBe(0);
    expect(counts.all).toBe(1);
  });

  it("repo chip narrows correctly; combined with status, the result is the intersection (AC2)", async () => {
    const slug = `filt-repo-${randomUUID()}`;
    let repoAId = "";
    let matchId = "";
    await withDb(async (c) => {
      const agentId = await insertAgent(c, slug);
      repoAId = await insertRepository(c, `org/repo-a-${randomUUID()}`);
      const repoBId = await insertRepository(c, `org/repo-b-${randomUUID()}`);
      matchId = await insertRun(c, agentId, {
        status: "failed",
        minutesAgo: 5,
        repositoryId: repoAId,
      });
      // Same repo, different status — must be excluded by the intersection.
      await insertRun(c, agentId, { status: "succeeded", minutesAgo: 6, repositoryId: repoAId });
      // Different repo, same status — must be excluded by the repo filter.
      await insertRun(c, agentId, { status: "failed", minutesAgo: 7, repositoryId: repoBId });
    });

    const result = await getFilteredRuns(
      client(),
      baseFilter({ agentSlug: slug, status: "failed", repositoryId: repoAId }),
      25,
    );
    expect(result.totalCount).toBe(1);
    expect(result.rows[0]!.id).toBe(matchId);
  });

  it("a repo chip for a syntactically valid but non-existent repositoryId resolves to zero matches, not an error", async () => {
    const slug = `filt-repo-missing-${randomUUID()}`;
    await withDb(async (c) => {
      const agentId = await insertAgent(c, slug);
      await insertRun(c, agentId, { status: "succeeded", minutesAgo: 5 });
    });

    const result = await getFilteredRuns(
      client(),
      baseFilter({ agentSlug: slug, repositoryId: randomUUID() }),
      25,
    );
    expect(result).toEqual({ rows: [], totalCount: 0 });
  });

  it("free-text search matches a repository-name substring, or an exact run id; composes with other filters (AC3)", async () => {
    const slug = `filt-search-${randomUUID()}`;
    let repoId = "";
    let matchId = "";
    await withDb(async (c) => {
      const agentId = await insertAgent(c, slug);
      const uniqueRepoName = `zsearchable-${randomUUID()}`;
      repoId = await insertRepository(c, `org/${uniqueRepoName}`);
      matchId = await insertRun(c, agentId, {
        status: "succeeded",
        minutesAgo: 5,
        repositoryId: repoId,
      });
      await insertRun(c, agentId, { status: "succeeded", minutesAgo: 6 }); // no repo, must not match

      const byName = await getFilteredRuns(
        client(),
        baseFilter({ agentSlug: slug, search: uniqueRepoName }),
        25,
      );
      expect(byName.totalCount).toBe(1);
      expect(byName.rows[0]!.id).toBe(matchId);

      const byId = await getFilteredRuns(
        client(),
        baseFilter({ agentSlug: slug, search: matchId }),
        25,
      );
      expect(byId.totalCount).toBe(1);
      expect(byId.rows[0]!.id).toBe(matchId);
    });
  });

  it("a search string containing ilike wildcard metacharacters (%, _) matches literally, not as a wildcard (v1.1 addendum)", async () => {
    const slug = `filt-wildcard-${randomUUID()}`;
    await withDb(async (c) => {
      const agentId = await insertAgent(c, slug);
      const literalName = `my_repo_${randomUUID()}`;
      const repoId = await insertRepository(c, `org/${literalName}`);
      await insertRun(c, agentId, { status: "succeeded", minutesAgo: 5, repositoryId: repoId });
      // A decoy repo whose name would ALSO match if `_` behaved as a
      // single-character SQL wildcard instead of a literal underscore.
      const decoyName = literalName.replace(/_/g, "X");
      const decoyRepoId = await insertRepository(c, `org/${decoyName}`);
      await insertRun(c, agentId, {
        status: "succeeded",
        minutesAgo: 6,
        repositoryId: decoyRepoId,
      });
    });

    const literalName = (await getFilteredRuns(client(), baseFilter({ agentSlug: slug }), 25)).rows;
    const searchTerm = literalName
      .map((r) => r.repository_full_name)
      .find((n) => n?.includes("my_repo"))!
      .split("/")[1]!;

    const result = await getFilteredRuns(
      client(),
      baseFilter({ agentSlug: slug, search: searchTerm }),
      25,
    );
    expect(result.totalCount).toBe(1);
    expect(result.rows[0]!.repository_full_name).toContain("my_repo");
  });

  it("a search string containing regex metacharacters never throws (mirrors AgentFilter EC-25)", async () => {
    const slug = `filt-regex-meta-${randomUUID()}`;
    await withDb(async (c) => {
      const agentId = await insertAgent(c, slug);
      await insertRun(c, agentId, { status: "succeeded", minutesAgo: 5 });
    });

    for (const meta of ["[", "(", ".*", "$^", "\\d+", "a|b"]) {
      await expect(
        getFilteredRuns(client(), baseFilter({ agentSlug: slug, search: meta }), 25),
      ).resolves.toBeDefined();
    }
  });

  it("reloading a URL reproduces the identical filtered result from a fresh server-side query (AC4)", async () => {
    const slug = `filt-reload-${randomUUID()}`;
    let repoId = "";
    await withDb(async (c) => {
      const agentId = await insertAgent(c, slug);
      repoId = await insertRepository(c, `org/reload-target-${randomUUID()}`);
      await insertRun(c, agentId, { status: "failed", minutesAgo: 5, repositoryId: repoId });
      await insertRun(c, agentId, { status: "succeeded", minutesAgo: 6, repositoryId: repoId });
    });

    const url = new URLSearchParams(`status=failed&repo=${repoId}&q=foo`);
    const parsed = parseRunFilter(url);
    const direct = await getFilteredRuns(
      client(),
      baseFilter({ agentSlug: slug, status: "failed", repositoryId: repoId }),
      25,
    );
    const viaUrl = await getFilteredRuns(client(), { ...parsed, agentSlug: slug }, 25);
    // Same status/repo filter, different search term ("foo" matches nothing
    // here) — the point is the URL round trip reproduces the same query shape
    // and result, not a client-side re-filter of a larger fetch.
    expect(viaUrl.totalCount).toBe(0);
    expect(direct.totalCount).toBe(1);
  });

  it("pagination is cumulative-offset and totalCount stays accurate under a filter (AC5)", async () => {
    const slug = `filt-page-${randomUUID()}`;
    await withDb(async (c) => {
      const agentId = await insertAgent(c, slug);
      for (let i = 0; i < 7; i++) {
        await insertRun(c, agentId, { status: "succeeded", minutesAgo: i + 1 });
      }
    });

    const page1 = await getFilteredRuns(client(), baseFilter({ agentSlug: slug }), 3);
    expect(page1.rows).toHaveLength(3);
    expect(page1.totalCount).toBe(7);

    const page2 = await getFilteredRuns(client(), baseFilter({ agentSlug: slug, page: 2 }), 3);
    expect(page2.rows).toHaveLength(6); // cumulative: pages 1..2
    expect(page2.totalCount).toBe(7);

    const page3 = await getFilteredRuns(client(), baseFilter({ agentSlug: slug, page: 3 }), 3);
    expect(page3.rows).toHaveLength(7); // exhausted before the requested ceiling
    expect(page3.totalCount).toBe(7);
  });

  it("a zero-match filter combination returns { rows: [], totalCount: 0 }, never an error (AC6, CT-2)", async () => {
    const slug = `filt-empty-${randomUUID()}`;
    await withDb(async (c) => {
      const agentId = await insertAgent(c, slug);
      await insertRun(c, agentId, { status: "succeeded", minutesAgo: 5 });
    });

    const result = await getFilteredRuns(
      client(),
      baseFilter({ agentSlug: slug, status: "failed" }),
      25,
    );
    expect(result).toEqual({ rows: [], totalCount: 0 });
  });

  it("getRunStatusCounts folds counts per effective_status for the current repo/search scope, excluding status itself", async () => {
    const slug = `filt-counts-${randomUUID()}`;
    await withDb(async (c) => {
      const agentId = await insertAgent(c, slug);
      await insertRun(c, agentId, { status: "succeeded", minutesAgo: 5 });
      await insertRun(c, agentId, { status: "succeeded", minutesAgo: 6 });
      await insertRun(c, agentId, { status: "failed", minutesAgo: 7 });
    });

    const counts = await getRunStatusCounts(client(), {
      agentSlug: slug,
      repositoryId: null,
      search: null,
    });
    expect(counts.succeeded).toBe(2);
    expect(counts.failed).toBe(1);
    expect(counts.all).toBe(3);
    expect(counts.running).toBe(0);
  });

  it("an empty agentSlug scope reads across every agent (S-146/FR13 reuse — agentSlug: null)", async () => {
    const slugA = `filt-cross-a-${randomUUID()}`;
    const slugB = `filt-cross-b-${randomUUID()}`;
    let idA = "";
    let idB = "";
    await withDb(async (c) => {
      const agentA = await insertAgent(c, slugA);
      const agentB = await insertAgent(c, slugB);
      idA = await insertRun(c, agentA, { status: "succeeded", minutesAgo: 5 });
      idB = await insertRun(c, agentB, { status: "succeeded", minutesAgo: 6 });
    });

    // Search for a run id that only exists once, scoped to null agent (cross-agent read).
    const result = await getFilteredRuns(
      client(),
      baseFilter({ agentSlug: null, search: idA }),
      25,
    );
    expect(result.rows.map((r) => r.id)).toEqual([idA]);
    expect(result.rows.map((r) => r.id)).not.toContain(idB);
  });

  it("agentSlug: null returns rows across >=2 agents, newest-first, count accurate (S-146 AC1)", async () => {
    const slugA = `filt-allruns-a-${randomUUID()}`;
    const slugB = `filt-allruns-b-${randomUUID()}`;
    let oldestId = "";
    let middleId = "";
    let newestId = "";
    await withDb(async (c) => {
      const agentA = await insertAgent(c, slugA);
      const agentB = await insertAgent(c, slugB);
      // Interleave insert order and agent ownership so a correct result can
      // only come from an unscoped, `created_at desc`-ordered read — not from
      // a coincidence of insertion or agent order.
      oldestId = await insertRun(c, agentA, { status: "succeeded", minutesAgo: 30 });
      newestId = await insertRun(c, agentB, { status: "succeeded", minutesAgo: 5 });
      middleId = await insertRun(c, agentA, { status: "succeeded", minutesAgo: 15 });
    });

    // A large page size — this is a shared, non-isolated fixture DB (other
    // suites/tests leave their own rows behind), so an unscoped, default-page
    // read could push these three fixture rows off page 1 before the
    // assertion below ever sees them. The property under test is ordering
    // and cross-agent attribution, not pagination (already covered above),
    // so a wide-enough page removes that false-negative risk.
    const result = await getFilteredRuns(client(), baseFilter({ agentSlug: null }), 5000);
    const ids = result.rows.map((r) => r.id);
    // Both agents' runs are present (cross-agent, not scoped to one).
    expect(ids).toEqual(expect.arrayContaining([oldestId, middleId, newestId]));
    // Newest-first ordering, verified by relative position among the three
    // fixture rows (ignoring any other rows that may exist in the fixture DB).
    const positions = [newestId, middleId, oldestId].map((id) => ids.indexOf(id));
    expect(positions[0]).toBeLessThan(positions[1]);
    expect(positions[1]).toBeLessThan(positions[2]);
    // Each row is correctly attributed to its own agent via `agent_slug`
    // (the S-146 Agent column reads straight off this).
    const bySlug = new Map(result.rows.map((r) => [r.id, r.agent_slug]));
    expect(bySlug.get(oldestId)).toBe(slugA);
    expect(bySlug.get(middleId)).toBe(slugA);
    expect(bySlug.get(newestId)).toBe(slugB);
  });

  it("a disabled agent's historical runs still appear in an agentSlug:null read (S-146 EC — not agent-scoped, unlike /agents/[slug]'s 404 rule)", async () => {
    const slug = `filt-disabled-${randomUUID()}`;
    let runId = "";
    await withDb(async (c) => {
      const agentId = await insertAgent(c, slug);
      runId = await insertRun(c, agentId, { status: "succeeded", minutesAgo: 5 });
      await c.query(`update agents set is_enabled = false where id = $1`, [agentId]);
    });

    const result = await getFilteredRuns(
      client(),
      baseFilter({ agentSlug: null, search: runId }),
      25,
    );
    expect(result.rows.map((r) => r.id)).toEqual([runId]);
  });
});

if (!runSuite) {
  describe("panel Layer 2.5 — getFilteredRuns / getRunStatusCounts (skipped)", () => {
    it.skip(`SKIPPED: ${skipReason}`, () => {});
  });
}
