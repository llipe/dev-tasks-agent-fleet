/**
 * S-153 (#265) — `POST /api/internal/schedules/[id]/fire` (SD-T9, FR5/FR6).
 *
 * The internal endpoint the `pg_cron` due-tick (S-154) calls via `pg_net` to
 * perform a scheduled invocation. It reuses the EXACT manual-invocation path
 * (insert queued run then invoke, D1) so a scheduled run that never starts is a
 * visible `failed_to_start` row, identical to a manual one — only the trigger
 * descriptor differs (`schedule` / `schedule:<id>`, S-150).
 *
 * Authorization is a fail-closed, constant-time shared-secret check
 * (`X-Scheduler-Secret`, SD-A1) — NOT a session (the caller is Postgres). The
 * middleware classifies `/api/internal/**` as `internal` and lets the request
 * through without the session gate; THIS handler is the authorization. An
 * unauthenticated/wrong-secret call returns 401 before any work — the release
 * gate (S-160) asserts that externally.
 *
 * Guardrail re-checks (overlap/open-PR/cap) and G3 counter/auto-pause are hooked
 * here but land fully in S-155/S-156/S-157; today a fire-time failure increments
 * the consecutive-failure counter (recordScheduleFireFailure).
 *
 * Route-segment config inline (S-104 audit D4 / §12): never cached.
 */

import { NextResponse } from "next/server";
import { randomUUID } from "node:crypto";

import { createServerClient } from "@/lib/supabase/server";
import {
  getAgentById,
  getRepositoryById,
  getScheduleById,
  insertQueuedRun,
  markRunFailedToStart,
  recordScheduleFired,
  recordScheduleFireFailure,
} from "@/lib/supabase/queries";
import { invokeResolvedRun } from "@/lib/domain/invoke-resolved-run";
import { validateParams } from "@/lib/schema/validate";
import { invokeAgentRuntime } from "@/lib/aws/invoke";
import { authorizeInternalRequest } from "@/lib/auth/internal-secret";
import { credentialSource } from "@/lib/aws/credentials";
import { describeAwsError } from "@/lib/aws/aws-error";
import type { AnySchema } from "ajv";

export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";
export const runtime = "nodejs";

/** Structured, secret-free fire log line. Never logs the shared secret. */
function logFire(
  fields: {
    schedule_id: string;
    run_id?: string;
    event: string;
    error_code?: string;
    aws_error?: string;
    http?: number;
    request_id?: string;
  },
  logger: Pick<Console, "info" | "error"> = console,
): void {
  const line = JSON.stringify({
    at: "schedule_fire",
    credential_source: credentialSource(),
    ...fields,
  });
  if (fields.error_code) logger.error(line);
  else logger.info(line);
}

export async function POST(
  _request: Request,
  context: { params: Promise<{ id: string }> },
): Promise<NextResponse> {
  // 1. Authorize — fail-closed, constant-time, before ANY work (SD-A1).
  const auth = authorizeInternalRequest(_request);
  if (!auth.ok) {
    logFire({ schedule_id: "-", event: "unauthorized", error_code: "UNAUTHORIZED" });
    return NextResponse.json({ error: "UNAUTHORIZED" }, { status: 401 });
  }

  const { id } = await context.params;
  const client = createServerClient();

  // 2. Load the schedule. A stale/disabled/paused schedule is a 409 (the tick
  //    and the handler can race a CRUD change) — recorded, not an error.
  const schedule = await getScheduleById(client, id);
  if (!schedule || !schedule.is_enabled || schedule.state !== "active") {
    logFire({ schedule_id: id, event: "stale_or_inactive" });
    return NextResponse.json({ skipped: true, reason: "stale_or_inactive" }, { status: 409 });
  }

  // 3. Guardrail re-check hooks (S-155 overlap / S-156 open-PR / S-154 cap).
  //    No-ops until those stories land; kept here so the ordering is fixed.
  //    (Intentionally empty — see S-155/S-156.)

  // 4. Resolve agent + repository and validate params (same as manual invoke).
  const agent = await getAgentById(client, schedule.agent_id);
  if (!agent || !agent.is_enabled) {
    await recordScheduleFireFailure(client, id, "agent_not_found_or_disabled");
    logFire({ schedule_id: id, event: "agent_unavailable", error_code: "AGENT_NOT_FOUND" });
    return NextResponse.json({ skipped: true, reason: "agent_unavailable" }, { status: 409 });
  }

  let repositoryId: string | null = null;
  let installationId: string | null = null;
  let repositoryFullName: string | null = null;
  let defaultBranch = "main";
  if (agent.requires_repository) {
    if (!schedule.repository_id) {
      await recordScheduleFireFailure(client, id, "missing_repository");
      return NextResponse.json({ skipped: true, reason: "missing_repository" }, { status: 409 });
    }
    const repo = await getRepositoryById(client, schedule.repository_id);
    if (!repo || !repo.is_enabled || repo.archived_at !== null) {
      await recordScheduleFireFailure(client, id, "repository_unavailable");
      return NextResponse.json(
        { skipped: true, reason: "repository_unavailable" },
        { status: 409 },
      );
    }
    repositoryId = repo.id;
    installationId = repo.installation_id;
    repositoryFullName = repo.full_name;
    defaultBranch = repo.default_branch || "main";
  }

  const validation = validateParams(
    agent.id,
    agent.params_schema as AnySchema,
    schedule.params as Record<string, unknown>,
  );
  if (!validation.valid) {
    // A schedule whose params no longer validate (the agent schema changed) is
    // a fire-time failure that counts toward G3 (SD-T9 step 4).
    await recordScheduleFireFailure(client, id, "INVALID_PARAMS");
    logFire({ schedule_id: id, event: "invalid_params", error_code: "INVALID_PARAMS" });
    return NextResponse.json({ error: { code: "INVALID_PARAMS" } }, { status: 422 });
  }
  const params = validation.params;
  // 5–8. Shared invoke core (S-172, D-W6): payload → queued insert with the
  //      SCHEDULE trigger descriptor (S-150 / AC2) → invoke → failed_to_start on
  //      throw. The webhook handler runs the same steps.
  const outcome = await invokeResolvedRun(
    {
      newRunId: randomUUID,
      insertQueuedRun: (insert) => insertQueuedRun(client, insert),
      invokeAgentRuntime: (target, req) => invokeAgentRuntime(target, req),
      markRunFailedToStart: (runId, code, message) =>
        markRunFailedToStart(client, runId, code, message),
      onQueued: (runId) =>
        logFire({ schedule_id: id, run_id: runId, event: "queued_row_inserted" }),
    },
    {
      agent,
      repository:
        repositoryId && installationId && repositoryFullName
          ? {
              id: repositoryId,
              installation_id: installationId,
              full_name: repositoryFullName,
              default_branch: defaultBranch,
            }
          : null,
      params,
      trigger: { triggerType: "schedule", triggeredBy: `schedule:${id}` },
    },
  );

  if (!outcome.ok) {
    // The core already marked the run failed_to_start; count it toward G3.
    await recordScheduleFireFailure(client, id, outcome.errorCode);
    logFire({
      schedule_id: id,
      run_id: outcome.runId,
      event: "invocation_failed",
      error_code: outcome.errorCode,
      // Allowlisted AWS error fields only (#306) — never the SDK message.
      ...describeAwsError(outcome.cause),
    });
    return NextResponse.json(
      { error: { code: outcome.errorCode }, run_id: outcome.runId },
      { status: outcome.status },
    );
  }
  const runId = outcome.runId;

  // 9. Record the clean fire (reset counter, pin refs). The tick owns next_run_at.
  await recordScheduleFired(client, id, runId);
  logFire({ schedule_id: id, run_id: runId, event: "fired" });
  return NextResponse.json({ run_id: runId, status: "queued" }, { status: 202 });
}
