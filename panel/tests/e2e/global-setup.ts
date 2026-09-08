/**
 * Playwright global setup (S-114 task 1.5).
 *
 * Runs ONCE before any scenario:
 *   1. Resolve the local Supabase stack env (CLI locally, exported vars in CI).
 *   2. Reset the database to the seeded baseline (`supabase db reset` applies
 *      `supabase/migrations/` + `supabase/seed.sql`) so every run starts from
 *      the same known catalog — the seeded `dependency-update` agent + repos.
 *   3. Wait for readiness with an explicit poll (never a fixed sleep): the
 *      PostgREST API must answer and the DB must be reachable.
 *   4. Start the AgentCore HTTP-boundary stub on its fixed port so the panel's
 *      invoke path is intercepted at the network boundary (no real AWS call).
 *
 * Fails fast with a clear, actionable message when the stack is unavailable —
 * a missing Docker daemon is a setup error the developer can fix, not a flake
 * to paper over.
 *
 * The stub handle is stashed on `globalThis` so `global-teardown.ts` can close
 * it. The env values are written into `process.env` so the config's
 * `webServer.env` (evaluated later, when the server launches) sees them.
 */

import { execFileSync } from "node:child_process";
import { Client } from "pg";

import { resolveLocalSupabaseEnv } from "./fixtures/local-env";
import { startAgentCoreStub, type AgentCoreStubHandle } from "./fixtures/agentcore-stub";
import { AGENTCORE_STUB_PORT } from "./fixtures/stub-port";

const READINESS_TIMEOUT_MS = Number(process.env.E2E_READINESS_TIMEOUT_MS ?? "60000");
const POLL_INTERVAL_MS = 500;

declare global {
  // eslint-disable-next-line no-var
  var __AGENTCORE_STUB__: AgentCoreStubHandle | undefined;
}

function repoRoot(): string {
  return new URL("../../../", import.meta.url).pathname;
}

async function waitForDb(host: string, port: number, deadline: number): Promise<void> {
  let lastErr: unknown;
  while (Date.now() < deadline) {
    const client = new Client({
      host,
      port,
      user: "postgres",
      password: "postgres",
      database: "postgres",
      connectionTimeoutMillis: 1500,
    });
    try {
      await client.connect();
      await client.query("select 1");
      await client.end();
      return;
    } catch (err) {
      lastErr = err;
      await client.end().catch(() => {});
      await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
    }
  }
  const msg = lastErr instanceof Error ? lastErr.message : String(lastErr);
  throw new Error(
    `E2E setup: local Postgres not reachable at ${host}:${port} within ${READINESS_TIMEOUT_MS}ms. ` +
      `Start the stack with \`supabase start\` (Docker required). Last error: ${msg}`,
  );
}

async function waitForRest(apiUrl: string, anonKey: string, deadline: number): Promise<void> {
  let lastStatus = 0;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${apiUrl}/rest/v1/`, {
        headers: { apikey: anonKey, Authorization: `Bearer ${anonKey}` },
      });
      lastStatus = res.status;
      // PostgREST answers 200 on the root once it is up.
      if (res.status >= 200 && res.status < 500) return;
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
  }
  throw new Error(
    `E2E setup: PostgREST at ${apiUrl}/rest/v1/ did not become ready within ${READINESS_TIMEOUT_MS}ms (last status ${lastStatus}).`,
  );
}

export default async function globalSetup(): Promise<void> {
  const env = resolveLocalSupabaseEnv();

  // Export for the webServer (config reads process.env at launch) and for the
  // seed helpers (pg config).
  process.env.SUPABASE_URL = env.SUPABASE_URL;
  process.env.SUPABASE_SERVICE_ROLE_KEY = env.SUPABASE_SERVICE_ROLE_KEY;
  process.env.SUPABASE_ANON_KEY = env.SUPABASE_ANON_KEY;
  process.env.SUPABASE_DB_HOST = env.SUPABASE_DB_HOST;
  process.env.SUPABASE_DB_PORT = env.SUPABASE_DB_PORT;

  const deadline = Date.now() + READINESS_TIMEOUT_MS;

  // 1. Reset to the seeded baseline. Skippable in CI where the workflow already
  //    reset the stack before launching Playwright (E2E_SKIP_DB_RESET=1).
  if (process.env.E2E_SKIP_DB_RESET !== "1") {
    try {
      execFileSync("supabase", ["db", "reset", "--local"], {
        cwd: repoRoot(),
        stdio: "inherit",
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      throw new Error(
        `E2E setup: \`supabase db reset\` failed — the stack must be running (\`supabase start\`, Docker required). ${msg}`,
      );
    }
  }

  // 2. Explicit readiness polls (no fixed sleep).
  await waitForDb(env.SUPABASE_DB_HOST, Number(env.SUPABASE_DB_PORT), deadline);
  await waitForRest(env.SUPABASE_URL, env.SUPABASE_ANON_KEY, deadline);

  // 3. Start the AgentCore stub on its fixed port; the config points the SDK at it.
  const stub = await startAgentCoreStub(AGENTCORE_STUB_PORT);
  globalThis.__AGENTCORE_STUB__ = stub;
  // eslint-disable-next-line no-console
  console.log(`[e2e] AgentCore stub listening on ${stub.endpoint}`);
}
