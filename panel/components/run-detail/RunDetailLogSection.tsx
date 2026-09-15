"use client";

import { useState } from "react";

import type { StepPanelRow } from "@/lib/domain/run-detail";
import type { LogFilterState } from "@/lib/domain/log-filter";
import type { LogLevel } from "@/lib/supabase/types";

import { StepsPanel } from "./StepsPanel";
import { LogViewer, type LogViewerProps } from "./LogViewer";
import { LiveLogViewer, type LiveLogViewerProps } from "./LiveLogViewer";
import styles from "./RunDetailLogSection.module.css";

/**
 * RunDetailLogSection — /DESIGN.md §4.2/§5.3 (Story S-145).
 *
 * The `"use client"` filter-state wrapper spec §8.2 calls for: it owns
 * `{ stepId, level }` and is the single source of truth both the steps panel
 * (FR9/FR10) and the level-filter control (FR11) write to. It renders exactly
 * ONE of the two log viewers — the terminal `LogViewer` (S-109) or the live
 * `LiveLogViewer` (S-110) — chosen by the page via `isLive` (the same
 * `effectiveStatus`-derived decision `page.tsx` already makes), and passes the
 * shared `filter` down to whichever one mounts. Neither viewer's own
 * pagination/live-tail state is touched by the filter — only what they RENDER
 * narrows (`applyLogFilter`, called inside each viewer).
 */
export interface RunDetailLogSectionProps {
  steps: StepPanelRow[];
  isLive: boolean;
  /** Required when `isLive` is false. */
  logViewerProps?: Omit<LogViewerProps, "filter">;
  /** Required when `isLive` is true. */
  liveLogViewerProps?: Omit<LiveLogViewerProps, "filter">;
}

const LEVEL_OPTIONS: { value: LogFilterState["level"]; label: string }[] = [
  { value: "all", label: "All levels" },
  { value: "debug", label: "Debug and above" },
  { value: "info", label: "Info and above" },
  { value: "warn", label: "Warnings and above" },
  { value: "error", label: "Errors only" },
];

export function RunDetailLogSection({
  steps,
  isLive,
  logViewerProps,
  liveLogViewerProps,
}: RunDetailLogSectionProps) {
  const [stepId, setStepId] = useState<string | null>(null);
  const [level, setLevel] = useState<LogLevel | "all">("all");
  const filter: LogFilterState = { stepId, level };

  return (
    <div className={styles.section}>
      <StepsPanel steps={steps} selectedStepId={stepId} onSelectStep={setStepId} />

      <div className={styles.viewerColumn}>
        <div className={styles.toolbar}>
          <label className={styles.levelLabel} htmlFor="log-level-filter">
            Log level
          </label>
          <select
            id="log-level-filter"
            className={styles.levelSelect}
            value={level}
            onChange={(e) => setLevel(e.target.value as LogLevel | "all")}
          >
            {LEVEL_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        {isLive
          ? liveLogViewerProps && <LiveLogViewer {...liveLogViewerProps} filter={filter} />
          : logViewerProps && <LogViewer {...logViewerProps} filter={filter} />}
      </div>
    </div>
  );
}
