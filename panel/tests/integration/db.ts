import { Client, type ClientConfig } from "pg";

// Layer 2.5 (integration) DB helper. These tests talk to a REAL local Postgres
// brought up by the Supabase CLI (`supabase start` / `supabase db reset`) — the
// data layer is never mocked (TESTING.md Layer 2.5 boundary).
//
// The local stack is Docker-backed. When Docker is unavailable (e.g. the CI or
// dev machine has no daemon), the integration suite MUST skip with a recorded
// reason rather than fail — this keeps `test:integration` reachable from
// `make validate` without turning a missing daemon into a red gate
// (TESTING.md: "Docker absent -> integration layer skips with a recorded reason").

// Supabase CLI default local Postgres connection (see supabase/config.toml,
// [db] port = 54322). Overridable via env for CI or a non-default stack.
export function localDbConfig(): ClientConfig {
  return {
    host: process.env.SUPABASE_DB_HOST ?? "127.0.0.1",
    port: Number(process.env.SUPABASE_DB_PORT ?? "54322"),
    user: process.env.SUPABASE_DB_USER ?? "postgres",
    password: process.env.SUPABASE_DB_PASSWORD ?? "postgres",
    database: process.env.SUPABASE_DB_NAME ?? "postgres",
    // Fail fast when nothing is listening, so the skip-gate resolves quickly.
    connectionTimeoutMillis: Number(process.env.SUPABASE_DB_TIMEOUT_MS ?? "1500"),
  };
}

export interface DbAvailability {
  available: boolean;
  reason: string;
}

/**
 * `REQUIRE_LOCAL_DB=1` turns a Docker-gated skip into a hard failure (#134).
 *
 * Locally (unset) the Layer 2.5 suites skip with a recorded reason when the
 * stack is down — a missing daemon must not redden a developer's `make
 * validate`. In CI the workflow starts the stack and sets `REQUIRE_LOCAL_DB=1`,
 * so a suite that would otherwise skip vacuously instead FAILS (enforced in
 * `probeLocalDb` below): a green CI must mean the DB-boundary assertions
 * actually ran, not that they were skipped.
 */
export function requireLocalDb(): boolean {
  return process.env.REQUIRE_LOCAL_DB === "1";
}

// Probe the local stack once. Returns availability plus a human-readable reason
// suitable for a `SKIPPED(<reason>)` record when the stack is down.
//
// #134 CI gate: when `REQUIRE_LOCAL_DB=1` and the stack is NOT reachable, this
// THROWS instead of returning an unavailable result. Every Layer 2.5 suite
// calls `probeLocalDb()` at module top-level, so a throw here fails that test
// file in CI — turning a would-be vacuous skip into a hard failure, uniformly,
// for every current and future suite (no per-suite assertion change needed).
// Locally (`REQUIRE_LOCAL_DB` unset) the behavior is unchanged: it returns
// `{ available: false, reason }` and the suite skips with that recorded reason.
export async function probeLocalDb(): Promise<DbAvailability> {
  const cfg = localDbConfig();
  const client = new Client(cfg);
  try {
    await client.connect();
    await client.query("select 1");
    return { available: true, reason: "local Supabase Postgres reachable" };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    const reason = `local Supabase Postgres not reachable at ${cfg.host}:${cfg.port} (run \`supabase start\` + \`supabase db reset\`; Docker required) — ${msg}`;
    if (requireLocalDb()) {
      // CI: a skip is not evidence. Fail loudly rather than pass vacuously.
      throw new Error(
        `REQUIRE_LOCAL_DB=1 but the local Supabase stack is unavailable: ${reason}. ` +
          `In CI a Docker-gated skip of a Layer 2.5 suite is a FAILURE (#134) — the DB-boundary ` +
          `assertions must actually run. Start the stack before the JS/TS test branch.`,
      );
    }
    return { available: false, reason };
  } finally {
    await client.end().catch(() => {});
  }
}

// Convenience: run a query against the local stack with a fresh client.
export async function withDb<T>(fn: (client: Client) => Promise<T>): Promise<T> {
  const client = new Client(localDbConfig());
  await client.connect();
  try {
    return await fn(client);
  } finally {
    await client.end().catch(() => {});
  }
}
