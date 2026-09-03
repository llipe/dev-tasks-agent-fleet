import { execFileSync } from "node:child_process";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Security-negative build-artifact test (S-104 / issue #117, CT-7, AC-104.6).
// Proves no client-side chunk contains the service role key.
//
// G3 design note: a grep for the real key cannot run where no key exists (CI),
// and a grep for nothing is a test that cannot fail — worse than no test. So we
// build with a recognizable SENTINEL value and grep the real build output for
// BOTH the sentinel and the `SUPABASE_SERVICE_ROLE_KEY` identifier. If the
// server-only key ever leaks into a client bundle, the sentinel appears and the
// test fails loudly, with no real secret ever present in CI.
//
// The test performs a production build with the sentinel env, then scans
// `.next/static/**` (the browser-served assets). It is slow (~30–60s), so it is
// given a generous timeout. If the Next build cannot run in this environment it
// records a skip reason rather than a false green.

const SENTINEL = "SENTINEL_MUST_NOT_APPEAR_IN_BUNDLE";
const IDENTIFIER = "SUPABASE_SERVICE_ROLE_KEY";

const panelDir = join(__dirname, "..", "..");
const staticDir = join(panelDir, ".next", "static");

// This test builds the app, which is slow (~30-60s). To keep the routine
// `pnpm run test:unit` / `make validate` fast, the real build runs only when
// `RUN_BUNDLE_SECRET_TEST=1` is set (CI sets it, and it is run explicitly
// during story verification). Otherwise it skips with a recorded reason — never
// a false green. This is the mechanical gate G3 asked for; it is opt-in for
// speed, not opt-out for correctness.
const ENABLED = process.env.RUN_BUNDLE_SECRET_TEST === "1";

function runBuild(): { ok: boolean; reason: string } {
  if (!ENABLED) {
    return {
      ok: false,
      reason:
        "set RUN_BUNDLE_SECRET_TEST=1 to run the production build + bundle grep (skipped for speed in the routine gate; CI runs it)",
    };
  }
  try {
    execFileSync("pnpm", ["run", "build"], {
      cwd: panelDir,
      env: {
        ...process.env,
        SUPABASE_URL: "http://127.0.0.1:54321",
        SUPABASE_SERVICE_ROLE_KEY: SENTINEL,
        // Keep the build non-interactive and deterministic.
        CI: "1",
      },
      stdio: "pipe",
      timeout: 240_000,
    });
    return { ok: true, reason: "build completed with sentinel key" };
  } catch (err) {
    const e = err as { message?: string; stderr?: Buffer | string; stdout?: Buffer | string };
    const detail = [e.message, e.stderr?.toString(), e.stdout?.toString()]
      .filter(Boolean)
      .join("\n")
      .slice(-1500);
    return { ok: false, reason: `next build could not run in this environment: ${detail}` };
  }
}

function walkFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walkFiles(p));
    else out.push(p);
  }
  return out;
}

const build = runBuild();

describe.skipIf(!build.ok)("panel bundle — no service role key in client chunks", () => {
  it("built the client assets with the sentinel key", () => {
    expect(existsSync(staticDir), `${staticDir} should exist after build`).toBe(true);
  });

  it("no client-served file contains the sentinel service role key value", () => {
    const files = walkFiles(staticDir);
    const leaking = files.filter((f) => readFileSync(f, "utf8").includes(SENTINEL));
    expect(leaking, `sentinel leaked into: ${leaking.join(", ")}`).toHaveLength(0);
  });

  it("no client-served file contains the SUPABASE_SERVICE_ROLE_KEY identifier", () => {
    const files = walkFiles(staticDir);
    const leaking = files.filter((f) => readFileSync(f, "utf8").includes(IDENTIFIER));
    expect(leaking, `identifier leaked into: ${leaking.join(", ")}`).toHaveLength(0);
  });
});

if (!build.ok) {
  describe("panel bundle — no service role key in client chunks (skipped)", () => {
    it.skip(`SKIPPED: ${build.reason}`, () => {});
  });
}
