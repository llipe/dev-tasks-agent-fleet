import Link from "next/link";

import type { RunRow } from "@/lib/domain/run-row";
import { isSafeArtifactUrl } from "@/lib/domain/artifact-url";
import { StatusPill } from "@/components/StatusPill";
import { Tag } from "@/components/Tag";
import { RowChevronIcon } from "@/components/icons";

import styles from "./RunHistoryTable.module.css";

/**
 * One run-history table row (`/DESIGN.md` §5.2), rendered as a semantic
 * `<tr>` so screen-reader table navigation works (spec §10). Six data columns
 * plus a chevron: status pill, outcome tag, repository (+ branch + PR link),
 * duration, step progress `n/m`, relative start.
 *
 * Every status is the pre-derived `effective_status` from the row shaper — this
 * component never sees a raw `runs.status`. A pending/absent outcome renders as
 * `—` at reduced opacity (§8.2). A run with no repository renders a clean `—`,
 * never `null/null`.
 *
 * **Inline PR link (Story S-144, issue 204):** when `row.pullRequestUrl` is
 * present, the repository cell renders a small "PR" link inline — no need to
 * open the row to check it. `row.pullRequestUrl` is agent-written, untrusted
 * input (spec §12, A10), so it is linked ONLY through the existing
 * `isSafeArtifactUrl` guard (S-109) — reused, never duplicated. A `null`
 * value (no `pull_request` artifact) renders the branch-only markup exactly
 * as before this story (AC2). A present-but-unsafe URL renders inert text,
 * matching Run Detail's `ArtifactLinks` behavior, never a link (AC4).
 *
 * The whole row links to the run detail (`/runs/[id]`, S-109); that target may
 * 404 until S-109 lands (task 3.8). That link lives in its own chevron cell
 * (not a stretched row-wide overlay), so the new inline PR anchor in the
 * repository cell is an independent, ordinarily-clickable link — no z-index
 * or overlay conflict to resolve.
 */
export interface RunHistoryRowProps {
  row: RunRow;
  /**
   * Renders a leading Agent cell (name + slug), Story S-146. Defaults `false`
   * so `/agents/[slug]` renders exactly as before this story.
   */
  showAgentColumn?: boolean;
}

export function RunHistoryRow({ row, showAgentColumn = false }: RunHistoryRowProps) {
  const rowClass = showAgentColumn ? `${styles.row} ${styles.rowAgent}` : styles.row;
  return (
    <tr className={rowClass}>
      {showAgentColumn && (
        <td className={styles.cell}>
          {row.agentName != null || row.agentSlug != null ? (
            <span className={styles.agent}>
              <span className={styles.agentName}>{row.agentName ?? "—"}</span>
              {row.agentSlug != null && <span className={styles.agentSlug}>{row.agentSlug}</span>}
            </span>
          ) : (
            <span className={styles.pending}>—</span>
          )}
        </td>
      )}
      <td className={styles.cell}>
        <StatusPill status={row.effectiveStatus} />
      </td>
      <td className={styles.cell}>
        {row.hasOutcome ? (
          <Tag variant="outline" size="sm">
            {row.outcomeLabel}
          </Tag>
        ) : (
          <span className={styles.pending} aria-label="no outcome yet">
            {row.outcomeLabel}
          </span>
        )}
      </td>
      <td className={`${styles.cell} ${styles.repoCell}`}>
        {row.hasRepository ? (
          <span className={styles.repo}>
            <span className={styles.repoName}>{row.repositoryFullName}</span>
            {row.repositoryBranch != null && (
              <span className={styles.repoBranch}>{row.repositoryBranch}</span>
            )}
            <PullRequestLink url={row.pullRequestUrl} />
          </span>
        ) : (
          <span className={styles.pending}>—</span>
        )}
      </td>
      <td className={`${styles.cell} ${styles.mono}`}>{row.duration}</td>
      <td className={`${styles.cell} ${styles.mono}`}>{row.steps}</td>
      <td className={`${styles.cell} ${styles.mono} ${styles.startedCell}`}>
        {row.startedRelative}
      </td>
      <td className={`${styles.cell} ${styles.chevronCell}`}>
        <Link
          href={`/runs/${row.id}`}
          className={styles.rowLink}
          aria-label={`Open run ${row.shortId}`}
        >
          <RowChevronIcon size={14} />
        </Link>
      </td>
    </tr>
  );
}

/**
 * The inline PR link/inert fragment for the repository cell (Story S-144).
 *
 * `url` is `row.pullRequestUrl` — raw, agent-written, untrusted input.
 * `null` (no `pull_request` artifact) renders nothing at all, leaving the
 * branch-only markup unchanged (AC2). A present URL is linked ONLY when
 * `isSafeArtifactUrl` accepts it (well-formed `https:`, S-109's existing
 * guard, reused not duplicated); every other shape renders inert text, the
 * same pattern `ArtifactLinks` (Run Detail) already uses (AC4).
 */
function PullRequestLink({ url }: { url: string | null }) {
  if (url == null) return null;

  if (isSafeArtifactUrl(url)) {
    return (
      <a
        className={styles.repoPr}
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        onClick={(e) => e.stopPropagation()}
      >
        PR
      </a>
    );
  }

  // Unsafe or malformed URL — inert text, never a link (guard #5).
  return (
    <span className={styles.repoPrInert} title="No linkable URL">
      PR
    </span>
  );
}
