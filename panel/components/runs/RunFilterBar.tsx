"use client";

import type { CSSProperties } from "react";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import {
  serializeRunFilter,
  STATUS_FILTER_ORDER,
  type RunFilter,
  type RunFilterStatus,
} from "@/lib/domain/run-filter";
import type { RunStatusCounts } from "@/lib/supabase/queries";
import { StatusDot } from "@/components/StatusDot";
import { statusMeta } from "@/components/status-meta";
import { Input } from "@/components/Input";

import styles from "./RunFilterBar.module.css";

/** Search-input debounce, per spec §8.1 Technical Notes. */
const SEARCH_DEBOUNCE_MS = 300;

const STATUS_LABEL: Record<RunFilterStatus, string> = {
  queued: "queued",
  running: "running",
  succeeded: "succeeded",
  failed: "failed",
  timed_out: "timed out",
  failed_to_start: "failed to start",
  canceled: "canceled",
  all: "all",
};

export interface RunFilterBarRepositoryOption {
  id: string;
  fullName: string;
}

export interface RunFilterBarProps {
  /** The route this bar mutates via `router.replace` (e.g. `/agents/dependency-update` or `/runs`). */
  basePath: string;
  /** The server-derived filter this render reflects — the single source of truth (spec §8.1). */
  filter: RunFilter;
  /** Per-status counts for the current repo/search/agent scope, excluding the status dimension itself (FR1). */
  statusCounts: RunStatusCounts;
  /** Enabled, non-archived repositories (FR2; reuses `getEnabledRepositories` as-is, spec §8.1). */
  repositories: RunFilterBarRepositoryOption[];
}

/**
 * Run History filter bar (Story S-143, `/DESIGN.md` §5.2): status segmented
 * control (colored dot + live count), repository chips, a 300ms-debounced
 * free-text search, and a connection-state indicator.
 *
 * Filter state lives in the URL only (spec §8.1 Business Rule) — this
 * component never keeps a filter in `localStorage` or bare component state
 * beyond the transient, in-flight search input value. Every change calls
 * `router.replace` so the server component re-runs `parseRunFilter` +
 * `getFilteredRuns`/`getRunStatusCounts` against the new URL — there is no
 * client-side re-filtering of an already-loaded list.
 *
 * **Debounce race guard (test-plan gap, §5.3):** an immediate control (a
 * status/repo chip click, or "Clear filters") always cancels any pending
 * debounced search push AND folds the latest in-flight search value into its
 * own URL write, so a fast "type, then click a chip before the debounce
 * fires" sequence never lets a stale debounced write clobber the chip's
 * update.
 *
 * **Connection indicator (spec §8.1 v1.1 addendum):** this component only
 * ever mounts once the server component has already returned rows — a failed
 * server-side fetch throws to the Next.js error boundary before this
 * component exists. There is therefore exactly one reachable state, rendered
 * statically: "Connected".
 */
export function RunFilterBar({ basePath, filter, statusCounts, repositories }: RunFilterBarProps) {
  const router = useRouter();
  const [searchValue, setSearchValue] = useState(filter.search ?? "");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // The server round-trip may change `filter.search` (e.g. a "Clear filters"
  // navigation, or a back/forward nav) — keep the local input in sync.
  useEffect(() => {
    setSearchValue(filter.search ?? "");
  }, [filter.search]);

  function cancelPendingDebounce() {
    if (debounceRef.current != null) {
      clearTimeout(debounceRef.current);
      debounceRef.current = null;
    }
  }

  /** Cancels any pending debounce and navigates to the merged filter, resetting to page 1. */
  function pushFilter(next: Partial<RunFilter>) {
    cancelPendingDebounce();
    const trimmedSearch = searchValue.trim();
    const merged: RunFilter = {
      ...filter,
      page: 1,
      search: trimmedSearch === "" ? null : searchValue,
      ...next,
    };
    const qs = serializeRunFilter(merged).toString();
    router.replace(qs ? `${basePath}?${qs}` : basePath);
  }

  function onSearchChange(value: string) {
    setSearchValue(value);
    cancelPendingDebounce();
    debounceRef.current = setTimeout(() => {
      debounceRef.current = null;
      const merged: RunFilter = { ...filter, page: 1, search: value.trim() === "" ? null : value };
      const qs = serializeRunFilter(merged).toString();
      router.replace(qs ? `${basePath}?${qs}` : basePath);
    }, SEARCH_DEBOUNCE_MS);
  }

  const hasActiveFilter =
    filter.status !== "all" || filter.repositoryId != null || (filter.search ?? "") !== "";

  return (
    <div className={styles.bar} role="toolbar" aria-label="Run history filters">
      <div className={styles.segmented} role="group" aria-label="Filter by status">
        {STATUS_FILTER_ORDER.map((status) => {
          const active = filter.status === status;
          const count = statusCounts[status];
          const classes = [styles.statusOption, active && styles.statusOptionActive]
            .filter(Boolean)
            .join(" ");
          return (
            <button
              key={status}
              type="button"
              className={classes}
              aria-pressed={active}
              aria-label={`${STATUS_LABEL[status]} filter, ${count} runs`}
              onClick={() => pushFilter({ status })}
            >
              {status !== "all" && (
                <StatusDot status={status} size={6} decorative className={styles.statusOptionDot} />
              )}
              <span>{STATUS_LABEL[status]}</span>
              <span className={styles.statusOptionCount}>{count}</span>
            </button>
          );
        })}
      </div>

      {repositories.length > 0 && (
        <div className={styles.chips} role="group" aria-label="Filter by repository">
          <button
            type="button"
            className={[styles.chip, filter.repositoryId == null && styles.chipActive]
              .filter(Boolean)
              .join(" ")}
            aria-pressed={filter.repositoryId == null}
            onClick={() => pushFilter({ repositoryId: null })}
          >
            All repos
          </button>
          {repositories.map((repo) => {
            const active = filter.repositoryId === repo.id;
            return (
              <button
                key={repo.id}
                type="button"
                className={[styles.chip, active && styles.chipActive].filter(Boolean).join(" ")}
                aria-pressed={active}
                onClick={() => pushFilter({ repositoryId: repo.id })}
              >
                {repo.fullName}
              </button>
            );
          })}
        </div>
      )}

      <div className={styles.searchWrap}>
        <label htmlFor="run-history-search" className={styles.srOnly}>
          Search by repository, or run id
        </label>
        <Input
          id="run-history-search"
          inputSize="sm"
          type="search"
          placeholder="Search repository or run id…"
          value={searchValue}
          onChange={(e) => onSearchChange(e.target.value)}
          autoComplete="off"
          spellCheck={false}
        />
      </div>

      {hasActiveFilter && (
        <button
          type="button"
          className={styles.clearButton}
          onClick={() => pushFilter({ status: "all", repositoryId: null, search: null })}
        >
          Clear filters
        </button>
      )}

      <span className={styles.connection} role="status">
        <span
          className={styles.connectionDot}
          style={{ "--st-color": statusMeta("succeeded").colorVar } as CSSProperties}
          aria-hidden="true"
        />
        Connected
      </span>
    </div>
  );
}
