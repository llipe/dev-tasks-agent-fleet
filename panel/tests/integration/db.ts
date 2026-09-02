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

// Probe the local stack once. Returns availability plus a human-readable reason
// suitable for a `SKIPPED(<reason>)` record when the stack is down.
export async function probeLocalDb(): Promise<DbAvailability> {
  const cfg = localDbConfig();
  const client = new Client(cfg);
  try {
    await client.connect();
    await client.query("select 1");
    return { available: true, reason: "local Supabase Postgres reachable" };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return {
      available: false,
      reason: `local Supabase Postgres not reachable at ${cfg.host}:${cfg.port} (run \`supabase start\` + \`supabase db reset\`; Docker required) — ${msg}`,
    };
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
