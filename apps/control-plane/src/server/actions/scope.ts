/**
 * Scope Server Actions — S-022.
 *
 * All actions:
 * - Re-verify JWT from headers (defense in depth)
 * - Parse input from `unknown` via Zod as the first statement
 * - Return discriminated result { ok: true } | { ok: false, error: ActionError }
 * - Never expose raw AWS errors to the client
 * - Never touch last_* attributes (those are agent/orchestrator-owned)
 * - Log scope writes at info with before/after values
 */
"use server";

import { z } from "zod";
import { revalidatePath } from "next/cache";
import { headers } from "next/headers";
import { paramsSchemaFor, normalizeSubjectId } from "@fleet/shared";
import { verifyToken } from "@/lib/auth/verify-token";
import {
  setSubjectEnabled as repoSetEnabled,
  setSubjectParams as repoSetParams,
  addSubject as repoAddSubject,
  getSubjectAgent,
} from "@/server/repository/scope-repository.js";

// --- Types ---

export interface ActionError {
  code: string;
  message: string;
}

export type ActionResult = { ok: true } | { ok: false; error: ActionError };

// --- Input Schemas ---

export const SetSubjectEnabledSchema = z.object({
  subjectId: z.string().min(1),
  agentName: z.string().min(1),
  enabled: z.boolean(),
});

export const SetSubjectParamsSchema = z.object({
  subjectId: z.string().min(1),
  agentName: z.string().min(1),
  params: z.record(z.string(), z.unknown()),
});

export const AddSubjectToAgentSchema = z.object({
  subjectId: z.string().min(1),
  agentName: z.string().min(1),
  enabled: z.boolean().default(true),
});

// --- Helpers ---

async function reVerifyJwt(): Promise<ActionResult | null> {
  const hdrs = await headers();
  const token = hdrs.get("Cf-Access-Jwt-Assertion") ?? "";

  const teamName = process.env["CF_ACCESS_TEAM_NAME"] ?? "";
  const aud = process.env["CF_ACCESS_AUD"] ?? "";
  const certsUrl = `https://${teamName}.cloudflareaccess.com/cdn-cgi/access/certs`;
  const issuer = `https://${teamName}.cloudflareaccess.com`;

  const result = await verifyToken(token, { certsUrl, issuer, audience: aud });

  if (!result.ok) {
    return { ok: false, error: { code: "unauthorized", message: "Authentication failed" } };
  }
  return null; // success
}

function logScopeWrite(
  action: string,
  subjectId: string,
  agentName: string,
  before: unknown,
  after: unknown,
): void {
  console.info(
    JSON.stringify({
      level: "info",
      action,
      subjectId,
      agentName,
      before,
      after,
      timestamp: new Date().toISOString(),
    }),
  );
}

// --- Actions ---

/**
 * Set the enabled state of a subject-agent pair.
 * Conditional on attribute_exists(pk) — returns not_found if the item doesn't exist.
 */
export async function setSubjectEnabled(input: unknown): Promise<ActionResult> {
  // 1. Parse input from unknown via Zod
  const parsed = SetSubjectEnabledSchema.safeParse(input);
  if (!parsed.success) {
    return {
      ok: false,
      error: { code: "validation_error", message: "Invalid input" },
    };
  }
  const { subjectId, agentName, enabled } = parsed.data;

  // 2. Re-verify JWT
  const authError = await reVerifyJwt();
  if (authError) return authError;

  // 3. Get current state for logging
  const current = await getSubjectAgent(subjectId, agentName);
  const beforeEnabled = current.status === "ok" ? current.data.enabled : undefined;

  // 4. Execute update
  const result = await repoSetEnabled(subjectId, agentName, enabled);

  if (result.status === "error") {
    if (result.error.includes("ConditionalCheckFailed")) {
      return {
        ok: false,
        error: { code: "not_found", message: `Repository "${subjectId}" not found for this agent` },
      };
    }
    return {
      ok: false,
      error: { code: "upstream_error", message: "Failed to update enabled state" },
    };
  }

  // 5. Log the scope write
  logScopeWrite("setSubjectEnabled", subjectId, agentName, { enabled: beforeEnabled }, { enabled });

  // 6. Revalidate the agent page
  revalidatePath(`/agents/${agentName}`);

  return { ok: true };
}

/**
 * Set params for a subject-agent pair.
 * Validates params against paramsSchemaFor(agentName).strict().
 */
export async function setSubjectParams(input: unknown): Promise<ActionResult> {
  // 1. Parse input from unknown via Zod
  const parsed = SetSubjectParamsSchema.safeParse(input);
  if (!parsed.success) {
    return {
      ok: false,
      error: { code: "validation_error", message: "Invalid input" },
    };
  }
  const { subjectId, agentName, params } = parsed.data;

  // 2. Re-verify JWT
  const authError = await reVerifyJwt();
  if (authError) return authError;

  // 3. Validate params against agent-specific schema (strict mode)
  const agentParamsSchema = paramsSchemaFor(agentName);
  const paramsResult = agentParamsSchema.safeParse(params);
  if (!paramsResult.success) {
    const issue = paramsResult.error.issues[0];
    const key = issue?.path?.join(".") || "unknown";
    return {
      ok: false,
      error: {
        code: "params_validation_error",
        message: `Invalid params: key "${key}" — ${issue?.message ?? "validation failed"}`,
      },
    };
  }

  // 4. Get current state for logging
  const current = await getSubjectAgent(subjectId, agentName);
  const beforeParams = current.status === "ok" ? current.data.params : undefined;

  // 5. Execute update
  const result = await repoSetParams(subjectId, agentName, params);

  if (result.status === "error") {
    if (result.error.includes("ConditionalCheckFailed")) {
      return {
        ok: false,
        error: { code: "not_found", message: `Repository "${subjectId}" not found for this agent` },
      };
    }
    return {
      ok: false,
      error: { code: "upstream_error", message: "Failed to update params" },
    };
  }

  // 6. Log the scope write
  logScopeWrite("setSubjectParams", subjectId, agentName, { params: beforeParams }, { params });

  // 7. Revalidate
  revalidatePath(`/agents/${agentName}`);

  return { ok: true };
}

/**
 * Add a subject (repository) to an agent's scope.
 * TransactWriteItems creates META + AGENT# items.
 * attribute_not_exists on AGENT# prevents duplicates.
 */
export async function addSubjectToAgent(input: unknown): Promise<ActionResult> {
  // 1. Parse input from unknown via Zod
  const parsed = AddSubjectToAgentSchema.safeParse(input);
  if (!parsed.success) {
    return {
      ok: false,
      error: { code: "validation_error", message: "Invalid input" },
    };
  }
  const { agentName, enabled } = parsed.data;

  // 2. Re-verify JWT
  const authError = await reVerifyJwt();
  if (authError) return authError;

  // 3. Normalize the subject ID
  const subjectId = normalizeSubjectId(parsed.data.subjectId);

  // 4. Execute transactional add
  const result = await repoAddSubject(subjectId, agentName, enabled);

  if (result.status === "error") {
    if (result.error.includes("conflict")) {
      return {
        ok: false,
        error: {
          code: "conflict",
          message: `Repository "${subjectId}" already exists for agent "${agentName}"`,
        },
      };
    }
    return {
      ok: false,
      error: { code: "upstream_error", message: "Failed to add repository" },
    };
  }

  // 5. Log the scope write
  logScopeWrite("addSubjectToAgent", subjectId, agentName, null, { enabled, params: {} });

  // 6. Revalidate
  revalidatePath(`/agents/${agentName}`);

  return { ok: true };
}
