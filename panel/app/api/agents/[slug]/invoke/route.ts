/**
 * S-112 (#125) — `POST /api/agents/[slug]/invoke` (FR14, SD5, closes #89).
 *
 * The panel's first database write and its reach across the panel→agent
 * boundary. The handler runs in the NORMATIVE order (D1) so an invocation that
 * never starts is a visible `failed_to_start` row rather than an invisible
 * nothing:
 *
 *   resolve agent -> resolve repository -> Ajv-validate params ->
 *   generate run_id -> split full_name -> INSERT queued run ->
 *   assume role (implicit in the provider) -> InvokeAgentRuntime ->
 *   update session_id/runtime_invocation_id
 *
 * The insert precedes the invoke. If `InvokeAgentRuntime` throws, the run is
 * marked `failed_to_start` here (AC12) and a 502 carrying `run_id` is returned
 * — the panel does not wait for the reaper.
 *
 * Route-segment config is declared INLINE (not re-exported): Next.js silently
 * ignores `dynamic`/`revalidate`/`fetchCache` when re-exported from another
 * module (S-104 audit D4, technical-guidelines §12).
 */

import { NextResponse } from "next/server";
import { randomUUID } from "node:crypto";
import { createServerClient } from "@/lib/supabase/server";
import {
  getAgentBySlug,
  getRepositoryById,
  insertQueuedRun,
  markRunFailedToStart,
  updateRunInvocationRefs,
} from "@/lib/supabase/queries";
import { buildAgentPayload, MalformedRepositoryError } from "@/lib/domain/payload";
import { buildRunInsert } from "@/lib/domain/run-insert";
import { validateParams } from "@/lib/schema/validate";
import { invokeAgentRuntime } from "@/lib/aws/invoke";
import {
  ApiError,
  asTypedError,
  InvalidParamsError,
  INVOCATION_FAILED,
  DATABASE_ERROR,
} from "@/lib/errors";
import { credentialSource } from "@/lib/aws/credentials";
import type { AnySchema } from "ajv";

// Inline route-segment config — never read stale run state.
export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";

interface InvokeRequestBody {
  repository_id?: unknown;
  params?: unknown;
}

/** Structured, secret-free invoke log line (AC11). */
function logInvoke(
  fields: {
    run_id: string;
    agent_slug: string;
    repository_full_name: string | null;
    event: string;
    error_code?: string;
  },
  logger: Pick<Console, "info" | "error"> = console,
): void {
  const line = JSON.stringify({
    at: "invoke_route",
    credential_source: credentialSource(),
    ...fields,
  });
  if (fields.error_code) logger.error(line);
  else logger.info(line);
}

export async function POST(
  request: Request,
  context: { params: Promise<{ slug: string }> },
): Promise<NextResponse> {
  const { slug } = await context.params;
  const client = createServerClient();

  // Parse the body defensively — a non-JSON or non-object body is a 400.
  let body: InvokeRequestBody;
  try {
    const parsed = await request.json();
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      throw new Error("body is not an object");
    }
    body = parsed as InvokeRequestBody;
  } catch {
    return NextResponse.json(
      new ApiError("INVALID_PARAMS", 400, "Request body must be a JSON object.").toBody(),
      { status: 400 },
    );
  }

  try {
    // 1. Resolve agent.
    const agent = await getAgentBySlug(client, slug);
    if (!agent || !agent.is_enabled) {
      // A disabled agent is not-found, never an empty invoke.
      return NextResponse.json(
        new ApiError("AGENT_NOT_FOUND", 404, `No enabled agent with slug "${slug}".`).toBody(),
        { status: 404 },
      );
    }

    // 2. Resolve repository (only when the agent requires one).
    let repositoryId: string | null = null;
    let installationId: string | null = null;
    let repositoryFullName: string | null = null;
    let defaultBranch = "main";

    if (agent.requires_repository) {
      const repoId = typeof body.repository_id === "string" ? body.repository_id : null;
      if (!repoId) {
        return NextResponse.json(
          new ApiError(
            "MALFORMED_REPOSITORY",
            400,
            "This agent requires a repository_id.",
          ).toBody(),
          { status: 400 },
        );
      }
      const repo = await getRepositoryById(client, repoId);
      if (!repo || !repo.is_enabled || repo.archived_at !== null) {
        return NextResponse.json(
          new ApiError(
            "MALFORMED_REPOSITORY",
            400,
            "The selected repository is unknown, disabled, or archived.",
          ).toBody(),
          { status: 400 },
        );
      }
      repositoryId = repo.id;
      installationId = repo.installation_id;
      repositoryFullName = repo.full_name;
      defaultBranch = repo.default_branch || "main";
    }

    // 3. Validate params against the agent schema (server-authoritative,
    //    security-negative #3). Rejected BEFORE any run_id or insert (AC13).
    const validation = validateParams(agent.id, agent.params_schema as AnySchema, body.params);
    if (!validation.valid) {
      throw new InvalidParamsError(validation.errors);
    }
    const params = validation.params;

    // The base branch: explicit param wins, else the repo default.
    const baseBranch =
      typeof params.base_branch === "string" && params.base_branch.trim() !== ""
        ? (params.base_branch as string)
        : defaultBranch;

    // 4. Generate the run id (panel-owned, D1).
    const runId = randomUUID();

    // 5. Split full_name (throws MalformedRepositoryError before any insert)
    //    and build the agent payload. For a no-repository agent there is no
    //    payload repository — but the seeded agent requires one, so this path
    //    only builds a payload when a repository is present.
    let agentPayload: Record<string, unknown> | null = null;
    if (agent.requires_repository && repositoryFullName) {
      agentPayload = buildAgentPayload({
        runId,
        repositoryFullName,
        baseBranch,
        params,
      }) as unknown as Record<string, unknown>;
    } else {
      // No-repository agent: the payload carries no org/name.
      agentPayload = { run_id: runId, base_branch: baseBranch, params };
    }

    // 6. Insert the queued run (D1) — all three timeout snapshots explicit (OQ3).
    const insert = buildRunInsert({
      runId,
      agent: {
        id: agent.id,
        version: agent.version,
        max_runtime_seconds: agent.max_runtime_seconds,
        grace_seconds: agent.grace_seconds,
        start_timeout_seconds: agent.start_timeout_seconds,
      },
      repositoryId,
      installationId,
      params,
    });
    await insertQueuedRun(client, insert);

    logInvoke({
      run_id: runId,
      agent_slug: slug,
      repository_full_name: repositoryFullName,
      event: "queued_row_inserted",
    });

    // 7 & 8. Assume role (implicit in the credential provider) + invoke. On a
    //        throw, mark failed_to_start and return 502 with run_id (AC12).
    try {
      await invokeAgentRuntime(
        { runtimeArn: agent.runtime_arn, runtimeQualifier: agent.runtime_qualifier },
        { payload: agentPayload },
      );
    } catch (invokeErr) {
      const typed = asTypedError(invokeErr);
      const errorCode = typed?.code ?? INVOCATION_FAILED;
      const status = typed?.status ?? 502;

      // Persist the failure so it is immediately visible (AC12).
      try {
        await markRunFailedToStart(
          client,
          runId,
          errorCode,
          typed?.message ?? "InvokeAgentRuntime failed.",
        );
      } catch (markErr) {
        // The run stays queued; the reaper is the backstop. Log and continue.
        logInvoke({
          run_id: runId,
          agent_slug: slug,
          repository_full_name: repositoryFullName,
          event: "mark_failed_to_start_failed",
          error_code: DATABASE_ERROR,
        });
        void markErr;
      }

      logInvoke({
        run_id: runId,
        agent_slug: slug,
        repository_full_name: repositoryFullName,
        event: "invocation_failed",
        error_code: errorCode,
      });

      // A credential failure (500) keeps its status; an invocation failure is
      // 502. Both carry run_id so the form can navigate to /runs/[id].
      return NextResponse.json(
        {
          error: {
            code: errorCode,
            message: typed?.message ?? "The agent invocation failed.",
          },
          run_id: runId,
        },
        { status },
      );
    }

    // 9. Record the invocation refs (best-effort; the run is already visible).
    try {
      await updateRunInvocationRefs(client, runId, {
        session_id: null,
        runtime_invocation_id: null,
      });
    } catch {
      // Non-fatal: the run exists and is queued. Refs are diagnostic only.
    }

    logInvoke({
      run_id: runId,
      agent_slug: slug,
      repository_full_name: repositoryFullName,
      event: "invoked",
    });

    return NextResponse.json({ run_id: runId, status: "queued" }, { status: 202 });
  } catch (err) {
    // Typed, expected errors -> their status + client-safe body.
    if (err instanceof MalformedRepositoryError || err instanceof ApiError) {
      const body =
        err instanceof ApiError
          ? err.toBody()
          : { error: { code: err.code, message: err.message } };
      return NextResponse.json(body, { status: err.status });
    }
    const typed = asTypedError(err);
    if (typed) {
      if (typed.logDetail) console.error(`[invoke] ${typed.code} ${typed.logDetail}`);
      return NextResponse.json(
        { error: { code: typed.code, message: typed.message } },
        { status: typed.status },
      );
    }
    // Unknown error -> generic 500, nothing leaked.
    console.error("[invoke] unexpected error", err);
    return NextResponse.json(
      { error: { code: "INTERNAL_ERROR", message: "An unexpected error occurred." } },
      { status: 500 },
    );
  }
}
