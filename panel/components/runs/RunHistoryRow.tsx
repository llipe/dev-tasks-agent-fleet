import Link from "next/link";

import type { RunRow } from "@/lib/domain/run-row";
import { StatusPill } from "@/components/StatusPill";
import { Tag } from "@/components/Tag";
import { RowChevronIcon } from "@/components/icons";

import styles from "./RunHistoryTable.module.css";

/**
 * One run-history table row (`/DESIGN.md` §5.2), rendered as a semantic
 * `<tr>` so screen-reader table navigation works (spec §10). Six data columns
 * plus a chevron: status pill, outcome tag, repository (+ branch), duration,
 * step progress `n/m`, relative start.
 *
 * Every status is the pre-derived `effective_status` from the row shaper — this
 * component never sees a raw `runs.status`. A pending/absent outcome renders as
 * `—` at reduced opacity (§8.2). A run with no repository renders a clean `—`,
 * never `null/null`.
 *
 * The whole row links to the run detail (`/runs/[id]`, S-109); that target may
 * 404 until S-109 lands (task 3.8). The link is a single anchor spanning the
 * row via a stretched overlay so keyboard focus lands once per row.
 */
export interface RunHistoryRowProps {
  row: RunRow;
}

export function RunHistoryRow({ row }: RunHistoryRowProps) {
  return (
    <tr className={styles.row}>
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
