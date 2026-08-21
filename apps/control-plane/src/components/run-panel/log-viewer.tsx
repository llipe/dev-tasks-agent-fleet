/**
 * LogViewer — S-021, sub-task 21.4.
 *
 * Displays FilterLogEvents output by session_id.
 * Monospace text, scrollable container (max-h with overflow-y-auto).
 * Each line: timestamp + message.
 * For `incomplete` runs: logs just stop (no error indicator).
 *
 * Handles loading, empty, error, timeout states independently.
 */

"use client";

import { use } from "react";
import { parseLogLines, type ParsedLogLine } from "@/lib/run-panel-utils.js";
import type { ReadOutcome } from "@/server/repository/types.js";

interface LogViewerProps {
  promise: Promise<ReadOutcome<string[]>>;
  isIncomplete?: boolean;
}

/**
 * LogViewer component — uses React `use()` to suspend on the data promise.
 * Wrapped in a Suspense boundary by the parent RunPanel.
 */
export function LogViewer({ promise }: LogViewerProps) {
  const outcome = use(promise);

  if (outcome.status === "empty") {
    return (
      <div className="rounded-md border border-surface-border p-4 text-center text-sm text-text-muted">
        No logs available for this session.
      </div>
    );
  }

  if (outcome.status === "error") {
    return (
      <div
        className="rounded-md border border-status-failed-bg p-4 text-sm text-status-failed-fg"
        role="alert"
      >
        Failed to load logs: {outcome.error}
      </div>
    );
  }

  if (outcome.status === "timeout") {
    return (
      <div className="rounded-md border border-status-incomplete-bg p-4 text-sm text-status-incomplete-fg">
        Log query timed out. Try again later.
      </div>
    );
  }

  const lines = parseLogLines(outcome.data);

  return (
    <div
      className="max-h-80 overflow-y-auto rounded-md border border-surface-border bg-surface-subtle p-3 font-mono text-xs"
      role="log"
      aria-label="Run logs"
    >
      {lines.map((line, index) => (
        <LogLine key={index} line={line} />
      ))}
    </div>
  );
}

function LogLine({ line }: { line: ParsedLogLine }) {
  if (!line.message && !line.timestamp) return null;

  return (
    <div className="whitespace-pre-wrap break-all py-0.5 leading-5">
      {line.timestamp && <span className="text-text-muted">{line.timestamp} </span>}
      <span className="text-text-primary">{line.message}</span>
    </div>
  );
}

/**
 * Loading fallback for the LogViewer Suspense boundary.
 */
export function LogViewerLoading() {
  return (
    <div
      className="space-y-1 rounded-md border border-surface-border p-3"
      aria-label="Loading logs"
    >
      {[1, 2, 3, 4, 5].map((i) => (
        <div key={i} className="h-4 animate-pulse rounded bg-surface-subtle" />
      ))}
    </div>
  );
}
