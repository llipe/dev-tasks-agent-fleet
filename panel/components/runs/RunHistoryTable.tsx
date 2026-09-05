import Link from "next/link";

import type { RunRow } from "@/lib/domain/run-row";
import { KLabel } from "@/components/KLabel";
import { Button } from "@/components/Button";

import { RunHistoryRow } from "./RunHistoryRow";
import styles from "./RunHistoryTable.module.css";

/**
 * Run-history table (`/DESIGN.md` §4.4 grid, §5.2 columns).
 *
 * **Semantic `<table>` markup** — not a div grid — so assistive tech can
 * navigate it as a table (spec §10). The `/DESIGN.md` §4.4 column widths
 * (`118px 122px minmax(0,1fr) 96px 78px 104px 30px`) are applied to the header
 * and body rows via CSS grid on the `<tr>`, so the table reads semantically
 * while laying out on the documented grid.
 *
 * The toolbar (filters, repo chips, search, pagination) is deferred to v3
 * (PRD §10); this renders the header + rows only, never dead controls.
 *
 * An empty run list renders a legible "no runs yet" state with an invoke CTA
 * (task 3.8), never a blank region.
 */
export interface RunHistoryTableProps {
  rows: RunRow[];
  /** Invoke route target for the empty-state CTA, or null while unbuilt (S-113). */
  invokeHref: string | null;
}

export function RunHistoryTable({ rows, invokeHref }: RunHistoryTableProps) {
  if (rows.length === 0) {
    return (
      <div className={styles.empty} role="status">
        <KLabel>No runs yet</KLabel>
        <p className={styles.emptyBody}>
          This agent has never been invoked. Invoke it once against a single repository to check the
          parameter schema resolves.
        </p>
        <div className={styles.emptyActions}>
          {invokeHref != null ? (
            <Link href={invokeHref} className={styles.invokeLink}>
              <Button variant="primary" size="sm">
                Invoke on one repo
              </Button>
            </Link>
          ) : (
            <Button variant="primary" size="sm" disabled aria-disabled="true">
              Invoke on one repo
            </Button>
          )}
        </div>
      </div>
    );
  }

  return (
    <table className={styles.table} aria-label="Run history">
      <thead>
        <tr className={`${styles.row} ${styles.headRow}`}>
          <th scope="col" className={styles.headCell}>
            Status
          </th>
          <th scope="col" className={styles.headCell}>
            Outcome
          </th>
          <th scope="col" className={styles.headCell}>
            Repository
          </th>
          <th scope="col" className={styles.headCell}>
            Duration
          </th>
          <th scope="col" className={styles.headCell}>
            Steps
          </th>
          <th scope="col" className={`${styles.headCell} ${styles.startedCell}`}>
            Started
          </th>
          <th scope="col" className={styles.headCell}>
            <span className={styles.srOnly}>Open</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <RunHistoryRow key={row.id} row={row} />
        ))}
      </tbody>
    </table>
  );
}
