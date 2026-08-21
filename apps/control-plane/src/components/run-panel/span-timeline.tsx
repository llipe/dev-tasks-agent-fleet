/**
 * SpanTimeline — S-021, sub-task 21.3.
 *
 * Renders per-call horizontal bars with latency and tokens.
 * Root span = full width, children offset/indented proportionally.
 * Each bar: span name, duration in ms, tokens if gen_ai span.
 * Bar width = (span duration / root duration) * 100%, min 2px.
 *
 * Handles loading, empty, error, timeout states independently.
 */

"use client";

import { use } from "react";
import { computeTimelineLayout, type TimelineBarData } from "@/lib/run-panel-utils.js";
import type { TimelineSpan } from "@/server/runs/span-to-run-mapper.js";
import type { ReadOutcome } from "@/server/repository/types.js";

export type SpanTimelineState =
  | { status: "loading" }
  | { status: "ok"; data: TimelineSpan[] }
  | { status: "empty" }
  | { status: "error"; error: string }
  | { status: "timeout" };

interface SpanTimelineProps {
  promise: Promise<ReadOutcome<TimelineSpan[]>>;
}

/**
 * SpanTimeline component — uses React `use()` to suspend on the data promise.
 * Wrapped in a Suspense boundary by the parent RunPanel.
 */
export function SpanTimeline({ promise }: SpanTimelineProps) {
  const outcome = use(promise);

  if (outcome.status === "empty") {
    return (
      <div className="rounded-md border border-surface-border p-4 text-center text-sm text-text-muted">
        No spans available for this run.
      </div>
    );
  }

  if (outcome.status === "error") {
    return (
      <div
        className="rounded-md border border-status-failed-bg p-4 text-sm text-status-failed-fg"
        role="alert"
      >
        Failed to load timeline: {outcome.error}
      </div>
    );
  }

  if (outcome.status === "timeout") {
    return (
      <div className="rounded-md border border-status-incomplete-bg p-4 text-sm text-status-incomplete-fg">
        Timeline query timed out. Try again later.
      </div>
    );
  }

  const layout = computeTimelineLayout(outcome.data);

  if (layout.length === 0) {
    return (
      <div className="rounded-md border border-surface-border p-4 text-center text-sm text-text-muted">
        No spans available for this run.
      </div>
    );
  }

  return (
    <div className="space-y-1" aria-label="Span timeline">
      {layout.map((bar, index) => (
        <TimelineBar key={`${bar.span.spanName}-${index}`} bar={bar} />
      ))}
    </div>
  );
}

function TimelineBar({ bar }: { bar: TimelineBarData }) {
  const { span, geometry, depth } = bar;
  const paddingLeft = depth * 16;

  const barStyle: React.CSSProperties = {
    width: geometry.needsMinWidth
      ? `max(${geometry.widthPercent}%, 2px)`
      : `${geometry.widthPercent}%`,
    marginLeft: `${geometry.leftPercent}%`,
  };

  const hasTokens = span.tokensIn > 0 || span.tokensOut > 0;

  return (
    <div className="flex items-center gap-2" style={{ paddingLeft }}>
      <div className="flex-1 min-w-0">
        {/* Bar container */}
        <div className="relative h-6 w-full rounded bg-surface-subtle">
          {/* Filled bar */}
          <div
            className={`absolute inset-y-0 rounded ${span.isRoot ? "bg-brand-secondary" : "bg-brand-secondary/60"}`}
            style={barStyle}
          />
        </div>
        {/* Label row */}
        <div className="mt-0.5 flex items-center gap-2 text-xs">
          <span className="truncate font-medium text-text-primary" title={span.spanName}>
            {span.spanName || "unnamed"}
          </span>
          <span className="tabular-nums text-text-secondary">{span.durationMs}ms</span>
          {hasTokens && (
            <span className="tabular-nums text-text-muted">
              {span.tokensIn.toLocaleString()}↑ {span.tokensOut.toLocaleString()}↓
            </span>
          )}
          {span.modelId && (
            <span className="truncate text-text-muted" title={span.modelId}>
              {span.modelId}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Loading fallback for the SpanTimeline Suspense boundary.
 */
export function SpanTimelineLoading() {
  return (
    <div className="space-y-2" aria-label="Loading timeline">
      {[1, 2, 3].map((i) => (
        <div key={i} className="h-6 animate-pulse rounded bg-surface-subtle" />
      ))}
    </div>
  );
}
