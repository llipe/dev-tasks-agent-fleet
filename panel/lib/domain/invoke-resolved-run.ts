/**
 * S-172 (#317) — the shared invoke core (D-W6, FR16). The schedule fire route
 * and the webhook handler both call this, so a webhook-fired run goes through
 * exactly the machinery a scheduled run does; only the trigger descriptor differs.
 *
 * Steps (extracted from the S-153 fire route, unchanged):
 *   1. build the agent payload (repository agents: org/name split + base branch;
 *      no-repository agents: run_id + base_branch + params);
 *   2. buildRunInsert with the caller's TriggerDescriptor → insertQueuedRun
 *      (panel-owned run id, D1). An insert failure propagates; nothing was invoked;
 *   3. invokeAgentRuntime;
 *   4. on an invoke throw: markRunFailedToStart so the run is a visible
 *      `failed_to_start`. A failure to mark is swallowed (the reaper is the
 *      backstop) and reported as `markFailed`.
 *
 * Returns a typed result; callers keep their own logging, bookkeeping and HTTP
 * response. The manual invoke route keeps its own copy for now (out of S-172's
 * scope).
 */

import { buildAgentPayload } from "@/lib/domain/payload";
import { buildRunInsert, type RunInsert, type TriggerDescriptor } from "@/lib/domain/run-insert";
import { asTypedError, INVOCATION_FAILED } from "@/lib/errors";

export interface InvokeCoreAgent {
  id: string;
  version: string;
  runtime_arn: string;
  runtime_qualifier: string;
  requires_repository: boolean;
  max_runtime_seconds: number;
  grace_seconds: number;
  start_timeout_seconds: number;
}

export interface InvokeCoreRepository {
  id: string;
  installation_id: string;
  full_name: string;
  default_branch: string;
}

export interface InvokeCoreInput {
  agent: InvokeCoreAgent;
  repository: InvokeCoreRepository | null;
  params: Record<string, unknown>;
  trigger: TriggerDescriptor;
}

export interface InvokeCoreDeps {
  newRunId(): string;
  insertQueuedRun(insert: RunInsert): Promise<void>;
  invokeAgentRuntime(
    target: { runtimeArn: string; runtimeQualifier: string },
    request: { payload: Record<string, unknown> },
  ): Promise<unknown>;
  markRunFailedToStart(runId: string, errorCode: string, message: string): Promise<void>;
  /** Optional: called after the queued insert, before the invoke (the fire route's log line). */
  onQueued?(runId: string): void;
}

export type InvokeCoreResult =
  | { ok: true; runId: string }
  | {
      ok: false;
      runId: string;
      errorCode: string;
      status: number;
      /** The original error, for the caller's allowlisted AWS logging (#306). */
      cause: unknown;
      /** True when markRunFailedToStart itself failed (the run stays queued). */
      markFailed: boolean;
    };

export async function invokeResolvedRun(
  deps: InvokeCoreDeps,
  input: InvokeCoreInput,
): Promise<InvokeCoreResult> {
  const { agent, repository, params, trigger } = input;
  const defaultBranch = repository?.default_branch || "main";
  const baseBranch =
    typeof params.base_branch === "string" && params.base_branch.trim() !== ""
      ? params.base_branch
      : defaultBranch;

  const runId = deps.newRunId();
  const payload: Record<string, unknown> =
    agent.requires_repository && repository
      ? (buildAgentPayload({
          runId,
          repositoryFullName: repository.full_name,
          baseBranch,
          params,
        }) as unknown as Record<string, unknown>)
      : { run_id: runId, base_branch: baseBranch, params };

  await deps.insertQueuedRun(
    buildRunInsert({
      runId,
      agent: {
        id: agent.id,
        version: agent.version,
        max_runtime_seconds: agent.max_runtime_seconds,
        grace_seconds: agent.grace_seconds,
        start_timeout_seconds: agent.start_timeout_seconds,
      },
      repositoryId: repository?.id ?? null,
      installationId: repository?.installation_id ?? null,
      params,
      trigger,
    }),
  );
  deps.onQueued?.(runId);

  try {
    await deps.invokeAgentRuntime(
      { runtimeArn: agent.runtime_arn, runtimeQualifier: agent.runtime_qualifier },
      { payload },
    );
    return { ok: true, runId };
  } catch (invokeErr) {
    const typed = asTypedError(invokeErr);
    const errorCode = typed?.code ?? INVOCATION_FAILED;
    const status = typed?.status ?? 502;
    let markFailed = false;
    try {
      await deps.markRunFailedToStart(runId, errorCode, typed?.message ?? "Invoke failed.");
    } catch {
      markFailed = true;
    }
    return { ok: false, runId, errorCode, status, cause: invokeErr, markFailed };
  }
}
