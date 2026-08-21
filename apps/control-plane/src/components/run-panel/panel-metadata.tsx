/**
 * Panel metadata section — S-021, sub-task 21.2.
 *
 * Displays run metadata immediately from row data (no async fetch):
 * - Agent name, Repository (subjectId)
 * - Session ID: monospace, truncated, copy button, full in title
 * - Status: StatusBadge
 * - Duration: human format
 * - Tokens: in/out
 * - Cost: CostEstimate
 * - Outcome: labelled link or dash
 */

"use client";

import { useCallback, useState } from "react";
import { StatusBadge, type Status } from "@/components/status-badge.js";
import { CostEstimate } from "@/components/cost-estimate.js";
import { truncateSessionId } from "@/lib/run-panel-utils.js";
import { formatDuration, formatTokens } from "@/lib/run-filters.js";
import type { MergedRun } from "@/server/runs/merge-runs.js";

interface PanelMetadataProps {
  run: MergedRun;
}

export function PanelMetadata({ run }: PanelMetadataProps) {
  const [copied, setCopied] = useState(false);

  const totalTokensIn = run.perModel.reduce((sum, m) => sum + m.tokensIn, 0);
  const totalTokensOut = run.perModel.reduce((sum, m) => sum + m.tokensOut, 0);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(run.sessionId);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Silently fail — clipboard may not be available
    }
  }, [run.sessionId]);

  return (
    <section aria-label="Run metadata" className="space-y-3 border-b border-surface-border pb-4">
      <div className="grid grid-cols-2 gap-3">
        {/* Agent */}
        <MetadataField label="Agent" value={run.agentName} />

        {/* Repository */}
        <MetadataField label="Repository" value={run.subjectId} />

        {/* Session ID */}
        <div className="col-span-2">
          <dt className="text-xs font-medium text-text-muted">Session ID</dt>
          <dd className="mt-0.5 flex items-center gap-2">
            <code className="font-mono text-sm text-text-primary" title={run.sessionId}>
              {truncateSessionId(run.sessionId)}
            </code>
            <button
              type="button"
              onClick={handleCopy}
              className="rounded px-1.5 py-0.5 text-xs text-text-secondary hover:bg-surface-hover focus:outline-none focus:ring-2 focus:ring-brand-secondary"
              title="Copy session ID"
              aria-label="Copy session ID"
            >
              {copied ? "Copied!" : "Copy"}
            </button>
          </dd>
        </div>

        {/* Status */}
        <div>
          <dt className="text-xs font-medium text-text-muted">Status</dt>
          <dd className="mt-0.5">
            <StatusBadge status={run.status as Status} />
          </dd>
        </div>

        {/* Duration */}
        <MetadataField label="Duration" value={formatDuration(run.durationMs)} numeric />

        {/* Tokens */}
        <MetadataField label="Tokens" value={formatTokens(totalTokensIn, totalTokensOut)} numeric />

        {/* Cost */}
        <div>
          <dt className="text-xs font-medium text-text-muted">Cost</dt>
          <dd className="mt-0.5">
            <CostEstimate usd={run.cost?.usd ?? null} complete={run.cost?.complete ?? false} />
          </dd>
        </div>

        {/* Outcome */}
        <div className="col-span-2">
          <dt className="text-xs font-medium text-text-muted">Outcome</dt>
          <dd className="mt-0.5">
            <OutcomeLink outcomeType={run.outcomeType} outcomeUrl={run.outcomeUrl} />
          </dd>
        </div>
      </div>
    </section>
  );
}

function MetadataField({
  label,
  value,
  numeric,
}: {
  label: string;
  value: string;
  numeric?: boolean;
}) {
  return (
    <div>
      <dt className="text-xs font-medium text-text-muted">{label}</dt>
      <dd className={`mt-0.5 text-sm text-text-primary ${numeric ? "tabular-nums" : ""}`}>
        {value || "—"}
      </dd>
    </div>
  );
}

function OutcomeLink({ outcomeType, outcomeUrl }: { outcomeType: string; outcomeUrl: string }) {
  if (!outcomeType || outcomeType === "none" || outcomeType === "") {
    return <span className="text-sm text-text-muted">—</span>;
  }

  const label = outcomeType.charAt(0).toUpperCase() + outcomeType.slice(1);

  if (outcomeUrl) {
    return (
      <a
        href={outcomeUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="text-sm text-brand-secondary underline hover:text-brand-primary"
      >
        {label}
      </a>
    );
  }

  return <span className="text-sm text-text-primary">{label}</span>;
}
