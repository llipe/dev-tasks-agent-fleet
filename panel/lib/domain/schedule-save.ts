/**
 * S-161/S-162 — pure, injectable cores for the `/schedules` Server Actions
 * (SD-UI-1/SD-UI-2). Lives OUTSIDE the `"use server"` module because a
 * `"use server"` file may only export async functions (Next.js constraint); the
 * sync validators and the result/dep types belong here and are exhaustively
 * unit-testable without a live Supabase or Next.js request context.
 *
 * The DB remains the final authority (its `chk_schedule_cadence` check +
 * `compute_next_run_at`); these cores are the fail-fast surface so a bad submit
 * never round-trips. Every DB failure maps to a generic `DATABASE_ERROR` (no
 * Postgres detail leaks).
 */

import { validateParams } from "@/lib/schema/validate";
import { validateCron, type CadenceKind } from "@/lib/domain/cadence";
import type { ScheduleWriteInput } from "@/lib/supabase/queries";
import type { AnySchema } from "ajv";

// ---- mutation (pause/resume/delete/clear) --------------------------------

export const SCHEDULE_INVALID_ID = "INVALID_ID" as const;

export interface ScheduleActionSuccess {
  ok: true;
}
export interface ScheduleActionFailure {
  ok: false;
  code: typeof SCHEDULE_INVALID_ID | "DATABASE_ERROR";
  message: string;
}
export type ScheduleActionResult = ScheduleActionSuccess | ScheduleActionFailure;

export interface ScheduleMutationDeps {
  mutate: (id: string) => Promise<void>;
}

/** Validate the `id` shape, run the injected mutation, map errors. Never throws. */
export async function resolveScheduleMutation(
  rawId: unknown,
  deps: ScheduleMutationDeps,
  failMessage: string,
): Promise<ScheduleActionResult> {
  const id = typeof rawId === "string" ? rawId.trim() : "";
  if (id === "") {
    return { ok: false, code: SCHEDULE_INVALID_ID, message: "Missing schedule id." };
  }
  try {
    await deps.mutate(id);
    return { ok: true };
  } catch {
    return { ok: false, code: "DATABASE_ERROR", message: failMessage };
  }
}

// ---- create / edit -------------------------------------------------------

export const SAVE_CODES = {
  INVALID_CADENCE: "INVALID_CADENCE",
  INVALID_PARAMS: "INVALID_PARAMS",
  MISSING_REPOSITORY: "MISSING_REPOSITORY",
  AGENT_UNAVAILABLE: "AGENT_UNAVAILABLE",
  DATABASE_ERROR: "DATABASE_ERROR",
} as const;
export type SaveCode = (typeof SAVE_CODES)[keyof typeof SAVE_CODES];

export interface SaveScheduleSuccess {
  ok: true;
  id: string;
}
export interface SaveScheduleFailure {
  ok: false;
  code: SaveCode;
  message: string;
  fieldErrors?: Record<string, string>;
}
export type SaveScheduleResult = SaveScheduleSuccess | SaveScheduleFailure;

/** The raw, untrusted candidate the dialog submits. */
export interface SaveScheduleRaw {
  scheduleId?: string | null; // present => edit
  agentId: unknown;
  repositoryId: unknown;
  name: unknown;
  params: unknown;
  cadenceKind: unknown;
  cadenceMinute: unknown;
  cadenceHour: unknown;
  cadenceWeekday: unknown;
  cadenceIntervalHours: unknown;
  cadenceCron: unknown;
  timezone: unknown;
  autoPauseThreshold: unknown;
  notifyOnSuccess: unknown;
}

export interface SaveScheduleDeps {
  getAgent: (id: string) => Promise<{
    id: string;
    is_enabled: boolean;
    requires_repository: boolean;
    params_schema: unknown;
  } | null>;
  getRepository: (id: string) => Promise<{
    id: string;
    installation_id: string;
    is_enabled: boolean;
    archived_at: string | null;
  } | null>;
  create: (input: ScheduleWriteInput) => Promise<string>;
  update: (id: string, input: ScheduleWriteInput) => Promise<void>;
}

function intOrNull(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = typeof v === "number" ? v : Number(String(v));
  return Number.isFinite(n) ? n : null;
}

/** Validate the kind-specific cadence fields. Returns a field-error map or null. */
export function validateCadence(
  kind: CadenceKind,
  f: {
    minute: number | null;
    hour: number | null;
    weekday: number | null;
    intervalHours: number | null;
    cron: string | null;
  },
): Record<string, string> | null {
  const errs: Record<string, string> = {};
  const inRange = (n: number | null, lo: number, hi: number) => n !== null && n >= lo && n <= hi;
  switch (kind) {
    case "hourly":
      if (!inRange(f.minute, 0, 59)) errs.minute = "Minute must be 0–59.";
      break;
    case "daily":
      if (!inRange(f.minute, 0, 59)) errs.minute = "Minute must be 0–59.";
      if (!inRange(f.hour, 0, 23)) errs.hour = "Hour must be 0–23.";
      break;
    case "weekly":
      if (!inRange(f.minute, 0, 59)) errs.minute = "Minute must be 0–59.";
      if (!inRange(f.hour, 0, 23)) errs.hour = "Hour must be 0–23.";
      if (!inRange(f.weekday, 0, 6)) errs.weekday = "Pick a weekday.";
      break;
    case "every_n_hours":
      if (!inRange(f.intervalHours, 1, 23)) errs.intervalHours = "Interval must be 1–23 hours.";
      break;
    case "advanced": {
      const cron = (f.cron ?? "").trim();
      if (cron === "") errs.cron = "Enter a cron expression.";
      else {
        const v = validateCron(cron);
        if (!v.valid) errs.cron = v.error ?? "Invalid cron expression.";
      }
      break;
    }
  }
  return Object.keys(errs).length > 0 ? errs : null;
}

/**
 * Validate agent, repository requirement, cadence, and params, then create or
 * update via the injected functions. Never throws.
 */
export async function resolveSaveSchedule(
  raw: SaveScheduleRaw,
  deps: SaveScheduleDeps,
): Promise<SaveScheduleResult> {
  const agentId = typeof raw.agentId === "string" ? raw.agentId.trim() : "";
  if (agentId === "") {
    return { ok: false, code: SAVE_CODES.AGENT_UNAVAILABLE, message: "Select an agent." };
  }

  let agent;
  try {
    agent = await deps.getAgent(agentId);
  } catch {
    return dbFail();
  }
  if (!agent || !agent.is_enabled) {
    return { ok: false, code: SAVE_CODES.AGENT_UNAVAILABLE, message: "That agent is unavailable." };
  }

  let repositoryId: string | null = null;
  let installationId: string | null = null;
  if (agent.requires_repository) {
    const rid = typeof raw.repositoryId === "string" ? raw.repositoryId.trim() : "";
    if (rid === "") {
      return {
        ok: false,
        code: SAVE_CODES.MISSING_REPOSITORY,
        message: "This agent requires a repository.",
        fieldErrors: { repositoryId: "Pick a repository." },
      };
    }
    let repo;
    try {
      repo = await deps.getRepository(rid);
    } catch {
      return dbFail();
    }
    if (!repo || !repo.is_enabled || repo.archived_at !== null) {
      return {
        ok: false,
        code: SAVE_CODES.MISSING_REPOSITORY,
        message: "That repository is unavailable.",
        fieldErrors: { repositoryId: "Pick an enabled repository." },
      };
    }
    repositoryId = repo.id;
    installationId = repo.installation_id;
  }

  const kind = String(raw.cadenceKind) as CadenceKind;
  const validKinds: CadenceKind[] = ["hourly", "daily", "weekly", "every_n_hours", "advanced"];
  if (!validKinds.includes(kind)) {
    return { ok: false, code: SAVE_CODES.INVALID_CADENCE, message: "Pick a cadence." };
  }
  const cadence = {
    minute: intOrNull(raw.cadenceMinute),
    hour: intOrNull(raw.cadenceHour),
    weekday: intOrNull(raw.cadenceWeekday),
    intervalHours: intOrNull(raw.cadenceIntervalHours),
    cron: typeof raw.cadenceCron === "string" ? raw.cadenceCron.trim() : null,
  };
  const cadenceErrors = validateCadence(kind, cadence);
  if (cadenceErrors) {
    return {
      ok: false,
      code: SAVE_CODES.INVALID_CADENCE,
      message: "Fix the highlighted cadence fields.",
      fieldErrors: cadenceErrors,
    };
  }

  const paramsInput = raw.params ?? {};
  const validation = validateParams(agent.id, agent.params_schema as AnySchema, paramsInput);
  if (!validation.valid) {
    const fieldErrors: Record<string, string> = {};
    for (const e of validation.errors) {
      const key = e.instancePath.replace(/^\//, "");
      if (key) fieldErrors[`params.${key}`] = e.message;
    }
    return {
      ok: false,
      code: SAVE_CODES.INVALID_PARAMS,
      message: "Fix the highlighted parameters.",
      fieldErrors,
    };
  }

  const threshold = intOrNull(raw.autoPauseThreshold);
  const write: ScheduleWriteInput = {
    agentId: agent.id,
    repositoryId,
    installationId,
    name: typeof raw.name === "string" && raw.name.trim() !== "" ? raw.name.trim() : null,
    params: validation.params,
    cadenceKind: kind,
    cadenceMinute: kind === "every_n_hours" || kind === "advanced" ? null : cadence.minute,
    cadenceHour: kind === "daily" || kind === "weekly" ? cadence.hour : null,
    cadenceWeekday: kind === "weekly" ? cadence.weekday : null,
    cadenceIntervalHours: kind === "every_n_hours" ? cadence.intervalHours : null,
    cadenceCron: kind === "advanced" ? cadence.cron : null,
    timezone:
      typeof raw.timezone === "string" && raw.timezone.trim() !== ""
        ? raw.timezone.trim()
        : "America/Santiago",
    autoPauseThreshold: threshold !== null && threshold >= 1 ? threshold : 3,
    notifyOnSuccess:
      raw.notifyOnSuccess === true ||
      raw.notifyOnSuccess === "true" ||
      raw.notifyOnSuccess === "on",
  };

  try {
    const scheduleId = typeof raw.scheduleId === "string" ? raw.scheduleId.trim() : "";
    if (scheduleId !== "") {
      await deps.update(scheduleId, write);
      return { ok: true, id: scheduleId };
    }
    const id = await deps.create(write);
    return { ok: true, id };
  } catch {
    return dbFail();
  }
}

function dbFail(): SaveScheduleFailure {
  return {
    ok: false,
    code: SAVE_CODES.DATABASE_ERROR,
    message: "Could not save the schedule. Try again.",
  };
}
