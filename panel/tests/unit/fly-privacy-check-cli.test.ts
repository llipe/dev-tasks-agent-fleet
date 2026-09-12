import { spawnSync } from "node:child_process";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { afterAll, beforeAll, describe, expect, it } from "vitest";

/**
 * CLI entrypoint of the privacy-gate parser (Story S-115, AC6).
 *
 * The pure decision logic is covered by fly-privacy-check.test.ts; this suite
 * covers the process-level contract the release script depends on — the exact
 * exit codes `scripts/verify-fly-private.sh` turns into "release allowed" vs
 * "release BLOCKED". Spawning the real Node CLI is the only way to exercise the
 * `process.exit` wiring, and it makes the "gate observed failing" evidence
 * end-to-end (a public IP → non-zero exit), not just at the function boundary.
 */

const CLI = fileURLToPath(new URL("../../scripts/fly-privacy-check.mjs", import.meta.url));

let dir: string;
let publicIps: string;
let privateIps: string;
let noSvc: string;
let publicSvc: string;

beforeAll(() => {
  dir = mkdtempSync(join(tmpdir(), "fly-privacy-cli-"));
  publicIps = join(dir, "public-ips.json");
  privateIps = join(dir, "private-ips.json");
  noSvc = join(dir, "no-svc.json");
  publicSvc = join(dir, "public-svc.json");
  writeFileSync(publicIps, JSON.stringify([{ Address: "168.220.90.10", Type: "v4" }]));
  writeFileSync(privateIps, JSON.stringify([{ Address: "fdaa:0:1::2", Type: "private" }]));
  writeFileSync(noSvc, JSON.stringify({ Services: [] }));
  writeFileSync(
    publicSvc,
    JSON.stringify({ Services: [{ Protocol: "tcp", Ports: [{ Port: 443, Handlers: ["http"] }] }] }),
  );
});

afterAll(() => {
  rmSync(dir, { recursive: true, force: true });
});

function run(ips: string, status: string) {
  return spawnSync(process.execPath, [CLI, ips, status], { encoding: "utf8" });
}

describe("fly-privacy-check CLI — exit-code contract (AC6)", () => {
  it("exits 0 (release allowed) for a private-only allocation", () => {
    const r = run(privateIps, noSvc);
    expect(r.status).toBe(0);
    expect(r.stdout).toMatch(/private-only/i);
  });

  it("exits 1 (release BLOCKED) when a public IP is allocated — gate observed failing", () => {
    const r = run(publicIps, noSvc);
    expect(r.status).toBe(1);
    expect(r.stderr).toMatch(/BLOCKED/i);
    expect(r.stderr).toMatch(/Public IP/i);
  });

  it("exits 1 when a public service is exposed even with no public IP", () => {
    const r = run(privateIps, publicSvc);
    expect(r.status).toBe(1);
    expect(r.stderr).toMatch(/Public service/i);
  });

  it("is fail-closed: a missing/garbage IP file cannot silently pass with a public service", () => {
    // Missing IP file (null) + a public service still blocks.
    const r = run(join(dir, "does-not-exist.json"), publicSvc);
    expect(r.status).toBe(1);
  });
});
