"use server";

import { createServerClient } from "@/lib/supabase/server";
import {
  clearSchedulePrBlock,
  deleteSchedule as deleteScheduleRow,
  getAgentById,
  getRepositoryById,
  insertSchedule,
  pauseSchedule as pauseScheduleRow,
  previewNextRuns,
  resumeSchedule as resumeScheduleRow,
  updateSchedule as updateScheduleRow,
} from "@/lib/supabase/queries";
import {
  resolveSaveSchedule,
  resolveScheduleMutation,
  type SaveScheduleRaw,
  type SaveScheduleResult,
  type ScheduleActionResult,
} from "@/lib/domain/schedule-save";
import type { CadenceKind } from "@/lib/domain/cadence";

/**
 * S-161/S-162 — the `/schedules` Server Actions (SD-UI-1/SD-UI-2): pause,
 * resume, delete, the G5-c open-PR manual clear, and create/edit.
 *
 * These are thin `"use server"` wrappers over the pure, injectable cores in
 * `lib/domain/schedule-save.ts` (a `"use server"` file may only export async
 * functions, so the sync validators + types live there). All write through the
 * service-role `createServerClient()` (RLS deny-all, D11) and are reachable only
 * when authenticated (`/schedules` is not a `public` route). The list re-reads
 * server-side on `router.refresh()` (server-refetch-is-truth, §5.6).
 */

export async function pauseScheduleAction(
  _prev: ScheduleActionResult | null,
  formData: FormData,
): Promise<ScheduleActionResult> {
  const client = createServerClient();
  return resolveScheduleMutation(
    formData.get("id"),
    { mutate: (id) => pauseScheduleRow(client, id) },
    "Could not pause the schedule. Try again.",
  );
}

export async function resumeScheduleAction(
  _prev: ScheduleActionResult | null,
  formData: FormData,
): Promise<ScheduleActionResult> {
  const client = createServerClient();
  return resolveScheduleMutation(
    formData.get("id"),
    { mutate: (id) => resumeScheduleRow(client, id) },
    "Could not resume the schedule. Try again.",
  );
}

export async function deleteScheduleAction(
  _prev: ScheduleActionResult | null,
  formData: FormData,
): Promise<ScheduleActionResult> {
  const client = createServerClient();
  return resolveScheduleMutation(
    formData.get("id"),
    { mutate: (id) => deleteScheduleRow(client, id) },
    "Could not delete the schedule. Try again.",
  );
}

/**
 * G5-c manual clear ("PR handled · resume anyway"). Sets `pr_block_cleared_at`;
 * the next due-tick re-evaluates and clears the block (S-156).
 */
export async function clearPrBlockAction(
  _prev: ScheduleActionResult | null,
  formData: FormData,
): Promise<ScheduleActionResult> {
  const client = createServerClient();
  return resolveScheduleMutation(
    formData.get("id"),
    { mutate: (id) => clearSchedulePrBlock(client, id) },
    "Could not clear the PR block. Try again.",
  );
}

/** Create or edit a schedule (S-162). Accepts a JSON payload from the dialog. */
export async function saveScheduleAction(raw: SaveScheduleRaw): Promise<SaveScheduleResult> {
  const client = createServerClient();
  return resolveSaveSchedule(raw, {
    getAgent: (id) => getAgentById(client, id),
    getRepository: (id) => getRepositoryById(client, id),
    create: (input) => insertSchedule(client, input),
    update: (id, input) => updateScheduleRow(client, id, input),
  });
}

/**
 * The dialog's live "Next 3 runs" preview (S-162, SD-T6). Calls the
 * authoritative RPC; an invalid/never-matching cadence returns `[]` (the dialog
 * renders "no upcoming runs") rather than throwing.
 */
export async function previewScheduleAction(cadence: {
  kind: CadenceKind;
  minute: number | null;
  hour: number | null;
  weekday: number | null;
  intervalHours: number | null;
  cron: string | null;
  timezone: string;
}): Promise<string[]> {
  const client = createServerClient();
  try {
    return await previewNextRuns(client, cadence, 3);
  } catch {
    return [];
  }
}
