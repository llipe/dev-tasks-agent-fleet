"use client";

import { useActionState, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/Button";
import { KLabel } from "@/components/KLabel";
import { Tag } from "@/components/Tag";
import {
  archiveRepository,
  type ArchiveRepositoryResult,
} from "@/app/(panel)/repositories/actions";
import type { RepositoryRow } from "@/lib/supabase/types";

import styles from "./RepositoryTable.module.css";

/**
 * The Repositories list (Story S-147, spec §10, DESIGN.md §5.6 — first-pass
 * layout, see the stub note there), extended by Story S-148 (issue 208, spec §8.4)
 * with an "Archive" action + confirm dialog.
 *
 * Reuses `RunHistoryTable`'s semantic `<table>`-on-CSS-grid pattern
 * (accessible to assistive tech, not a div grid).
 *
 * Presentational for the LIST: it renders exactly the rows it is given.
 * `page.tsx` (the server component) is responsible for excluding archived
 * rows by default via `getRepositories(client)` — this component does not
 * duplicate that filtering decision.
 *
 * The Archive action IS this component's own concern (S-148): clicking
 * "Archive" opens a confirm dialog (the panel's FIRST destructive-action
 * confirm dialog — no other screen has one, so this is a simple, minimal,
 * accessible `role="dialog"`/`aria-modal="true"` overlay, not a reusable
 * dialog primitive). Confirming submits the `archiveRepository` Server
 * Action; on success the dialog closes and `router.refresh()` re-runs the
 * server component's `getRepositories(client)` read, so the archived row
 * disappears from the default (non-archived) list on the next render — no
 * client-side row removal is done here, matching `AddRepositoryForm`'s
 * existing "server re-fetch is the source of truth" posture. A server-
 * returned failure keeps the dialog open with an inline `role="alert"`
 * error, never a silent failure.
 *
 * No "restore" affordance exists anywhere in this component (AC6 — the
 * confirmed, accepted v1 limitation; reversal requires a direct DB action).
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
          <th scope="col" className={styles.headCell}>
            Actions
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
            <td className={styles.cell}>
              <ArchiveAction row={row} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * Per-row Archive button + confirm dialog + `archiveRepository` submit.
 * Isolated to its own component so each row owns an independent
 * `useActionState` instance (one row's pending/error state never bleeds
 * into another row's).
 */
function ArchiveAction({ row }: { row: RepositoryRow }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [state, formAction, pending] = useActionState<ArchiveRepositoryResult | null, FormData>(
    archiveRepository,
    null,
  );
  const seen = useRef<ArchiveRepositoryResult | null>(null);

  useEffect(() => {
    if (state && state !== seen.current) {
      seen.current = state;
      if (state.ok) {
        setOpen(false);
        router.refresh();
      }
    }
  }, [state, router]);

  const error = state && !state.ok ? state.message : null;

  return (
    <>
      <Button type="button" variant="ghost" size="sm" onClick={() => setOpen(true)}>
        Archive
      </Button>

      {open && (
        <div className={styles.overlay}>
          <div
            className={styles.dialog}
            role="dialog"
            aria-modal="true"
            aria-label="Archive repository"
          >
            <p className={styles.dialogBody}>
              Archive <strong>{row.full_name}</strong>? It will stop appearing as an invocation
              target. Existing runs against it keep their history and repository name unchanged.
              This cannot be undone from the UI.
            </p>

            {error && (
              <div className={styles.alert} role="alert">
                {error}
              </div>
            )}

            <div className={styles.dialogActions}>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => setOpen(false)}
                disabled={pending}
              >
                Cancel
              </Button>
              <form action={formAction}>
                <input type="hidden" name="id" value={row.id} />
                <Button
                  type="submit"
                  variant="primary"
                  size="sm"
                  disabled={pending}
                  aria-disabled={pending}
                >
                  {pending ? "Archiving…" : "Confirm"}
                </Button>
              </form>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
