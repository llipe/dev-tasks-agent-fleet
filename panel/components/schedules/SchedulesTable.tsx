"use client";

import type { CSSProperties } from "react";

import {
  OpenPrIcon,
  WarningIcon,
  SkipIcon,
  PauseIcon,
  PlayIcon,
  EditIcon,
  DeleteIcon,
} from "@/components/icons";
import { GitBranch } from "@phosphor-icons/react/ssr";
import type { ScheduleCellModel, ReasonChip } from "@/lib/domain/schedule-row";

import styles from "./SchedulesTable.module.css";

/**
 * S-161 (#273) — the `/schedules` table (DESIGN.md §5.7). A semantic `<table>`
 * on the §4.4 CSS-grid pattern (`role` preserved by the native element) with the
 * seven columns of §5.7, the unified blocked/skipped reason row (SD-G6), and the
 * right-aligned Pause/Resume · Edit · Delete actions.
 *
 * Presentational: it receives rows already shaped by `buildScheduleCellModel`
 * (pure, clock-injected) plus the per-row action callbacks the client wrapper
 * owns — it renders no data and reads no clock itself. The state pill reuses the
 * StatusPill color mechanism; `paused` is a hollow-dot muted pill mirroring
 * `failed_to_start` (§8.1).
 */
export interface ScheduleTableRow {
  id: string;
  agentName: string;
  agentSlug: string;
  repositoryFullName: string | null;
  repositoryBranch: string | null;
  lastRunId: string | null;
  lastRunAgo: string | null;
  model: ScheduleCellModel;
  flash: boolean;
}

export interface SchedulesTableProps {
  rows: ScheduleTableRow[];
  onPause: (id: string) => void;
  onResume: (id: string) => void;
  onEdit: (id: string) => void;
  onDelete: (id: string) => void;
  onClearPrBlock: (id: string) => void;
}

const STATE_COLOR: Record<ScheduleCellModel["statePill"], string> = {
  active: "--st-ok",
  blocked: "--st-timeout",
  paused: "--muted",
};

const STATE_LABEL: Record<ScheduleCellModel["statePill"], string> = {
  active: "active",
  blocked: "blocked",
  paused: "paused",
};

function PillText({
  kind,
  label,
  colorVar,
  hollow,
}: {
  kind?: ScheduleCellModel["statePill"];
  label: string;
  colorVar?: string;
  hollow?: boolean;
}) {
  const resolved = colorVar ?? (kind ? STATE_COLOR[kind] : "--muted");
  const isHollow = hollow ?? kind === "paused";
  const style = { "--st-color": `var(${resolved})` } as CSSProperties;
  return (
    <span className={styles.pill} style={style}>
      <span className={`${styles.dot} ${isHollow ? styles.hollow : ""}`} aria-hidden="true" />
      <span className={styles.pillLabel}>{label}</span>
    </span>
  );
}

function ReasonGlyph({ glyph }: { glyph: ReasonChip["glyph"] }) {
  switch (glyph) {
    case "open_pr":
      return <OpenPrIcon size={13} aria-hidden="true" />;
    case "auto_paused":
      return <WarningIcon size={13} aria-hidden="true" />;
    case "manual_pause":
      return <PauseIcon size={13} aria-hidden="true" />;
    case "skip":
    default:
      return <SkipIcon size={13} aria-hidden="true" />;
  }
}

const REASON_COLOR: Record<ReasonChip["tone"], string> = {
  timeout: "--st-timeout",
  muted: "--muted",
  faint: "--faint",
};

export function SchedulesTable({
  rows,
  onPause,
  onResume,
  onEdit,
  onDelete,
  onClearPrBlock,
}: SchedulesTableProps) {
  return (
    <div className={styles.scroll}>
      <table className={styles.table} aria-label="Schedules">
        <thead>
          <tr className={`${styles.row} ${styles.headRow}`}>
            <th scope="col" className={styles.headCell}>
              State
            </th>
            <th scope="col" className={styles.headCell}>
              Agent
            </th>
            <th scope="col" className={styles.headCell}>
              Repository
            </th>
            <th scope="col" className={styles.headCell}>
              Cadence
            </th>
            <th scope="col" className={styles.headCell}>
              Next run
            </th>
            <th scope="col" className={styles.headCell}>
              Last run
            </th>
            <th scope="col" className={styles.headCell}>
              Actions
            </th>
          </tr>
        </thead>
        <tbody className={styles.body}>
          {rows.map((row) => (
            <ScheduleRowView
              key={row.id}
              row={row}
              onPause={onPause}
              onResume={onResume}
              onEdit={onEdit}
              onDelete={onDelete}
              onClearPrBlock={onClearPrBlock}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ScheduleRowView({
  row,
  onPause,
  onResume,
  onEdit,
  onDelete,
  onClearPrBlock,
}: {
  row: ScheduleTableRow;
} & Omit<SchedulesTableProps, "rows">) {
  const { model } = row;
  const paused = model.statePill === "paused";

  return (
    <>
      <tr className={`${styles.row} ${row.flash ? styles.flash : ""}`}>
        <td className={styles.cell}>
          <PillText kind={model.statePill} label={STATE_LABEL[model.statePill]} />
        </td>

        <td className={styles.cell}>
          <div className={styles.agentName}>{row.agentName}</div>
          <div className={styles.agentSlug}>{row.agentSlug}</div>
        </td>

        <td className={styles.cell}>
          {row.repositoryFullName ? (
            <>
              <div className={styles.repo}>{row.repositoryFullName}</div>
              {row.repositoryBranch && (
                <div className={styles.branch}>
                  <GitBranch size={11} aria-hidden="true" />
                  {row.repositoryBranch}
                </div>
              )}
            </>
          ) : (
            <span className={styles.noRepo}>—</span>
          )}
        </td>

        <td className={styles.cell}>
          <div className={styles.cadence}>{model.cadenceText}</div>
          <div className={styles.tz}>{model.timezone}</div>
        </td>

        <td className={styles.cell}>
          {model.nextRun ? (
            <>
              <div className={styles.nextRel}>{model.nextRun.relative}</div>
              <div className={styles.nextAbs}>{model.nextRun.absolute}</div>
            </>
          ) : (
            <span className={styles.held}>
              {model.nextRunPlaceholder === "held" ? "held" : "—"}
            </span>
          )}
        </td>

        <td className={styles.cell}>
          {model.lastRun && row.lastRunId ? (
            <a className={styles.lastCell} href={`/runs/${row.lastRunId}`}>
              <PillText
                label={model.lastRun.label}
                colorVar={
                  model.lastRun.status === "succeeded"
                    ? "--st-ok"
                    : model.lastRun.status === "timed_out"
                      ? "--st-timeout"
                      : "--st-fail"
                }
              />
              <span className={styles.lastAgo}>{row.lastRunAgo ?? ""} ↗</span>
            </a>
          ) : (
            <span className={styles.held}>—</span>
          )}
        </td>

        <td className={`${styles.cell} ${styles.actions}`}>
          <button
            type="button"
            className={styles.toggleBtn}
            onClick={() => (paused ? onResume(row.id) : onPause(row.id))}
          >
            {paused ? (
              <PlayIcon size={13} aria-hidden="true" />
            ) : (
              <PauseIcon size={13} aria-hidden="true" />
            )}
            {paused ? "Resume" : "Pause"}
          </button>
          <button
            type="button"
            className={styles.iconBtn}
            aria-label="Edit schedule"
            onClick={() => onEdit(row.id)}
          >
            <EditIcon size={14} aria-hidden="true" />
          </button>
          <button
            type="button"
            className={`${styles.iconBtn} ${styles.deleteBtn}`}
            aria-label="Delete schedule"
            onClick={() => onDelete(row.id)}
          >
            <DeleteIcon size={14} aria-hidden="true" />
          </button>
        </td>
      </tr>

      {model.reason && (
        <tr className={styles.reasonRow}>
          <td className={styles.reasonInner} colSpan={7}>
            <span
              className={styles.reasonChip}
              style={{ "--st-color": `var(${REASON_COLOR[model.reason.tone]})` } as CSSProperties}
            >
              <ReasonGlyph glyph={model.reason.glyph} />
              {model.reason.text}
            </span>
            {model.reason.clearable && (
              <button
                type="button"
                className={styles.clearBtn}
                onClick={() => onClearPrBlock(row.id)}
              >
                PR handled · resume anyway
              </button>
            )}
          </td>
        </tr>
      )}
    </>
  );
}
