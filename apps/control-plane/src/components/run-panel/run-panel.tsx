/**
 * RunPanel — S-021, sub-task 21.1.
 *
 * Side sheet from right (~w-[32rem]) overlaying table content.
 * Opens when `?run=<session_id>` is in URL. Removing param closes it.
 *
 * Features:
 * - Backdrop for click-to-dismiss
 * - Escape key dismissal
 * - Focus trap (tab cycles within panel)
 * - Focus restoration on close
 * - Browser back closes the panel (removing ?run= param)
 * - Each async section in its own Suspense boundary
 * - 'use client' — uses state, effects, event handlers
 */

"use client";

import { useCallback, useEffect, useRef, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { PanelMetadata } from "./panel-metadata.js";
import { SpanTimeline, SpanTimelineLoading } from "./span-timeline.js";
import { LogViewer, LogViewerLoading } from "./log-viewer.js";
import type { MergedRun } from "@/server/runs/merge-runs.js";
import type { TimelineSpan } from "@/server/runs/span-to-run-mapper.js";
import type { ReadOutcome } from "@/server/repository/types.js";

interface RunPanelProps {
  /** The run data (from the row) for immediate metadata rendering */
  run: MergedRun;
  /** Agent name for URL construction */
  agentName: string;
  /** Promise for trace spans (loaded async) */
  tracePromise: Promise<ReadOutcome<TimelineSpan[]>>;
  /** Promise for log lines (loaded async) */
  logsPromise: Promise<ReadOutcome<string[]>>;
}

export function RunPanel({ run, agentName, tracePromise, logsPromise }: RunPanelProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const panelRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<Element | null>(null);

  // Store the element that had focus before opening
  useEffect(() => {
    previousFocusRef.current = document.activeElement;

    // Focus the panel on mount
    const timer = setTimeout(() => {
      panelRef.current?.focus();
    }, 0);

    return () => {
      clearTimeout(timer);
      // Restore focus on unmount
      if (previousFocusRef.current instanceof HTMLElement) {
        previousFocusRef.current.focus();
      }
    };
  }, []);

  // Close panel by removing the `run` param from URL
  const closePanel = useCallback(() => {
    const params = new URLSearchParams(searchParams.toString());
    params.delete("run");
    const query = params.toString();
    const url = `/agents/${encodeURIComponent(agentName)}${query ? `?${query}` : ""}`;
    router.replace(url);
  }, [router, agentName, searchParams]);

  // Escape key handler
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        closePanel();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [closePanel]);

  // Browser popstate (back button) handler
  useEffect(() => {
    const handlePopState = () => {
      const params = new URLSearchParams(window.location.search);
      if (!params.has("run")) {
        // Panel should close — the URL no longer has the run param
        // This is handled by the parent re-render when searchParams change
      }
    };

    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  // Focus trap: keep Tab cycling within the panel
  useEffect(() => {
    const panel = panelRef.current;
    if (!panel) return;

    const handleTab = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;

      const focusable = panel.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])',
      );
      if (focusable.length === 0) return;

      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    };

    panel.addEventListener("keydown", handleTab);
    return () => panel.removeEventListener("keydown", handleTab);
  }, []);

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/30"
        onClick={closePanel}
        aria-hidden="true"
        data-testid="run-panel-backdrop"
      />

      {/* Panel */}
      <aside
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={`Run details: ${run.sessionId}`}
        tabIndex={-1}
        className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[32rem] flex-col overflow-y-auto bg-surface-primary shadow-xl focus:outline-none"
        data-testid="run-panel"
      >
        {/* Header with close button */}
        <header className="flex items-center justify-between border-b border-surface-border p-4">
          <h2 className="text-lg font-semibold text-text-primary">Run Details</h2>
          <button
            type="button"
            onClick={closePanel}
            className="rounded p-1 text-text-secondary hover:bg-surface-hover focus:outline-none focus:ring-2 focus:ring-brand-secondary"
            aria-label="Close panel"
            data-testid="run-panel-close"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-5 w-5"
              viewBox="0 0 20 20"
              fill="currentColor"
              aria-hidden="true"
            >
              <path
                fillRule="evenodd"
                d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z"
                clipRule="evenodd"
              />
            </svg>
          </button>
        </header>

        {/* Content */}
        <div className="flex-1 space-y-6 p-4">
          {/* Metadata — renders immediately from row data */}
          <PanelMetadata run={run} />

          {/* Span Timeline — async with its own Suspense */}
          <section aria-label="Span timeline">
            <h3 className="mb-2 text-sm font-semibold text-text-primary">Timeline</h3>
            <Suspense fallback={<SpanTimelineLoading />}>
              <SpanTimeline promise={tracePromise} />
            </Suspense>
          </section>

          {/* Log Viewer — async with its own Suspense */}
          <section aria-label="Run logs">
            <h3 className="mb-2 text-sm font-semibold text-text-primary">Logs</h3>
            <Suspense fallback={<LogViewerLoading />}>
              <LogViewer promise={logsPromise} isIncomplete={run.status === "incomplete"} />
            </Suspense>
          </section>
        </div>
      </aside>
    </>
  );
}
