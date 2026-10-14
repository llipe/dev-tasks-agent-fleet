/**
 * S-152 (#264) — pure cadence helpers for the panel (SD-T1/T5).
 *
 * The AUTHORITATIVE next-run math lives in plpgsql
 * (`scheduler.compute_next_run_at` / `scheduler.preview_next_runs`, SD-T6) and
 * the dialog's "next 3 runs" preview comes from that RPC — this module does NOT
 * reimplement it (one source of truth, no drift). What lives here is pure and
 * client-safe:
 *
 *  - `validateCron` — a reject-before-save grammar check mirroring the plpgsql
 *    `scheduler.cron_field_matches` grammar (`*`, number, list, range, step),
 *    so an obviously-invalid advanced cron is caught in the form before a round
 *    trip. The DB remains the final authority (it returns null for an
 *    expression this accepts but that never matches).
 *  - `cadenceLabel` / `cadenceSummary` — the compact table label and the
 *    human sentence shown in the dialog preview header.
 */

export type CadenceKind = "hourly" | "daily" | "weekly" | "every_n_hours" | "advanced";

export interface CadenceSpec {
  kind: CadenceKind;
  minute?: number | null;
  hour?: number | null;
  weekday?: number | null; // 0=Sun..6=Sat
  intervalHours?: number | null;
  cron?: string | null;
}

const WEEKDAY_SHORT = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const WEEKDAY_LONG = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

/** `HH:MM` from minute/hour, defaulting missing parts to 0. */
function hhmm(hour: number | null | undefined, minute: number | null | undefined): string {
  return `${pad2(hour ?? 0)}:${pad2(minute ?? 0)}`;
}

export interface CronValidation {
  valid: boolean;
  /** A human reason when invalid (field name + offending token), else null. */
  error: string | null;
}

// Field bounds matching the plpgsql matcher. dow upper bound is 7 (0 and 7 = Sun).
const FIELD_BOUNDS: ReadonlyArray<readonly [string, number, number]> = [
  ["minute", 0, 59],
  ["hour", 0, 23],
  ["day-of-month", 1, 31],
  ["month", 1, 12],
  ["day-of-week", 0, 7],
];

function validateField(spec: string, lo: number, hi: number): boolean {
  for (const rawPart of spec.split(",")) {
    const part = rawPart.trim();
    const m = /^(\*|\d+(?:-\d+)?)(?:\/(\d+))?$/.exec(part);
    if (!m) return false;
    const step = m[2] ? Number(m[2]) : 1;
    if (step < 1) return false;
    let a = lo;
    let b = hi;
    if (m[1] !== "*") {
      if (part.includes("-") && m[1].includes("-")) {
        const [x, y] = m[1].split("-").map(Number);
        a = x;
        b = y;
      } else {
        a = Number(m[1]);
        // bare number: exact unless a step was given (then "a..hi step n")
        b = m[2] ? hi : a;
      }
    }
    if (a < lo || b > hi || a > b) return false;
  }
  return true;
}

/**
 * Validate a 5-field cron against the closed grammar. Mirrors
 * `scheduler.cron_field_matches` so the dialog can reject before saving. A
 * `valid: true` result does NOT guarantee the expression ever matches (e.g. an
 * impossible day/month combo) — the DB's `compute_next_run_at` is the final
 * authority and returns null for a never-matching expression.
 */
export function validateCron(cron: string): CronValidation {
  const fields = cron.trim().split(/\s+/).filter(Boolean);
  if (fields.length !== 5) {
    return { valid: false, error: `Expected 5 fields, got ${fields.length}.` };
  }
  for (let i = 0; i < 5; i++) {
    const [name, lo, hi] = FIELD_BOUNDS[i]!;
    if (!validateField(fields[i]!, lo, hi)) {
      return { valid: false, error: `Invalid ${name} field "${fields[i]}".` };
    }
  }
  return { valid: true, error: null };
}

/** Compact label for the schedules table Cadence column. */
export function cadenceLabel(spec: CadenceSpec): string {
  switch (spec.kind) {
    case "hourly":
      return "Hourly";
    case "daily":
      return `Daily · ${hhmm(spec.hour, spec.minute)}`;
    case "weekly":
      return `Weekly · ${WEEKDAY_SHORT[spec.weekday ?? 0]} ${hhmm(spec.hour, spec.minute)}`;
    case "every_n_hours":
      return `Every ${spec.intervalHours ?? 0}h`;
    case "advanced":
      return `Cron · ${(spec.cron ?? "").trim()}`;
  }
}

/** The dialog preview's human sentence. */
export function cadenceSummary(spec: CadenceSpec): string {
  switch (spec.kind) {
    case "hourly":
      return "Runs every hour on the hour";
    case "daily":
      return `Runs daily at ${hhmm(spec.hour, spec.minute)}`;
    case "weekly":
      return `Runs every ${WEEKDAY_LONG[spec.weekday ?? 0]} at ${hhmm(spec.hour, spec.minute)}`;
    case "every_n_hours":
      return `Runs every ${spec.intervalHours ?? 0} hours`;
    case "advanced":
      return `Runs on cron ${(spec.cron ?? "").trim()}`;
  }
}
