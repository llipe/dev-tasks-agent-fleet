import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { execFileSync } from "node:child_process";
import { chmodSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

// Issue #280 (PR #295 review, point 1 & 2). The deploy-time OIDC probe in
// scripts/deploy-panel.sh must decide PASS/FAIL from the probe's OUTPUT, NOT
// from `flyctl machine exec`'s exit status — because `flyctl machine exec`
// returns exit 0 even when the remote command fails (verified live:
// `flyctl machine exec <id> 'false'` prints `Exit code: 1` to stdout but exits
// 0 itself). Gating on flyctl's status is a SILENT-FAILURE mode: a real token
// failure prints `status=0 token=absent` (+ `Exit code: 1`) yet the deploy
// reports OK. These tests drive the REAL deploy-panel.sh with a realistic fake
// `flyctl` and assert the output-driven verdict.
//
// PASS only when the captured output contains a line matching EXACTLY
// `^status=2[0-9]{2} token=present$`. Anything else fails with exit 3 (the
// script's verify-fail code). flyctl's own nonzero status is also a failure.

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
 * Write a fake `flyctl` onto a throwaway dir and prepend it to PATH, then run
 * the real deploy-panel.sh. The fake stubs every flyctl subcommand the script
 * calls on the happy path (auth whoami, deploy, machine list) and mimics
 * `machine exec`'s REAL behavior: it always exits 0, printing whatever the test
 * configures via FAKE_PROBE_LINE (the probe's own stdout line) plus, when
 * FAKE_PROBE_EXITCODE is set, flyctl's `Exit code: <n>` echo of the remote
 * command's status.
 */
function runDeploy(opts: {
  probeLine: string;
  probeExitEcho?: number;
  flyctlExecExitsNonzero?: boolean;
  machineListJson?: string;
}): RunResult {
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

  // A fake auth gate so the script reaches the probe without a live deploy.
  const verifyBin = join(workdir, "verify-panel-auth.sh");
  writeFileSync(verifyBin, "#!/usr/bin/env bash\nexit 0\n");
  chmodSync(verifyBin, 0o755);

  try {
    const stdout = execFileSync("bash", [DEPLOY_SCRIPT], {
      cwd: REPO_ROOT,
      encoding: "utf8",
      env: {
        ...process.env,
        PATH: `${workdir}:${process.env.PATH ?? ""}`,
        NEXT_PUBLIC_SUPABASE_URL: "http://example.invalid",
        NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: "test-key",
        DEPLOY_PANEL_VERIFY_CMD: verifyBin,
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
