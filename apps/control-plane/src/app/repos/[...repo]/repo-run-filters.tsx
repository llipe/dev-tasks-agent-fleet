"use client";

/**
 * Repo run filter controls — S-023.
 *
 * Client component for status dropdown and date range presets.
 * Identical logic to RunFilters from S-020 but with repo-specific URL path.
 */

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";
import type { ParsedRunFilters } from "@/lib/run-filters.js";
import { cn } from "@/lib/utils/cn";

interface RepoRunFiltersProps {
  repoId: string;
  filters: ParsedRunFilters;
}

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "All statuses" },
  { value: "running", label: "Running" },
  { value: "success", label: "Success" },
  { value: "failed", label: "Failed" },
  { value: "incomplete", label: "Incomplete" },
];

const RANGE_PRESETS: { label: string; days: number }[] = [
  { label: "24h", days: 1 },
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
];

export function RepoRunFilters({ repoId, filters }: RepoRunFiltersProps) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const updateFilters = useCallback(
    (updates: Partial<{ status: string; from: string; to: string }>) => {
      const params = new URLSearchParams(searchParams.toString());

      if (updates.status !== undefined) {
        if (updates.status === "") {
          params.delete("status");
        } else {
          params.set("status", updates.status);
        }
      }

      if (updates.from !== undefined) {
        params.set("from", updates.from);
      }

      if (updates.to !== undefined) {
        params.set("to", updates.to);
      }

      const qs = params.toString();
      router.replace(`/repos/${encodeURIComponent(repoId)}${qs ? `?${qs}` : ""}`);
    },
    [router, repoId, searchParams],
  );

  const handleStatusChange = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      updateFilters({ status: e.target.value });
    },
    [updateFilters],
  );

  const handleRangePreset = useCallback(
    (days: number) => {
      const now = new Date();
      const from = new Date(now.getTime() - days * 24 * 60 * 60 * 1000);
      updateFilters({ from: from.toISOString(), to: now.toISOString() });
    },
    [updateFilters],
  );

  const activePresetDays = getActivePresetDays(filters);

  return (
    <div className="flex flex-wrap items-center gap-3">
      {/* Status filter */}
      <label className="flex items-center gap-2 text-sm text-text-secondary">
        <span className="sr-only">Filter by status</span>
        <select
          value={filters.status ?? ""}
          onChange={handleStatusChange}
          className="rounded-md border border-surface-border bg-surface-primary px-3 py-1.5 text-sm text-text-primary focus:border-brand-secondary focus:outline-none focus:ring-1 focus:ring-brand-secondary"
          aria-label="Filter by status"
        >
          {STATUS_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </label>

      {/* Range presets */}
      <div className="flex items-center gap-1" role="group" aria-label="Date range presets">
        {RANGE_PRESETS.map((preset) => (
          <button
            key={preset.label}
            type="button"
            className={cn(
              "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              activePresetDays === preset.days
                ? "bg-brand-primary text-white"
                : "bg-surface-hover text-text-secondary hover:bg-surface-border",
            )}
            onClick={() => handleRangePreset(preset.days)}
            aria-pressed={activePresetDays === preset.days}
          >
            {preset.label}
          </button>
        ))}
      </div>

      {/* Custom from/to inputs */}
      <div className="flex items-center gap-2 text-sm">
        <label className="flex items-center gap-1 text-text-secondary">
          From
          <input
            type="date"
            value={toDateInputValue(filters.from)}
            onChange={(e) => {
              if (e.target.value) {
                updateFilters({ from: new Date(e.target.value).toISOString() });
              }
            }}
            className="rounded-md border border-surface-border bg-surface-primary px-2 py-1 text-sm text-text-primary focus:border-brand-secondary focus:outline-none focus:ring-1 focus:ring-brand-secondary"
            aria-label="From date"
          />
        </label>
        <label className="flex items-center gap-1 text-text-secondary">
          To
          <input
            type="date"
            value={toDateInputValue(filters.to)}
            onChange={(e) => {
              if (e.target.value) {
                updateFilters({ to: new Date(e.target.value).toISOString() });
              }
            }}
            className="rounded-md border border-surface-border bg-surface-primary px-2 py-1 text-sm text-text-primary focus:border-brand-secondary focus:outline-none focus:ring-1 focus:ring-brand-secondary"
            aria-label="To date"
          />
        </label>
      </div>
    </div>
  );
}

/** Format a Date to yyyy-mm-dd for <input type="date"> */
function toDateInputValue(date: Date): string {
  return date.toISOString().split("T")[0] ?? "";
}

/** Determine which preset is active based on current filter range */
function getActivePresetDays(filters: ParsedRunFilters): number | null {
  const rangeMs = filters.to.getTime() - filters.from.getTime();
  const rangeDays = Math.round(rangeMs / (24 * 60 * 60 * 1000));

  for (const preset of RANGE_PRESETS) {
    if (Math.abs(rangeDays - preset.days) <= 0) {
      return preset.days;
    }
  }
  return null;
}
