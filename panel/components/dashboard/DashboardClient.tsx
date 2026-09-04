"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import type { AgentSummary } from "@/lib/domain/dashboard";
import { filterAgentSummaries } from "@/lib/domain/dashboard";
import { DEFAULT_DENSITY, readDensity, writeDensity, type Density } from "@/lib/ui/density-state";
import { isTypingTarget } from "@/lib/ui/shortcuts";
import { KLabel } from "@/components/KLabel";

import { AgentFilter } from "./AgentFilter";
import { AgentCards } from "./AgentCards";
import { DenseRows } from "./DenseRows";
import { DensityToggle } from "./DensityToggle";
import { Ledger } from "./Ledger";
import styles from "./DashboardClient.module.css";

/**
 * The dashboard's single client component (task 2.5/2.9). The server component
 * reads once and passes the shaped summaries + a fixed `nowMs` as props; this
 * component holds the presentation state (density + transient filter) and swaps
 * which variant renders. It performs no data access — a client component cannot
 * construct the `server-only` Supabase client — so the toggle and the filter
 * physically cannot refetch, and neither navigates.
 *
 * Hydration contract (mirrors the shell, S-106): density lives in
 * `localStorage`, unreadable on the server, so the first client render uses the
 * fixed `DEFAULT_DENSITY` and the stored value is reconciled in a mount effect —
 * never during render — so server and client markup match.
 */
export interface DashboardClientProps {
  agents: AgentSummary[];
  nowMs: number;
  /**
   * Whether the invoke route (S-113) exists yet. While false, the Invoke
   * action renders disabled rather than linking to a 404 (task 2.11). Passed as
   * a serializable boolean, not a function, so it can cross the server→client
   * boundary.
   */
  invokeRouteAvailable: boolean;
}

export function DashboardClient({ agents, nowMs, invokeRouteAvailable }: DashboardClientProps) {
  const [density, setDensity] = useState<Density>(DEFAULT_DENSITY);
  const [query, setQuery] = useState("");
  const filterRef = useRef<HTMLInputElement>(null);

  // Maps a slug to its invoke route, or null while the route is unbuilt (S-113).
  const invokeHref = (slug: string): string | null =>
    invokeRouteAvailable ? `/agents/${slug}/invoke` : null;

  // Reconcile density from storage once, after mount — never during render.
  useEffect(() => {
    const stored = readDensity(typeof window === "undefined" ? null : window.localStorage);
    if (stored !== DEFAULT_DENSITY) setDensity(stored);
  }, []);

  // Persist density on change (best-effort; the filter is intentionally NOT
  // persisted — a remembered filter would hide agents on the next load).
  useEffect(() => {
    writeDensity(typeof window === "undefined" ? null : window.localStorage, density);
  }, [density]);

  // Global `/` focuses the filter (superset of §6.5's ledger-only binding,
  // since the filter is a common header element). It must not steal a `/`
  // typed into a text field (same guard as Cmd+\).
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "/") return;
      if (isTypingTarget(event.target)) return;
      event.preventDefault();
      filterRef.current?.focus();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const filtered = useMemo(() => filterAgentSummaries(agents, query), [agents, query]);
  const focusFilter = () => filterRef.current?.focus();

  const totalRuns = agents.reduce((sum, a) => sum + a.runCount, 0);

  return (
    <section className={styles.dashboard} aria-label="Agents dashboard">
      <header className={styles.header}>
        <div className={styles.titleRow}>
          <h1 className={styles.title}>Agents</h1>
          <span className={styles.stats}>
            {agents.length} {agents.length === 1 ? "agent" : "agents"} · {totalRuns} runs
          </span>
        </div>
        <div className={styles.controls}>
          <AgentFilter ref={filterRef} value={query} onChange={setQuery} />
          <DensityToggle value={density} onChange={setDensity} />
        </div>
      </header>

      {agents.length === 0 ? (
        <EmptyNoAgents />
      ) : filtered.length === 0 ? (
        <EmptyNoMatch query={query} />
      ) : density === "cards" ? (
        <AgentCards agents={filtered} nowMs={nowMs} invokeHref={invokeHref} />
      ) : density === "ledger" ? (
        <Ledger
          agents={filtered}
          nowMs={nowMs}
          invokeHref={invokeHref}
          onFocusFilter={focusFilter}
        />
      ) : (
        <DenseRows agents={filtered} nowMs={nowMs} invokeHref={invokeHref} />
      )}
    </section>
  );
}

/** Empty state — no agents configured at all (a fresh deployment, EC-19). */
function EmptyNoAgents() {
  return (
    <div className={styles.empty} role="status">
      <KLabel>No agents</KLabel>
      <p className={styles.emptyTitle}>No agents configured</p>
      <p className={styles.emptyBody}>
        Agents are added via the seed (<code>supabase/seed.sql</code>). Once an agent row exists it
        appears here.
      </p>
    </div>
  );
}

/**
 * Empty state — a filter matched nothing. This MUST read differently from "no
 * agents configured" (EC-25): an operator who filters and sees the fleet-gone
 * copy would conclude the fleet is gone.
 */
function EmptyNoMatch({ query }: { query: string }) {
  return (
    <div className={styles.empty} role="status">
      <KLabel>No matches</KLabel>
      <p className={styles.emptyTitle}>
        Nothing matches “<span className={styles.query}>{query.trim()}</span>”
      </p>
      <p className={styles.emptyBody}>Clear the filter to see all agents.</p>
    </div>
  );
}
