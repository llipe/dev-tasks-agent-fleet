"use client";

import { Input } from "@/components/Input";
import { KLabel } from "@/components/KLabel";
import { validateCron, type CadenceKind } from "@/lib/domain/cadence";

import styles from "./CadencePicker.module.css";

/**
 * S-162 (#274) — the cadence segmented control + kind-specific fields + timezone
 * + the live Preview card (DESIGN.md §5.7.2). The preview's "Next 3 runs" come
 * from the authoritative RPC (passed in as `preview`); this component renders
 * them and the human `summary`, and shows the advanced-cron validity hint from
 * the shared `validateCron` pre-validator.
 */
export interface CadenceValue {
  kind: CadenceKind;
  minute: number | null;
  hour: number | null;
  weekday: number | null;
  intervalHours: number | null;
  cron: string | null;
  timezone: string;
}

export interface CadencePickerProps {
  value: CadenceValue;
  errors: Record<string, string>;
  summary: string;
  preview: string[];
  onChange: (patch: Partial<CadenceValue>) => void;
}

const KINDS: { kind: CadenceKind; label: string }[] = [
  { kind: "hourly", label: "Hourly" },
  { kind: "daily", label: "Daily" },
  { kind: "weekly", label: "Weekly" },
  { kind: "every_n_hours", label: "Every N hours" },
  { kind: "advanced", label: "Advanced (cron)" },
];

const WEEKDAYS = [
  { v: 0, label: "Sunday" },
  { v: 1, label: "Monday" },
  { v: 2, label: "Tuesday" },
  { v: 3, label: "Wednesday" },
  { v: 4, label: "Thursday" },
  { v: 5, label: "Friday" },
  { v: 6, label: "Saturday" },
];

// A small, representative IANA set + the default; the DB honors any valid zone.
const TIMEZONES = [
  "America/Santiago",
  "UTC",
  "America/New_York",
  "America/Los_Angeles",
  "Europe/Madrid",
  "Europe/London",
];

function hhmm(hour: number | null, minute: number | null): string {
  const h = String(hour ?? 0).padStart(2, "0");
  const m = String(minute ?? 0).padStart(2, "0");
  return `${h}:${m}`;
}

function parseTime(v: string): { hour: number; minute: number } | null {
  const m = /^(\d{1,2}):(\d{2})$/.exec(v);
  if (!m) return null;
  return { hour: Number(m[1]), minute: Number(m[2]) };
}

export function CadencePicker({ value, errors, summary, preview, onChange }: CadencePickerProps) {
  const cronCheck = value.kind === "advanced" ? validateCron((value.cron ?? "").trim()) : null;

  return (
    <div className={styles.wrap}>
      <div className={styles.seg} role="tablist" aria-label="Cadence kind">
        {KINDS.map((k) => (
          <button
            key={k.kind}
            type="button"
            role="tab"
            aria-selected={value.kind === k.kind}
            className={`${styles.segOpt} ${value.kind === k.kind ? styles.segActive : ""}`}
            onClick={() => onChange({ kind: k.kind })}
          >
            {k.label}
          </button>
        ))}
      </div>

      <div className={styles.grid}>
        <div className={styles.fields}>
          {value.kind === "hourly" && (
            <p className={styles.explain}>Runs every hour on minute {value.minute ?? 0}.</p>
          )}

          {(value.kind === "daily" || value.kind === "weekly") && (
            <>
              {value.kind === "weekly" && (
                <label className={styles.field}>
                  <span className={styles.fieldLabel}>Weekday</span>
                  <select
                    className={styles.select}
                    value={String(value.weekday ?? 1)}
                    onChange={(e) => onChange({ weekday: Number(e.target.value) })}
                  >
                    {WEEKDAYS.map((d) => (
                      <option key={d.v} value={d.v}>
                        {d.label}
                      </option>
                    ))}
                  </select>
                  {errors.weekday && <span className={styles.err}>{errors.weekday}</span>}
                </label>
              )}
              <label className={styles.field}>
                <span className={styles.fieldLabel}>Time (HH:MM)</span>
                <Input
                  type="time"
                  value={hhmm(value.hour, value.minute)}
                  onChange={(e) => {
                    const t = parseTime(e.target.value);
                    if (t) onChange({ hour: t.hour, minute: t.minute });
                  }}
                />
                {(errors.hour || errors.minute) && (
                  <span className={styles.err}>{errors.hour ?? errors.minute}</span>
                )}
              </label>
            </>
          )}

          {value.kind === "hourly" && (
            <label className={styles.field}>
              <span className={styles.fieldLabel}>Minute (0–59)</span>
              <Input
                type="number"
                min={0}
                max={59}
                value={String(value.minute ?? 0)}
                onChange={(e) => onChange({ minute: Number(e.target.value) })}
              />
              {errors.minute && <span className={styles.err}>{errors.minute}</span>}
            </label>
          )}

          {value.kind === "every_n_hours" && (
            <label className={styles.field}>
              <span className={styles.fieldLabel}>Every N hours (1–23)</span>
              <Input
                type="number"
                min={1}
                max={23}
                value={String(value.intervalHours ?? 6)}
                onChange={(e) => onChange({ intervalHours: Number(e.target.value) })}
              />
              {errors.intervalHours && <span className={styles.err}>{errors.intervalHours}</span>}
            </label>
          )}

          {value.kind === "advanced" && (
            <label className={styles.field}>
              <span className={styles.fieldLabel}>Cron expression</span>
              <Input
                type="text"
                className={cronCheck && !cronCheck.valid ? styles.cronInvalid : undefined}
                placeholder="0 4 * * 1"
                value={value.cron ?? ""}
                onChange={(e) => onChange({ cron: e.target.value })}
              />
              <span className={styles.legend}>
                minute · hour · day-of-month · month · day-of-week
              </span>
              {value.cron && value.cron.trim() !== "" && cronCheck && (
                <span className={cronCheck.valid ? styles.cronOk : styles.err}>
                  {cronCheck.valid ? "✓ valid" : cronCheck.error}
                </span>
              )}
              {errors.cron && <span className={styles.err}>{errors.cron}</span>}
            </label>
          )}

          <label className={styles.field}>
            <span className={styles.fieldLabel}>Timezone</span>
            <select
              className={styles.select}
              value={value.timezone}
              onChange={(e) => onChange({ timezone: e.target.value })}
            >
              {TIMEZONES.map((tz) => (
                <option key={tz} value={tz}>
                  {tz}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className={styles.preview}>
          <KLabel>Preview</KLabel>
          <p className={styles.summary}>{summary}</p>
          {value.kind === "advanced" && value.cron && (
            <p className={styles.cronLine}>cron {value.cron}</p>
          )}
          <div className={styles.nextLabel}>Next 3 runs</div>
          {preview.length === 0 ? (
            <p className={styles.noRuns}>No upcoming runs for this cadence.</p>
          ) : (
            <ul className={styles.nextList}>
              {preview.map((iso) => (
                <li key={iso} className={styles.nextItem}>
                  {formatPreview(iso, value.timezone)}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

function formatPreview(iso: string, timeZone: string): string {
  const d = new Date(iso);
  try {
    return new Intl.DateTimeFormat("en-GB", {
      weekday: "short",
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone,
    }).format(d);
  } catch {
    return iso;
  }
}
