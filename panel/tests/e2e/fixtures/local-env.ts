/**
 * Resolve the local Supabase stack's env for E2E (S-114).
 *
 * The panel-under-test needs the server-only Supabase config (SD2: no
 * `NEXT_PUBLIC_*`, service role key server-side only). In CI the workflow
 * exports these before launching Playwright; locally we resolve them from
 * `supabase status -o env` so a developer does not have to export anything by
 * hand.
 *
 * Precedence: an already-exported env var wins (CI path); otherwise we shell
 * out to the Supabase CLI once and cache the result.
 */

import { execFileSync } from "node:child_process";

export interface LocalSupabaseEnv {
  SUPABASE_URL: string;
  SUPABASE_SERVICE_ROLE_KEY: string;
  SUPABASE_ANON_KEY: string;
  SUPABASE_DB_HOST: string;
  SUPABASE_DB_PORT: string;
}

let cached: LocalSupabaseEnv | null = null;

function fromCli(): Record<string, string> {
  // `supabase status -o env` prints KEY="value" / KEY=value lines. Parse them.
  const out = execFileSync("supabase", ["status", "-o", "env"], {
    encoding: "utf8",
    cwd: repoRoot(),
  });
  const env: Record<string, string> = {};
  for (const line of out.split("\n")) {
    const m = line.match(/^([A-Z0-9_]+)=(.*)$/);
    if (!m) continue;
    let value = m[2].trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    env[m[1]] = value;
  }
  return env;
}

/** The repo root is two levels above `panel/` (panel/tests/e2e/fixtures). */
function repoRoot(): string {
  return new URL("../../../../", import.meta.url).pathname;
}

export function resolveLocalSupabaseEnv(): LocalSupabaseEnv {
  if (cached) return cached;

  // If everything is already exported (CI), use it and skip the CLI entirely.
  const preset =
    process.env.SUPABASE_URL &&
    process.env.SUPABASE_SERVICE_ROLE_KEY &&
    (process.env.SUPABASE_ANON_KEY ?? process.env.ANON_KEY);
  if (preset) {
    cached = {
      SUPABASE_URL: process.env.SUPABASE_URL!,
      SUPABASE_SERVICE_ROLE_KEY: process.env.SUPABASE_SERVICE_ROLE_KEY!,
      SUPABASE_ANON_KEY: (process.env.SUPABASE_ANON_KEY ?? process.env.ANON_KEY)!,
      SUPABASE_DB_HOST: process.env.SUPABASE_DB_HOST ?? "127.0.0.1",
      SUPABASE_DB_PORT: process.env.SUPABASE_DB_PORT ?? "54322",
    };
    return cached;
  }

  const cli = fromCli();
  const url = process.env.SUPABASE_URL ?? cli.API_URL;
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY ?? cli.SERVICE_ROLE_KEY;
  const anonKey = process.env.SUPABASE_ANON_KEY ?? cli.ANON_KEY;
  if (!url || !serviceKey || !anonKey) {
    throw new Error(
      "E2E setup: could not resolve the local Supabase env. Run `supabase start` (Docker required) or export SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY / SUPABASE_ANON_KEY.",
    );
  }
  cached = {
    SUPABASE_URL: url,
    SUPABASE_SERVICE_ROLE_KEY: serviceKey,
    SUPABASE_ANON_KEY: anonKey,
    SUPABASE_DB_HOST: process.env.SUPABASE_DB_HOST ?? "127.0.0.1",
    SUPABASE_DB_PORT: process.env.SUPABASE_DB_PORT ?? "54322",
  };
  return cached;
}
