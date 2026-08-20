"use client";

/**
 * Agent detail tab shell — S-020.
 *
 * Client component for tab switching (Runs / Repos) via URL `tab` param.
 * Uses shallow navigation (router.replace) to avoid full page reloads.
 */

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, type ReactNode } from "react";
import { cn } from "@/lib/utils/cn";
import type { ParsedRunFilters, TabValue } from "@/lib/run-filters.js";

interface AgentDetailShellProps {
  agentName: string;
  filters: ParsedRunFilters;
  children: ReactNode;
}

const TABS: { value: TabValue; label: string }[] = [
  { value: "runs", label: "Runs" },
  { value: "repos", label: "Repos" },
];

export function AgentDetailShell({ agentName, filters, children }: AgentDetailShellProps) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const handleTabChange = useCallback(
    (tab: TabValue) => {
      const params = new URLSearchParams(searchParams.toString());

      if (tab === "runs") {
        params.delete("tab");
      } else {
        params.set("tab", tab);
      }

      // Clear run panel when switching tabs
      params.delete("run");

      const qs = params.toString();
      router.replace(`/agents/${encodeURIComponent(agentName)}${qs ? `?${qs}` : ""}`);
    },
    [router, agentName, searchParams],
  );

  return (
    <div className="mt-4">
      <nav aria-label="Agent detail tabs" className="flex gap-1 border-b border-surface-border">
        {TABS.map((tab) => (
          <button
            key={tab.value}
            type="button"
            role="tab"
            aria-selected={filters.tab === tab.value}
            className={cn(
              "px-4 py-2 text-sm font-medium transition-colors",
              filters.tab === tab.value
                ? "border-b-2 border-brand-primary text-text-primary"
                : "text-text-muted hover:text-text-secondary",
            )}
            onClick={() => handleTabChange(tab.value)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      <div className="mt-4">{children}</div>
    </div>
  );
}
