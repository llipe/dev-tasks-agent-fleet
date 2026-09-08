/**
 * Warm up Supabase Realtime before the Layer 2.5 + E2E test branch (S-114 / #134).
 *
 * Right after `supabase start` / `supabase db reset`, Realtime can take a few
 * seconds before a channel reaches `SUBSCRIBED`. The Realtime-dependent suites
 * (`stream-e2e.test.ts`, and the E2E live-tail scenarios) run with no retry, so
 * a first-run miss against a cold Realtime is a flake. This script opens a
 * throwaway channel and resolves only once Realtime confirms the subscription
 * (an EXPLICIT readiness wait, not a sleep), then exits. Best-effort: if the
 * subscription cannot confirm within the window it logs and exits 0 rather than
 * blocking the pipeline — the suites still have their own waits.
 *
 * Reads SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY from the environment (the CI
 * job exports them from `supabase status -o env`).
 */

import { createClient } from "@supabase/supabase-js";

const url = process.env.SUPABASE_URL;
const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
const timeoutMs = Number(process.env.REALTIME_WARMUP_TIMEOUT_MS ?? "20000");

if (!url || !key) {
  console.log("[warm-realtime] SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set; skipping.");
  process.exit(0);
}

const client = createClient(url, key, {
  auth: { autoRefreshToken: false, persistSession: false },
  realtime: { params: { eventsPerSecond: 50 } },
});

const channel = client.channel("ci-realtime-warmup");

const done = new Promise((resolve) => {
  const timer = setTimeout(() => {
    console.log(`[warm-realtime] did not confirm within ${timeoutMs}ms; continuing.`);
    resolve();
  }, timeoutMs);
  channel
    .on("postgres_changes", { event: "INSERT", schema: "public", table: "run_events" }, () => {})
    .subscribe((status) => {
      if (status === "SUBSCRIBED") {
        console.log("[warm-realtime] Realtime SUBSCRIBED — warm.");
        clearTimeout(timer);
        resolve();
      }
    });
});

await done;
await client.removeChannel(channel).catch(() => {});
await client.removeAllChannels().catch(() => {});
process.exit(0);
