import { createServerClient } from "@/lib/supabase/server";
import { getDashboardData, type DashboardRunRow } from "@/lib/supabase/queries";
import { buildAgentSummaries, type AgentSummaryInput } from "@/lib/domain/dashboard";
import { DashboardClient } from "@/components/dashboard/DashboardClient";

/**
 * Agents dashboard (`/`, Story S-107).
 *
 * Route-segment config is declared **inline** — Next.js silently ignores these
 * values when re-exported from another module and falls back to static
 * rendering (S-104 audit D4, technical-guidelines §12). A cached run list is
 * exactly the staleness FR11a exists to prevent, so this is a correctness
 * requirement. `lib/supabase/route-config.ts` holds the canonical values as
 * documentation; they are copied here on purpose.
 */
export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";

// The invoke route (S-113) does not exist yet; render Invoke disabled until it
// lands (task 2.11) rather than linking to a 404.
const INVOKE_ROUTE_AVAILABLE = false;

function toRun(row: DashboardRunRow): AgentSummaryInput["runs"][number] {
  return {
    status: row.status,
    startedAtMs: row.started_at ? Date.parse(row.started_at) : null,
    queuedAtMs: Date.parse(row.queued_at),
    finishedAtMs: row.finished_at ? Date.parse(row.finished_at) : null,
    createdAtMs: Date.parse(row.created_at),
    maxRuntimeSeconds: row.max_runtime_seconds,
    graceSeconds: row.grace_seconds,
    startTimeoutSeconds: row.start_timeout_seconds,
    outcome: row.outcome,
  };
}

export default async function DashboardPage() {
  const client = createServerClient();
  const { agents, runs } = await getDashboardData(client);

  // A single injected instant for every relative time + status derivation on
  // this render, so nothing reads an ambient clock mid-render (EC-9).
  const nowMs = Date.now();

  // Group the flat runs by agent, then shape. This is presentation mapping, not
  // a second query — the read already happened once (CT-7).
  const runsByAgent = new Map<string, DashboardRunRow[]>();
  for (const row of runs) {
    const list = runsByAgent.get(row.agent_id);
    if (list) list.push(row);
    else runsByAgent.set(row.agent_id, [row]);
  }

  const input: AgentSummaryInput[] = agents.map((a) => ({
    id: a.id,
    slug: a.slug,
    name: a.name,
    description: a.description,
    requiresRepository: a.requires_repository,
    runs: (runsByAgent.get(a.id) ?? []).map(toRun),
  }));

  const summaries = buildAgentSummaries(input, nowMs);

  return (
    <DashboardClient
      agents={summaries}
      nowMs={nowMs}
      invokeRouteAvailable={INVOKE_ROUTE_AVAILABLE}
    />
  );
}
