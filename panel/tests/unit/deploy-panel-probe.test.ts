import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { execFileSync } from "node:child_process";
import {
  chmodSync,
  copyFileSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

// Issue #280 (PR #295 review, points 1 & 2, then the security re-review). The
// deploy-time OIDC probe in scripts/deploy-panel.sh must decide PASS/FAIL from
// the probe's OUTPUT, NOT from `flyctl machine exec`'s exit status — because
// `flyctl machine exec` returns exit 0 even when the remote command fails
// (verified live: `flyctl machine exec <id> 'false'` prints `Exit code: 1` to
// stdout but exits 0 itself). Gating on flyctl's status is a SILENT-FAILURE
// mode: a real token failure prints `status=0 token=absent` (+ `Exit code: 1`)
// yet the deploy reports OK.
//
// PASS only when the captured output contains a line matching EXACTLY
// `^status=2[0-9]{2} token=present$`. Anything else fails with exit 3 (the
// script's verify-fail code). flyctl's own nonzero status is also a failure.
//
// The auth gate is now HARD-WIRED to scripts/verify-panel-auth.sh with NO
// env-driven override (the DEPLOY_PANEL_VERIFY_CMD seam was removed — an env
// switch that can disable a security gate is itself the vulnerability). To
// exercise the probe branch WITHOUT a production seam, these tests build a temp
// directory that mirrors the repo layout (a copy of the REAL deploy-panel.sh
// plus a STUB scripts/verify-panel-auth.sh that exits 0), put the realistic
// fake `flyctl` on PATH, and run the real script with cwd = the temp dir. The
// script resolves scripts/verify-panel-auth.sh relative to its own location
// (REPO_ROOT = dirname($0)/..), so the temp copy picks up the stub.

const REPO_ROOT = fileURLToPath(new URL("../../../", import.meta.url));
const DEPLOY_SCRIPT = join(REPO_ROOT, "scripts", "deploy-panel.sh");

interface RunResult {
  status: number;
  stdout: string;
  stderr: string;
  combined: string;
}

let workdir: string;

/**
 * Lay out a temp directory mirroring the repo (scripts/deploy-panel.sh copied
 * verbatim, plus a stub scripts/verify-panel-auth.sh), drop a realistic fake
 * `flyctl` onto PATH, then run the REAL deploy-panel.sh with cwd = temp dir.
 *
 * The fake `flyctl` stubs every subcommand the script calls on the happy path
 * (auth whoami, deploy, machine list) and mimics `machine exec`'s REAL
 * behavior: it always exits 0, printing whatever the test configures via the
 * probe line plus, when probeExitEcho is set, flyctl's `Exit code: <n>` echo of
 * the remote command's status.
 */
function runDeploy(opts: {
  probeLine: string;
  probeExitEcho?: number;
  flyctlExecExitsNonzero?: boolean;
  machineListJson?: string;
}): RunResult {
  const scriptsDir = join(workdir, "scripts");
  mkdirSync(scriptsDir, { recursive: true });

  // Run the REAL deploy-panel.sh — copied into the mirrored layout so that
  // REPO_ROOT (dirname($0)/..) resolves to workdir and the stub auth gate at
  // workdir/scripts/verify-panel-auth.sh is the one it invokes.
  const deployCopy = join(scriptsDir, "deploy-panel.sh");
  copyFileSync(DEPLOY_SCRIPT, deployCopy);
  chmodSync(deployCopy, 0o755);

  // The stub auth gate — exits 0 so the script reaches the OIDC-probe branch
  // without a live deploy or a live release gate. No production seam.
  const verifyStub = join(scriptsDir, "verify-panel-auth.sh");
  writeFileSync(verifyStub, "#!/usr/bin/env bash\nexit 0\n");
  chmodSync(verifyStub, 0o755);

  const flyBin = join(workdir, "flyctl");
  const machineListJson =
    opts.machineListJson ?? JSON.stringify([{ id: "abc123", state: "started" }]);

  // The fake flyctl. `machine exec` ALWAYS exits 0 unless the test asks for a
  // flyctl-level error, exactly like the real binary. The remote command's real
  // status is only visible in the `Exit code: N` line it prints to stdout.
  const fake = `#!/usr/bin/env bash
set -eu
case "$1 \${2:-}" in
  "auth whoami") exit 0 ;;
esac
case "$1" in
  deploy) exit 0 ;;
  machine)
    sub="\${2:-}"
    case "$sub" in
      list) printf '%s' '${machineListJson.replace(/'/g, "'\\''")}' ; exit 0 ;;
      exec)
        ${opts.flyctlExecExitsNonzero ? 'echo "flyctl: machine exec failed" >&2; exit 1' : ""}
        printf '%s\\n' '${opts.probeLine.replace(/'/g, "'\\''")}'
        ${opts.probeExitEcho !== undefined ? `printf 'Exit code: %s\\n' '${opts.probeExitEcho}'` : ""}
        exit 0
        ;;
    esac
    ;;
esac
exit 0
`;
  writeFileSync(flyBin, fake);
  chmodSync(flyBin, 0o755);

  try {
    const stdout = execFileSync("bash", [deployCopy], {
      cwd: workdir,
      encoding: "utf8",
      env: {
        ...process.env,
        PATH: `${workdir}:${process.env.PATH ?? ""}`,
        NEXT_PUBLIC_SUPABASE_URL: "http://example.invalid",
        NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: "test-key",
      },
    });
    return { status: 0, stdout, stderr: "", combined: stdout };
  } catch (err) {
    const e = err as { status?: number; stdout?: unknown; stderr?: unknown };
    const stdout = String(e.stdout ?? "");
    const stderr = String(e.stderr ?? "");
    return { status: e.status ?? -1, stdout, stderr, combined: stdout + stderr };
  }
}

beforeEach(() => {
  workdir = mkdtempSync(join(tmpdir(), "deploy-panel-probe-"));
});

afterEach(() => {
  rmSync(workdir, { recursive: true, force: true });
});

describe("deploy-panel.sh OIDC probe — verdict from OUTPUT, not flyctl exit status (#280)", () => {
  it("(a) flyctl exit 0 + remote absent (`status=0 token=absent`, `Exit code: 1`) → exit 3", () => {
    // The real silent-failure case: `machine exec` exits 0, the probe reports an
    // absent token, flyctl echoes `Exit code: 1`. The deploy MUST fail (exit 3).
    const r = runDeploy({ probeLine: "status=0 token=absent", probeExitEcho: 1 });
    expect(r.status).toBe(3);
    expect(r.combined).toContain("VERIFY-FAIL");
  });

  it("(b) flyctl exit 0 + `status=200 token=present` → pass (exit 0)", () => {
    const r = runDeploy({ probeLine: "status=200 token=present" });
    expect(r.status).toBe(0);
    expect(r.combined).toContain("OK");
  });

  it("(c) flyctl itself exits nonzero → exit 3", () => {
    const r = runDeploy({ probeLine: "", flyctlExecExitsNonzero: true });
    expect(r.status).toBe(3);
    expect(r.combined).toContain("VERIFY-FAIL");
  });

  it("(d) flyctl exit 0 + empty probe output → exit 3", () => {
    const r = runDeploy({ probeLine: "" });
    expect(r.status).toBe(3);
    expect(r.combined).toContain("VERIFY-FAIL");
  });

  it("rejects a non-2xx status even with token=present (e.g. 404)", () => {
    const r = runDeploy({ probeLine: "status=404 token=present" });
    expect(r.status).toBe(3);
  });

  it("no token text appears in any output (presence only)", () => {
    const r = runDeploy({ probeLine: "status=0 token=absent", probeExitEcho: 1 });
    // The probe emits only `status=<code> token=<present|absent>`; never a JWT.
    expect(r.combined).not.toMatch(/eyJ[A-Za-z0-9_-]{10,}/);
  });
});

describe("deploy-panel.sh — the auth gate has no env-driven override (#280 security re-review)", () => {
  it("contains no DEPLOY_PANEL_VERIFY_CMD seam and no env override of the gate command", () => {
    const src = readFileSync(DEPLOY_SCRIPT, "utf8");
    // The removed seam: any environment that set DEPLOY_PANEL_VERIFY_CMD could
    // skip the release gate ADR-007 makes the panel's security boundary.
    expect(src).not.toContain("DEPLOY_PANEL_VERIFY_CMD");
    // No indirection: the gate is invoked directly, not through a variable that
    // an environment value could redefine.
    expect(src).not.toMatch(/VERIFY_CMD\s*=/);
    expect(src).toContain("scripts/verify-panel-auth.sh");
  });
});
