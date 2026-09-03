#!/usr/bin/env node
/**
 * Resilient dependency-audit gate for the `panel` package.
 *
 * `pnpm audit` POSTs the dependency set to the npm registry's advisory
 * endpoint (https://registry.npmjs.org/-/npm/v1/security/audits). That network
 * call is a third-party dependency of the gate and it flakes: in CI it has
 * failed with `ERR_SOCKET_TIMEOUT` after exhausting pnpm's own retries, which
 * exited the step non-zero and reddened the whole run — a network blip, not a
 * vulnerability.
 *
 * This wrapper keeps the SECURITY signal intact while removing the RELIABILITY
 * failure mode:
 *
 *   - It runs `pnpm audit --prod --audit-level=high --json` and inspects the
 *     machine-readable result.
 *   - A genuine high/critical advisory → EXIT 1 (the gate must fail; this is
 *     the behavior we are protecting).
 *   - A clean audit (no high+ advisory) → EXIT 0.
 *   - A transport failure (socket timeout / DNS / registry 5xx — i.e. the audit
 *     never actually ran to a verdict) → retry a few times, then SOFT-PASS with
 *     a loud warning and EXIT 0, rather than block a PR on an unreachable
 *     third-party endpoint.
 *
 * The distinction is the point: we only ever swallow "could not reach the
 * registry", never "the registry told us about a high-severity CVE".
 */

import { spawnSync } from "node:child_process";

const AUDIT_LEVEL = "high";
const MAX_ATTEMPTS = Number(process.env.AUDIT_MAX_ATTEMPTS ?? 3);
const RETRY_BASE_MS = Number(process.env.AUDIT_RETRY_BASE_MS ?? 5000);
// Hard ceiling per attempt. pnpm has its own internal retries against the
// advisory endpoint; if a single attempt still has not returned within this
// window the registry is effectively unreachable and we treat it as a
// transport failure rather than hang the CI step indefinitely. Overridable via
// env so CI can tune it (and tests can shrink it).
const ATTEMPT_TIMEOUT_MS = Number(process.env.AUDIT_ATTEMPT_TIMEOUT_MS ?? 60000);

// Severities at or above the gate level that MUST fail the build.
const BLOCKING_SEVERITIES = new Set(["high", "critical"]);

// Substrings that identify a transport/availability failure (audit never
// reached a verdict) as opposed to a real advisory result.
const TRANSPORT_ERROR_SIGNATURES = [
  "ERR_SOCKET_TIMEOUT",
  "ERR_PNPM_META_FETCH_FAIL",
  "ETIMEDOUT",
  "ECONNRESET",
  "ECONNREFUSED",
  "ENOTFOUND",
  "EAI_AGAIN",
  "socket timeout",
  "network",
  "request to https://registry",
  "getaddrinfo",
];

function sleep(ms) {
  // Block without CPU-spinning: wait on a private SharedArrayBuffer that is
  // never notified, so the wait always runs to its full timeout.
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

function runAudit() {
  return spawnSync("pnpm", ["audit", "--prod", `--audit-level=${AUDIT_LEVEL}`, "--json"], {
    encoding: "utf8",
    shell: false,
    timeout: ATTEMPT_TIMEOUT_MS,
  });
}

/**
 * Count advisories at or above the blocking severity from a parsed
 * `pnpm audit --json` payload. pnpm reports either a `metadata.vulnerabilities`
 * severity->count map, and/or an `advisories`/`vulnerabilities` object keyed by
 * id. We read the metadata map (authoritative for counts) and fall back to
 * scanning advisory entries.
 */
export function countBlocking(parsed) {
  let count = 0;

  const meta = parsed?.metadata?.vulnerabilities;
  if (meta && typeof meta === "object") {
    for (const sev of BLOCKING_SEVERITIES) {
      if (typeof meta[sev] === "number") count += meta[sev];
    }
    return count;
  }

  const advisories = parsed?.advisories ?? parsed?.vulnerabilities;
  if (advisories && typeof advisories === "object") {
    for (const entry of Object.values(advisories)) {
      const sev = String(entry?.severity ?? "").toLowerCase();
      if (BLOCKING_SEVERITIES.has(sev)) count += 1;
    }
  }
  return count;
}

export function looksLikeTransportError(text) {
  if (!text) return false;
  return TRANSPORT_ERROR_SIGNATURES.some((sig) => text.includes(sig));
}

export function tryParseJson(stdout) {
  if (!stdout) return null;
  // pnpm emits a single JSON object on stdout for --json; guard against
  // stray non-JSON prefixes/suffixes by extracting the outermost braces.
  const start = stdout.indexOf("{");
  const end = stdout.lastIndexOf("}");
  if (start === -1 || end === -1 || end < start) return null;
  try {
    return JSON.parse(stdout.slice(start, end + 1));
  } catch {
    return null;
  }
}

function main() {
  let lastCombined = "";

  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    const result = runAudit();

    // A timeout kill (spawnSync `timeout` exceeded) surfaces as a terminating
    // signal and/or an error whose code is ETIMEDOUT. Treat it as a transport
    // failure — the audit never reached a verdict because the registry hung.
    const timedOut =
      result.signal === "SIGTERM" ||
      result.error?.code === "ETIMEDOUT" ||
      (result.error && /timed out|ETIMEDOUT/i.test(result.error.message ?? ""));

    if (result.error && !timedOut) {
      // spawn itself failed (e.g. pnpm not found) — not a transient registry
      // issue; surface it.
      console.error(`[audit] failed to spawn pnpm: ${result.error.message}`);
      process.exit(1);
    }

    const stdout = result.stdout ?? "";
    const stderr = result.stderr ?? "";
    lastCombined = `${stdout}\n${stderr}${timedOut ? "\nERR_SOCKET_TIMEOUT (attempt timeout)" : ""}`;

    const parsed = tryParseJson(stdout);

    if (parsed) {
      // The audit reached a verdict. Trust it.
      const blocking = countBlocking(parsed);
      if (blocking > 0) {
        console.error(
          `[audit] FAIL — ${blocking} advisory(ies) at severity >= ${AUDIT_LEVEL}. ` +
            `Resolve or override before merging.`,
        );
        // Emit the raw audit JSON so the failing advisories are in the log.
        process.stdout.write(stdout);
        process.exit(1);
      }
      console.log(
        `[audit] OK — no advisories at severity >= ${AUDIT_LEVEL} ` +
          `(exit code from pnpm: ${result.status}).`,
      );
      process.exit(0);
    }

    // No parseable verdict. Decide whether this was a transport failure.
    if (looksLikeTransportError(lastCombined)) {
      console.warn(
        `[audit] attempt ${attempt}/${MAX_ATTEMPTS}: could not reach the npm ` +
          `advisory registry (transient network error).`,
      );
      if (attempt < MAX_ATTEMPTS) {
        const backoff = RETRY_BASE_MS * attempt;
        console.warn(`[audit] retrying in ${backoff / 1000}s...`);
        sleep(backoff);
        continue;
      }
      // Exhausted retries on a transport fault: soft-pass so a registry
      // outage does not block a PR. Loud, so it is visible in the log.
      console.warn(
        "::warning title=pnpm audit skipped::" +
          "The npm advisory registry was unreachable after " +
          `${MAX_ATTEMPTS} attempts (network error, not a vulnerability). ` +
          "Dependency audit was SOFT-PASSED for this run. Re-run once the " +
          "registry is reachable to restore the security signal.",
      );
      process.exit(0);
    }

    // Not a transport error and not parseable JSON — an unexpected audit
    // failure (e.g. a real non-zero verdict pnpm could not serialize, or a
    // config error). Surface it rather than swallow it.
    console.error(
      `[audit] FAIL — pnpm audit exited ${result.status} with no parseable ` +
        `JSON verdict and no recognized transport error. Output follows:`,
    );
    process.stdout.write(stdout);
    process.stderr.write(stderr);
    process.exit(result.status && result.status !== 0 ? result.status : 1);
  }

  // Unreachable, but exit non-zero defensively if the loop ever falls through.
  console.error("[audit] FAIL — exhausted attempts without a decision.");
  process.exit(1);
}

// Run the CLI only when executed directly, not when imported by a test.
import { fileURLToPath } from "node:url";
if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  main();
}
