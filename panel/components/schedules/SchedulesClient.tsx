"use client";

import { useCallback, useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/Button";
import { KLabel } from "@/components/KLabel";
import { NewScheduleIcon } from "@/components/icons";
import { buildScheduleCellModel } from "@/lib/domain/schedule-row";
import { formatRelative } from "@/lib/format";
import type { VScheduleRow } from "@/lib/supabase/types";
import {
  clearPrBlockAction,
  deleteScheduleAction,
  pauseScheduleAction,
  resumeScheduleAction,
} from "@/app/(panel)/schedules/actions";

import { SchedulesTable, type ScheduleTableRow } from "./SchedulesTable";
import { ScheduleDialog, type AgentOption, type RepositoryOption } from "./ScheduleDialog";
import styles from "./SchedulesTable.module.css";

/**
 * S-161/S-162 (issues 273/274) — the client controller for `/schedules` (DESIGN.md
 * §5.7). Shapes the server-read `v_schedules` rows into table cell models
 * (`buildScheduleCellModel`, clock taken once at mount), owns the New/Edit
 * dialog and the delete `alertdialog`, and wires the pause/resume/delete/clear
 * Server Actions. Every mutation calls `router.refresh()` so the server
 * re-reads the list (server-refetch-is-truth, §5.6) — no optimistic row edits.
 *
 * The create/edit flash (a transient accent left inset) is applied to the row
 * whose id the dialog returns on success.
 */
export interface SchedulesClientProps {
  rows: VScheduleRow[];
  agents: AgentOption[];
  repositories: RepositoryOption[];
  /** When filtered to one agent (the §5.7.1 indicator), used in the empty state. */
  agentFilter: string | null;
}

export function SchedulesClient({ rows, agents, repositories, agentFilter }: SchedulesClientProps) {
  const router = useRouter();
  const [, startTransition] = useTransition();
  const nowMs = useMemo(() => Date.now(), []);

  const [dialog, setDialog] = useState<
    { mode: "new" } | { mode: "edit"; row: VScheduleRow } | null
  >(null);
  const [confirmDelete, setConfirmDelete] = useState<VScheduleRow | null>(null);
  const [flashId, setFlashId] = useState<string | null>(null);

  const runAction = useCallback(
    (action: (prev: null, fd: FormData) => Promise<unknown>, id: string) => {
      const fd = new FormData();
      fd.set("id", id);
      startTransition(async () => {
        await action(null, fd);
        router.refresh();
      });
    },
    [router],
  );

  const tableRows: ScheduleTableRow[] = useMemo(
    () =>
      rows.map((r) => ({
        id: r.id,
        agentName: r.agent_name,
        agentSlug: r.agent_slug,
        repositoryFullName: r.repository_full_name,
        repositoryBranch: r.repository_default_branch,
        lastRunId: r.last_run_id,
        lastRunAgo: r.last_run_finished_at ? formatRelative(r.last_run_finished_at, nowMs) : null,
        flash: r.id === flashId,
        model: buildScheduleCellModel(
          {
            id: r.id,
            state: r.state,
            agentName: r.agent_name,
            agentSlug: r.agent_slug,
            repositoryFullName: r.repository_full_name,
            repositoryBranch: r.repository_default_branch,
            cadence: {
              kind: r.cadence_kind,
              minute: r.cadence_minute,
              hour: r.cadence_hour,
              weekday: r.cadence_weekday,
              intervalHours: r.cadence_interval_hours,
              cron: r.cadence_cron,
            },
            timezone: r.timezone,
            nextRunAtMs: r.next_run_at ? new Date(r.next_run_at).getTime() : null,
            blockReason: r.block_reason,
            lastSkippedReason: r.last_skipped_reason,
            prBlockRunId: r.pr_block_run_id,
            lastRunStatus: r.last_run_status,
            lastRunOutcome: r.last_run_outcome,
            lastRunFinishedAtMs: r.last_run_finished_at
              ? new Date(r.last_run_finished_at).getTime()
              : null,
            lastRunId: r.last_run_id,
          },
          nowMs,
        ),
      })),
    [rows, nowMs, flashId],
  );

  const onDialogSuccess = useCallback(
    (id: string) => {
      setDialog(null);
      setFlashId(id);
      router.refresh();
    },
    [router],
  );

  return (
    <>
      <div className={styles.actionsBar}>
        <Button variant="primary" onClick={() => setDialog({ mode: "new" })}>
          <NewScheduleIcon size={14} aria-hidden="true" /> New schedule
        </Button>
      </div>

      {rows.length === 0 ? (
        <div className={styles.empty} role="status">
          <KLabel>Schedules</KLabel>
          <p className={styles.emptyBody}>
            {agentFilter ? `No schedules for ${agentFilter} yet.` : "No schedules yet."}
          </p>
          <Button variant="primary" onClick={() => setDialog({ mode: "new" })}>
            <NewScheduleIcon size={14} aria-hidden="true" /> New schedule
          </Button>
        </div>
      ) : (
        <SchedulesTable
          rows={tableRows}
          onPause={(id) => runAction(pauseScheduleAction, id)}
          onResume={(id) => runAction(resumeScheduleAction, id)}
          onEdit={(id) => {
            const row = rows.find((r) => r.id === id);
            if (row) setDialog({ mode: "edit", row });
          }}
          onDelete={(id) => {
            const row = rows.find((r) => r.id === id);
            if (row) setConfirmDelete(row);
          }}
          onClearPrBlock={(id) => runAction(clearPrBlockAction, id)}
        />
      )}

      {dialog && (
        <ScheduleDialog
          mode={dialog.mode}
          schedule={dialog.mode === "edit" ? dialog.row : null}
          agents={agents}
          repositories={repositories}
          onClose={() => setDialog(null)}
          onSuccess={onDialogSuccess}
        />
      )}

      {confirmDelete && (
        <DeleteConfirm
          row={confirmDelete}
          onCancel={() => setConfirmDelete(null)}
          onConfirm={() => {
            runAction(deleteScheduleAction, confirmDelete.id);
            setConfirmDelete(null);
          }}
        />
      )}
    </>
  );
}

function DeleteConfirm({
  row,
  onCancel,
  onConfirm,
}: {
  row: VScheduleRow;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const cadence = row.cadence_kind;
  return (
    <div className={styles.overlay}>
      <div
        className={styles.dialog}
        role="alertdialog"
        aria-modal="true"
        aria-label="Delete schedule"
      >
        <h2 className={styles.dialogTitle}>Delete schedule?</h2>
        <p className={styles.dialogBody}>
          <strong>{row.agent_name}</strong>
          {row.repository_full_name ? (
            <>
              {" · "}
              <strong>{row.repository_full_name}</strong>
            </>
          ) : null}
          {" · "}
          <strong>{cadence}</strong> will stop firing. Past runs and their logs are kept.
        </p>
        <div className={styles.dialogActions}>
          <Button variant="secondary" size="sm" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant="secondary" size="sm" className={styles.destructive} onClick={onConfirm}>
            Delete schedule
          </Button>
        </div>
      </div>
    </div>
  );
}
