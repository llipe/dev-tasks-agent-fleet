/**
 * S-161/S-162 (#273/#274) — the Schedules screen `/schedules` (DESIGN.md §5.7).
 *
 * Async server component (SD2): reads `v_schedules` (optionally scoped to one
 * agent via `?agent=<slug>`, the §5.7.1 indicator link), the enabled agents (for
 * the dialog's agent select + schema), and the enabled repositories. Hands them
 * to the `SchedulesClient` controller. Route-segment config inline (never cached;
 * a new schedule must appear on next navigation).
 */

import { createServerClient } from "@/lib/supabase/server";
import { getEnabledAgents, getEnabledRepositories, getSchedules } from "@/lib/supabase/queries";
import { SchedulesClient } from "@/components/schedules/SchedulesClient";
import type { AgentOption, RepositoryOption } from "@/components/schedules/ScheduleDialog";

import styles from "./page.module.css";

export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";

export default async function SchedulesPage({
  searchParams,
}: {
  searchParams: Promise<{ agent?: string }>;
}) {
  const { agent: agentFilter } = await searchParams;
  const client = createServerClient();

  const [schedules, agents, repositories] = await Promise.all([
    getSchedules(client, agentFilter),
    getEnabledAgents(client),
    getEnabledRepositories(client),
  ]);

  const agentOptions: AgentOption[] = agents.map((a) => ({
    id: a.id,
    slug: a.slug,
    name: a.name,
    isEnabled: a.is_enabled,
    requiresRepository: a.requires_repository,
    paramsSchema: a.params_schema,
    defaultParams: a.default_params,
  }));
  const repositoryOptions: RepositoryOption[] = repositories.map((r) => ({
    id: r.id,
    fullName: r.full_name,
    defaultBranch: r.default_branch,
  }));

  const paused = schedules.filter((s) => s.state === "paused").length;
  const blocked = schedules.filter((s) => s.state === "blocked").length;

  return (
    <main className={styles.page}>
      <div className={styles.headerRow}>
        <h1 className={styles.heading}>Schedules</h1>
        {agentFilter && (
          <a className={styles.filterChip} href="/schedules">
            agent: {agentFilter} <span aria-hidden="true">✕</span>
          </a>
        )}
      </div>

      <p className={styles.stat}>
        {schedules.length} schedule{schedules.length === 1 ? "" : "s"} · {paused} paused ·{" "}
        <span className={blocked > 0 ? styles.blockedCount : undefined}>{blocked} blocked</span>
        <span className={styles.tzNote}> · all times America/Santiago unless noted</span>
      </p>

      <SchedulesClient
        rows={schedules}
        agents={agentOptions}
        repositories={repositoryOptions}
        agentFilter={agentFilter ?? null}
      />
    </main>
  );
}
