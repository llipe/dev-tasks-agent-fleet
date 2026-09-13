import { spawnSync } from "node:child_process";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { afterAll, beforeAll, describe, expect, it } from "vitest";

/**
 * CLI entrypoint of the AUTH-gate parser (Story S-122, PRD AC17).
 *
 * REPLACES fly-privacy-check-cli.test.ts (the privacy gate's CLI contract).
 * The pure decision logic is covered by panel-auth-check.test.ts; this suite
 * covers the process-level contract the release wrapper depends on — the exact
 * exit codes `scripts/verify-panel-auth.sh` turns into "release allowed" vs
 * "release BLOCKED". Spawning the real Node CLI is the only way to exercise the
 * `process.exit` wiring, and it makes the "gate observed failing" evidence
 * end-to-end (a violation → non-zero exit), not just at the function boundary.
 */

const CLI = fileURLToPath(new URL("../../scripts/panel-auth-check.mjs", import.meta.url));

let dir: string;
let okInput: string;
let signupOpenInput: string;
let protected200Input: string;
let garbageInput: string;

const OK = {
  envNames: ["NEXT_PUBLIC_SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_ANON_KEY"],
  protectedProbe: { status: 302, location: "/login?redirect=/" },
  sseProbe: { status: 401 },
  signupProbe: { rejected: true },
};

beforeAll(() => {
  dir = mkdtempSync(join(tmpdir(), "panel-auth-cli-"));
  okInput = join(dir, "ok.json");
  signupOpenInput = join(dir, "signup-open.json");
  protected200Input = join(dir, "protected-200.json");
  garbageInput = join(dir, "garbage.json");
  writeFileSync(okInput, JSON.stringify(OK));
  writeFileSync(
    signupOpenInput,
    JSON.stringify({ ...OK, signupProbe: { rejected: false, createdUserId: "u-1" } }),
  );
  writeFileSync(protected200Input, JSON.stringify({ ...OK, protectedProbe: { status: 200 } }));
  writeFileSync(garbageInput, "this is not json {");
});

afterAll(() => {
  rmSync(dir, { recursive: true, force: true });
});

function run(inputPath: string) {
  return spawnSync(process.execPath, [CLI, inputPath], { encoding: "utf8" });
}

describe("panel-auth-check CLI — exit-code contract (release gate)", () => {
  it("exits 0 (release allowed) on a fully correct deployment fixture", () => {
    const r = run(okInput);
    expect(r.status).toBe(0);
    expect(r.stdout).toMatch(/auth boundary holds/i);
  });

  it("exits 0 with the new publishable key env name (#172)", () => {
    const publishableInput = join(dir, "publishable.json");
    writeFileSync(
      publishableInput,
      JSON.stringify({
        ...OK,
        envNames: ["NEXT_PUBLIC_SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY"],
      }),
    );
    const r = run(publishableInput);
    expect(r.status).toBe(0);
  });

  it("exits 1 (release BLOCKED) when a signUp succeeds — gate observed failing (AC17)", () => {
    const r = run(signupOpenInput);
    expect(r.status).toBe(1);
    expect(r.stderr).toMatch(/BLOCKED/i);
    expect(r.stderr).toMatch(/self-register|enabled|succeeded/i);
  });

  it("exits 1 when a protected UI path returns 200", () => {
    const r = run(protected200Input);
    expect(r.status).toBe(1);
    expect(r.stderr).toMatch(/200/);
  });

  it("is fail-closed: unreadable/garbage input exits non-zero", () => {
    expect(run(garbageInput).status).toBe(1);
    expect(run(join(dir, "does-not-exist.json")).status).toBe(1);
  });
});
