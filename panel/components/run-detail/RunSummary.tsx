import type { RunSummaryView } from "@/lib/domain/run-detail";
import { StatusPill } from "@/components/StatusPill";
import { Tag } from "@/components/Tag";
import { KLabel } from "@/components/KLabel";

import { ArtifactLinks, type ArtifactView } from "./ArtifactLinks";
import styles from "./RunSummary.module.css";

/**
 * RunSummary — /DESIGN.md §4.2 / §5.3. The summary panel of the run-detail
 * screen: status pill (from the derived `effective_status`), outcome tag, run
 * ID (short uppercase mono), repository, and the metadata grid (queued /
 * started / finished / duration / branch), plus the artifact pill links.
 *
 * Artifacts render here on EVERY status, including `failed` (AC14) — the pills
 * come from `ArtifactLinks`, which is given artifacts, not status.
 *
 * Presentational and server-safe. The status comes pre-derived from
 * `buildSummary`; this component never re-derives it.
 */
export interface RunSummaryProps {
  summary: RunSummaryView;
  artifacts: ArtifactView[];
}

export function RunSummary({ summary, artifacts }: RunSummaryProps) {
  return (
    <section className={styles.summary} aria-label="Run summary">
      <div className={styles.headline}>
        <StatusPill status={summary.effectiveStatus} />
        {summary.hasOutcome ? (
          <Tag variant="outline" size="sm">
            {summary.outcomeLabel}
          </Tag>
        ) : (
          <span className={styles.pending} aria-label="no outcome yet">
            {summary.outcomeLabel}
          </span>
        )}
        <span className={styles.runId}>{summary.shortId}</span>
        {summary.hasRepository && <span className={styles.repo}>{summary.repositoryFullName}</span>}
      </div>

      <dl className={styles.metaGrid}>
        <Meta label="Queued" value={summary.queuedClock} mono />
        <Meta label="Started" value={summary.startedClock} mono />
        <Meta label="Finished" value={summary.finishedClock} mono />
        <Meta label="Duration" value={summary.duration} mono />
        <Meta label="Branch" value={summary.branch ?? "—"} mono />
      </dl>

      {artifacts.length > 0 && (
        <div className={styles.artifacts}>
          <KLabel>Artifacts</KLabel>
          <ArtifactLinks artifacts={artifacts} />
        </div>
      )}
    </section>
  );
}

function Meta({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className={styles.meta}>
      <dt className={styles.metaLabel}>{label}</dt>
      <dd className={[styles.metaValue, mono && styles.mono].filter(Boolean).join(" ")}>{value}</dd>
    </div>
  );
}
