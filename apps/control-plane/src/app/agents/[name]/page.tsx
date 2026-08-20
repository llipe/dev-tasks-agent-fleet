/**
 * Agent detail page — S-020.
 *
 * Server component that reads searchParams for tab, status, from, to, run.
 * Renders a tab shell (Runs / Repos) with the Runs tab as default.
 */

import { parseRunFilters, type ParsedRunFilters } from "@/lib/run-filters.js";
import { AgentDetailShell } from "./agent-detail-shell.js";
import { RunsTab } from "./runs-tab.js";

export const dynamic = "force-dynamic";

interface AgentDetailPageProps {
  params: Promise<{ name: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function AgentDetailPage({ params, searchParams }: AgentDetailPageProps) {
  const { name } = await params;
  const rawParams = await searchParams;
  const agentName = decodeURIComponent(name);

  // Normalize searchParams to simple string values
  const normalizedParams: Record<string, string> = {};
  for (const [key, value] of Object.entries(rawParams)) {
    if (typeof value === "string") {
      normalizedParams[key] = value;
    } else if (Array.isArray(value) && value.length > 0 && value[0] !== undefined) {
      normalizedParams[key] = value[0];
    }
  }

  const filters: ParsedRunFilters = parseRunFilters(normalizedParams);

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold text-text-primary">{agentName}</h1>
      <p className="mt-1 text-sm text-text-secondary">Agent detail and run history.</p>

      <AgentDetailShell agentName={agentName} filters={filters}>
        {filters.tab === "runs" ? (
          <RunsTab agentName={agentName} filters={filters} />
        ) : (
          <div className="mt-4 rounded-lg border border-surface-border p-8 text-center text-text-muted">
            Repos tab — coming in S-022.
          </div>
        )}
      </AgentDetailShell>
    </div>
  );
}
