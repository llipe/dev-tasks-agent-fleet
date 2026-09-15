import { KLabel } from "@/components/KLabel";
import { Tag } from "@/components/Tag";
import type { RepositoryRow } from "@/lib/supabase/types";

import styles from "./RepositoryTable.module.css";

/**
 * The Repositories list (Story S-147, spec §10, DESIGN.md §5.6 — first-pass
 * layout, see the stub note there). Reuses `RunHistoryTable`'s semantic
 * `<table>`-on-CSS-grid pattern (accessible to assistive tech, not a div
 * grid).
 *
 * Presentational only: it renders exactly the rows it is given. `page.tsx`
 * (the server component) is responsible for excluding archived rows by
 * default via `getRepositories(client)` — this component does not duplicate
 * that filtering decision.
 *
 * No Archive action in this story (S-148 scope, not yet built) — the props
 * surface is intentionally minimal (`rows` only) so a future extension adds a
 * prop rather than this component growing an unused affordance now.
 */
export interface RepositoryTableProps {
  rows: RepositoryRow[];
}

export function RepositoryTable({ rows }: RepositoryTableProps) {
  if (rows.length === 0) {
    return (
      <div className={styles.empty} role="status">
        <KLabel>No repositories yet</KLabel>
        <p className={styles.emptyBody}>
          Add a repository by reference below to make it available for agent invocation.
        </p>
      </div>
    );
  }

  return (
    <table className={styles.table} aria-label="Repositories">
      <thead>
        <tr className={`${styles.row} ${styles.headRow}`}>
          <th scope="col" className={styles.headCell}>
            Repository
          </th>
          <th scope="col" className={styles.headCell}>
            Default branch
          </th>
          <th scope="col" className={styles.headCell}>
            State
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.id} className={styles.row}>
            <td className={`${styles.cell} ${styles.fullName}`}>{row.full_name}</td>
            <td className={`${styles.cell} ${styles.branch}`}>{row.default_branch}</td>
            <td className={styles.cell}>
              <Tag variant={row.is_enabled ? "accent" : "neutral"} size="sm">
                {row.is_enabled ? "Enabled" : "Disabled"}
              </Tag>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
