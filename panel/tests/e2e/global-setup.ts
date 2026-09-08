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

import { execSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { Client } from "pg";

import { resolveLocalSupabaseEnv } from "./fixtures/local-env";
import { startAgentCoreStub, type AgentCoreStubHandle } from "./fixtures/agentcore-stub";
import { AGENTCORE_STUB_PORT } from "./fixtures/stub-port";

const READINESS_TIMEOUT_MS = Number(process.env.E2E_READINESS_TIMEOUT_MS ?? "60000");
const POLL_INTERVAL_MS = 500;

/** Resolve the supabase CLI binary — honor an explicit override, else PATH. */
const SUPABASE_BIN = process.env.SUPABASE_BIN ?? "supabase";

declare global {
  // eslint-disable-next-line no-var
  var __AGENTCORE_STUB__: AgentCoreStubHandle | undefined;
}

function repoRoot(): string {
  // This file is panel/tests/e2e/global-setup.ts. `fileURLToPath` decodes
  // percent-encoding (the repo path may contain spaces). Repo root is four
  // segments up from the file: e2e → tests → panel → <root>.
  return fileURLToPath(new URL("../../../../", import.meta.url));
}

/**
 * Return a copy of the environment with common CLI install dirs appended to
 * PATH, so `supabase` resolves even when the parent process PATH is minimal.
 */
function withCliPath(): NodeJS.ProcessEnv {
  const extra = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"];
  const current = process.env.PATH ?? "";
  const merged = [current, ...extra].filter(Boolean).join(":");
  return { ...process.env, PATH: merged };
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

async function assertSeededCatalog(host: string, port: number): Promise<void> {
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
    const agent = await client.query(
      `select 1 from agents where slug = 'dependency-update' and is_enabled = true`,
    );
    const repo = await client.query(
      `select 1 from repositories where is_enabled = true and archived_at is null limit 1`,
    );
    if (agent.rowCount === 0 || repo.rowCount === 0) {
      throw new Error(
        "E2E setup: the seeded catalog is missing the enabled 'dependency-update' agent and/or an enabled repository. " +
          "Apply the seed with `supabase db reset` (or run globalSetup with E2E_DB_RESET=1).",
      );
    }
  } finally {
    await client.end().catch(() => {});
  }
}

/**
 * Reproduce, on the LOCAL CLI stack only, the privileges the hosted Supabase
 * platform grants `service_role` automatically (technical-guidelines §7). The
 * panel reads AND writes server-side with the service role key (the invoke
 * route inserts the `queued` run); without these grants a fresh `supabase db
 * reset` denies those statements with 42501. Scoped to `service_role` ONLY —
 * never `anon` — so RLS deny-all is untouched.
 */
async function grantServiceRoleSelectLocalOnly(host: string, port: number): Promise<void> {
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
    await client.query(`grant usage on schema public to service_role`);
    await client.query(`grant all privileges on all tables in schema public to service_role`);
    await client.query(`grant all privileges on all sequences in schema public to service_role`);
  } finally {
    await client.end().catch(() => {});
  }
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

  // 1. Optionally reset to the seeded baseline. This is OPT-IN
  //    (`E2E_DB_RESET=1`): in CI the workflow starts a fresh stack and applies
  //    migrations + seed itself, and locally the stack is already seeded while
  //    each spec resets its own run rows in `beforeEach`. Shelling out to the
  //    Supabase CLI from Playwright's globalSetup is fragile (PATH / config
  //    detection), so we do it only when explicitly asked, and otherwise rely on
  //    readiness verification + a seeded-catalog assertion below.
  if (process.env.E2E_DB_RESET === "1") {
    try {
      execSync(`${SUPABASE_BIN} db reset --local`, {
        cwd: repoRoot(),
        stdio: "inherit",
        env: withCliPath(),
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

  // 3. Assert the seeded catalog is present — the scenarios depend on the
  //    `dependency-update` agent + at least one enabled repository. Fail fast
  //    with the exact remediation instead of letting every scenario fail.
  await assertSeededCatalog(env.SUPABASE_DB_HOST, Number(env.SUPABASE_DB_PORT));

  // 3b. Apply the LOCAL-ONLY `service_role` SELECT grant. The hosted Supabase
  //     platform applies these grants automatically as default table
  //     privileges, but `supabase db reset` on the CLI does NOT reproduce them
  //     (technical-guidelines §7 — the S-104 grant-asymmetry note). Without it
  //     the panel's server-side reads (service_role) are denied locally with
  //     42501 and every page 500s. Scoped to `service_role` ONLY — never
  //     `anon` — so RLS deny-all (D11) is preserved. The Layer 2.5 `queries`
  //     integration test applies the identical grant for the same reason.
  await grantServiceRoleSelectLocalOnly(env.SUPABASE_DB_HOST, Number(env.SUPABASE_DB_PORT));

  // 4. Start the AgentCore stub on its fixed port; the config points the SDK at it.
  const stub = await startAgentCoreStub(AGENTCORE_STUB_PORT);
  globalThis.__AGENTCORE_STUB__ = stub;
  console.log(`[e2e] AgentCore stub listening on ${stub.endpoint}`);
}
