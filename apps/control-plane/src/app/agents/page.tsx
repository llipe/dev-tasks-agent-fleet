/**
 * Agents list page — S-019.
 *
 * Server component that fetches agent inventory, config counts, and 30d cost aggregate.
 * Renders a DataTable with streaming cost column via Suspense boundary.
 */

import { Suspense } from "react";
import { listManagedAgents } from "@/server/aws/tagging-adapter.js";
import { listAgentSubjects } from "@/server/repository/scope-repository.js";
import { getAgentCostAggregate } from "@/lib/cost.js";
import { getAgentLifecycle } from "@/server/aws/agentcore-adapter.js";
import { buildAgentRows, type AgentRow, type AgentDataDeps } from "./agents-data.js";
import { AgentsTable } from "./agents-table.js";
import { AgentsCostColumn } from "./agents-cost-column.js";

export const dynamic = "force-dynamic";

/** Production dependencies wiring real adapters */
function createProductionDeps(): AgentDataDeps {
  return {
    listManagedAgents,
    listAgentSubjects,
    getAgentCostAggregate: async (agentName: string) => {
      const { queryRuns } = await import("@/server/runs/run-query-service.js");
      const thirtyDaysAgo = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000);
      const now = new Date();

      return getAgentCostAggregate(agentName, async () => {
        const outcome = await queryRuns({
          agentName,
          from: thirtyDaysAgo,
          to: now,
        });
        if (outcome.status === "ok") {
          return outcome.data.map((run) => ({ perModel: run.perModel }));
        }
        return [];
      });
    },
    getAgentLifecycle,
  };
}

export default async function AgentsPage() {
  let rows: AgentRow[] = [];
  let state: "ready" | "empty" | "error" | "timeout" = "ready";

  try {
    const deps = createProductionDeps();
    rows = await buildAgentRows(deps);

    if (rows.length === 0) {
      state = "empty";
    }
  } catch (error: unknown) {
    const errorObj = error as Error & { code?: string };
    if (errorObj.code === "TIMEOUT" || errorObj.message?.includes("timeout")) {
      state = "timeout";
    } else {
      state = "error";
    }
  }

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold text-text-primary">Agents</h1>
      <p className="mt-1 text-sm text-text-secondary">
        Managed agent inventory and status overview.
      </p>

      <div className="mt-6">
        <Suspense
          fallback={
            <AgentsTable data={rowsWithoutCost(rows)} state={state === "ready" ? "ready" : state} />
          }
        >
          <AgentsCostColumn rows={rows} state={state} />
        </Suspense>
      </div>
    </div>
  );
}

/** Strip cost data for the initial render (before cost streams in) */
function rowsWithoutCost(rows: AgentRow[]): AgentRow[] {
  return rows.map((row) => ({ ...row, cost30d: null }));
}
