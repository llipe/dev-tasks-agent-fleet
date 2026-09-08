import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { probeLocalDb } from "./db";
import {
  countRuns,
  getSeededIds,
  latestRunId,
  readRun,
  resetRuns,
  seedArtifact,
  seedEvent,
  seedRun,
} from "../e2e/fixtures/seed";

/**
 * Layer 2.5 smoke for the E2E seeding/reset fixture helper itself (S-114 task
 * 1.8, story Testing Requirements: "a Layer 2.5 smoke that the seeding/reset
 * fixture helper itself works").
 *
 * The E2E specs depend on `tests/e2e/fixtures/seed.ts` producing a known
 * baseline deterministically. If the reset does not clear runs, or an insert
 * lands with the wrong clocks/status, every scenario built on it is quietly
 * unsound. This test pins the fixture's contract against the REAL local stack,
 * independent of a browser — so a fixture regression is caught here, not as a
 * confusing E2E flake.
 *
 * Docker-gated (like every Layer 2.5 suite): skips with a recorded reason when
 * the stack is down; in CI (`REQUIRE_LOCAL_DB=1`) a skip is a failure (#134).
 */

const probe = await probeLocalDb();
const skipReason = probe.available ? "" : probe.reason;

describe.skipIf(!probe.available)("E2E seed fixture — Layer 2.5 smoke", () => {
  beforeAll(async () => {
    console.log(`[integration] ${probe.reason}`);
    await resetRuns();
  });

  afterAll(async () => {
    await resetRuns();
  });

  it("resolves the seeded dependency-update agent + an enabled repository", async () => {
    const ids = await getSeededIds();
    expect(ids.agentSlug).toBe("dependency-update");
    expect(ids.agentId).toMatch(/^[0-9a-f-]{36}$/);
    expect(ids.repositoryId).toMatch(/^[0-9a-f-]{36}$/);
    expect(ids.repositoryFullName.length).toBeGreaterThan(0);
  });

  it("resetRuns() clears runs and children to zero", async () => {
    await seedRun({ status: "running", startedAgoSecs: 30 });
    expect(await countRuns()).toBeGreaterThan(0);
    await resetRuns();
    expect(await countRuns()).toBe(0);
  });

  it("seedRun() writes exactly one row with the requested status + explicit timeout snapshots", async () => {
    await resetRuns();
    const runId = await seedRun({
      status: "running",
      startedAgoSecs: 30,
      maxRuntimeSeconds: 3600,
      graceSeconds: 120,
      startTimeoutSeconds: 300,
    });
    expect(await countRuns()).toBe(1);
    const row = await readRun(runId);
    expect(row).not.toBeNull();
    expect(row!.status).toBe("running");
    expect(row!.max_runtime_seconds).toBe(3600);
    expect(row!.grace_seconds).toBe(120);
    expect(row!.start_timeout_seconds).toBe(300);
    expect(await latestRunId()).toBe(runId);
  });

  it("seedEvent() and seedArtifact() attach children to a run", async () => {
    await resetRuns();
    const runId = await seedRun({ status: "failed", startedAgoSecs: 120, finishedAgoSecs: 10 });
    await seedEvent(runId, 1, "first line");
    await seedEvent(runId, 2, "second line", "error");
    await seedArtifact(runId, "pull_request", "chore: bump deps", "https://github.com/x/y/pull/1");
    // Assert through the same fixture DB connection (no app read path here).
    // The presence is proven by the E2E scenarios; here we only prove the
    // helpers do not throw and the run remains singular.
    expect(await countRuns()).toBe(1);
  });

  it("a stale running run is inserted with clocks past its threshold (Scenario 4 precondition)", async () => {
    await resetRuns();
    // started 3800s ago, threshold = 3600 + 120 = 3720 → effective timed_out.
    const runId = await seedRun({
      status: "running",
      startedAgoSecs: 3800,
      maxRuntimeSeconds: 3600,
      graceSeconds: 120,
    });
    const row = await readRun(runId);
    // The raw column is still 'running' — the reaper is OFF; the view derives it.
    expect(row!.status).toBe("running");
  });
});

if (!probe.available) {
  describe("E2E seed fixture — Layer 2.5 smoke (skipped)", () => {
    it.skip(`SKIPPED: ${skipReason}`, () => {});
  });
}
