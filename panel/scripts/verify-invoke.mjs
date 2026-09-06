#!/usr/bin/env node
/**
 * Live verification helper for issue #89 Check A (queued -> running).
 *
 * Submits an invoke to the LOCALLY running panel, then polls the `runs` row via
 * the Supabase REST API until it flips to `running` (or a terminal/timeout
 * state), printing the row transitions. This automates the observation in
 * docs/runbooks/issue-89-live-verification.md; it does NOT cover Check B
 * (malformed payload) or Check C (wrapper shape) — those need direct AWS +
 * CloudWatch access.
 *
 * This is an operator tool, run from a shell that has the panel env. It is not
 * imported by the app and not part of any test suite.
 *
 * Usage:
 *   SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... \
 *   node panel/scripts/verify-invoke.mjs --repo <REPO_UUID> [options]
 *
 * Options:
 *   --repo <uuid>       Repository id to invoke against (required)
 *   --slug <slug>       Agent slug (default: dependency-update)
 *   --panel <url>       Panel base URL (default: http://localhost:3000)
 *   --params <json>     params object (default: {"fix_mode":"audit_only"})
 *   --timeout <sec>     Max seconds to poll for `running` (default: 320)
 *   --interval <sec>    Poll interval (default: 3)
 *   --help              Show this help
 *
 * Env:
 *   SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY (or SERVICE_ROLE_KEY) — required for polling.
 */

const args = process.argv.slice(2);
function opt(name, fallback) {
  const i = args.indexOf(`--${name}`);
  return i !== -1 && args[i + 1] ? args[i + 1] : fallback;
}
if (args.includes("--help") || args.length === 0) {
  console.log(
    [
      "verify-invoke — issue #89 Check A (queued -> running)",
      "",
      "  SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... \\",
      "  node panel/scripts/verify-invoke.mjs --repo <REPO_UUID> [--slug dependency-update]",
      '    [--panel http://localhost:3000] [--params \'{"fix_mode":"audit_only"}\']',
      "    [--timeout 320] [--interval 3]",
    ].join("\n"),
  );
  process.exit(args.includes("--help") ? 0 : 1);
}

const repoId = opt("repo");
const slug = opt("slug", "dependency-update");
const panel = opt("panel", "http://localhost:3000").replace(/\/$/, "");
const paramsRaw = opt("params", '{"fix_mode":"audit_only"}');
const timeoutSec = Number(opt("timeout", "320"));
const intervalSec = Number(opt("interval", "3"));

const supabaseUrl = (process.env.SUPABASE_URL ?? "").replace(/\/$/, "");
const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY ?? process.env.SERVICE_ROLE_KEY ?? "";

function fail(msg) {
  console.error(`ERROR: ${msg}`);
  process.exit(1);
}

if (!repoId) fail("--repo <REPO_UUID> is required (see `--help`).");
if (!supabaseUrl || !serviceKey) {
  fail("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or SERVICE_ROLE_KEY) must be set.");
}
let params;
try {
  params = JSON.parse(paramsRaw);
} catch {
  fail(`--params must be valid JSON (got: ${paramsRaw}).`);
}

async function fetchRun(runId) {
  const url =
    `${supabaseUrl}/rest/v1/runs?id=eq.${encodeURIComponent(runId)}` +
    `&select=id,status,started_at,finished_at,error_code`;
  const res = await fetch(url, {
    headers: { apikey: serviceKey, authorization: `Bearer ${serviceKey}` },
  });
  if (!res.ok) fail(`Supabase read failed: HTTP ${res.status} ${await res.text()}`);
  const rows = await res.json();
  return rows[0] ?? null;
}

const TERMINAL = new Set(["succeeded", "failed", "canceled", "timed_out", "failed_to_start"]);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  console.log(`> Invoking ${slug} against repository ${repoId} via ${panel} ...`);
  const res = await fetch(`${panel}/api/agents/${slug}/invoke`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ repository_id: repoId, params }),
  });
  const body = await res.json().catch(() => ({}));
  console.log(`> Route responded HTTP ${res.status}: ${JSON.stringify(body)}`);

  const runId = body.run_id;
  if (!runId) {
    fail(`No run_id in response (status ${res.status}). Check the route/params and try again.`);
  }
  if (res.status !== 202) {
    console.log(
      `> Non-202 (${res.status}). run_id=${runId} was recorded; polling its state anyway.`,
    );
  }

  console.log(`> Polling runs.id=${runId} every ${intervalSec}s for up to ${timeoutSec}s ...`);
  const deadline = Date.now() + timeoutSec * 1000;
  let lastStatus = null;
  let sawRunning = false;

  while (Date.now() < deadline) {
    const row = await fetchRun(runId);
    if (row && row.status !== lastStatus) {
      console.log(
        `  [${new Date().toISOString()}] status=${row.status}` +
          `${row.started_at ? ` started_at=${row.started_at}` : ""}` +
          `${row.error_code ? ` error_code=${row.error_code}` : ""}`,
      );
      lastStatus = row.status;
      if (row.status === "running") sawRunning = true;
      if (TERMINAL.has(row.status)) {
        console.log(sawRunning ? "\nPASS (AC1): observed queued -> running." : "");
        console.log(`> Reached terminal state: ${row.status}. Done.`);
        process.exit(sawRunning || row.status === "succeeded" ? 0 : 2);
      }
    }
    await sleep(intervalSec * 1000);
  }

  if (sawRunning) {
    console.log("\nPASS (AC1): observed queued -> running (did not wait for terminal).");
    process.exit(0);
  }
  console.log(
    `\nFAIL: run did not reach 'running' within ${timeoutSec}s (last status: ${lastStatus}).` +
      " Check CloudWatch for the agent-side error.",
  );
  process.exit(2);
})().catch((err) => fail(err?.message ?? String(err)));
