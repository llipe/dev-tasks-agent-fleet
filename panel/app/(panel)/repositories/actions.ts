"use server";

import { createServerClient } from "@/lib/supabase/server";
import {
  getSingleInstallation,
  insertRepository,
  REPOSITORY_ALREADY_EXISTS,
} from "@/lib/supabase/queries";
import { parseFullName, INVALID_REPOSITORY_FORMAT } from "@/lib/domain/repository-input";
import type { RepositoryRow } from "@/lib/supabase/types";

/**
 * `addRepository` Server Action (Story S-147, spec §6/§8.4/§13).
 *
 * Built the SAME WAY as `app/login/actions.ts`'s `signIn` — a pure, injectable
 * core (`resolveAddRepository`) wrapped by a thin `"use server"` action:
 *   - The core is unit-testable without a live Supabase or Next.js request
 *     context (its two dependencies are injected functions, not imports).
 *   - `full_name` is re-validated server-side via `parseFullName` even though
 *     `AddRepositoryForm` already validates it client-side first — the client
 *     check is a fail-fast hint only, never trusted alone (AC4, spec §10).
 *   - `defaultBranch` defaults to `"main"` when absent or blank, matching the
 *     `repositories.default_branch` column default (spec §8.4).
 *   - A duplicate `full_name` is rejected with the friendly
 *     `REPOSITORY_ALREADY_EXISTS` code (from `insertRepository`'s pre-check OR
 *     its `23505` fallback — the core treats both identically, since which
 *     path fired is an implementation detail the caller never needs). Any
 *     other failure maps to a generic `DATABASE_ERROR`, never leaking the raw
 *     Postgres detail (the standing `lib/supabase/errors.ts` convention).
 *   - This action writes through the existing `createServerClient()`
 *     service-role client — no new credential path (RLS stays deny-all, D11).
 *   - Reachable only when authenticated: `/repositories` is not a `public`
 *     route-policy path, so the existing S-117 middleware gate denies an
 *     unauthenticated POST before this action ever runs (no `route-policy.ts`
 *     change needed).
 */

export interface AddRepositorySuccess {
  ok: true;
  repository: RepositoryRow;
}

export interface AddRepositoryFailure {
  ok: false;
  code: typeof INVALID_REPOSITORY_FORMAT | typeof REPOSITORY_ALREADY_EXISTS | "DATABASE_ERROR";
  message: string;
  /** Per-field hints for inline display (currently only `fullName`). */
  fieldErrors?: { fullName?: string };
}

export type AddRepositoryResult = AddRepositorySuccess | AddRepositoryFailure;

/** The minimal dependency surface the core needs (injectable, per the `signIn` pattern). */
export interface AddRepositoryDeps {
  getInstallation: () => Promise<{ id: string }>;
  insert: (row: {
    installationId: string;
    fullName: string;
    defaultBranch: string;
  }) => Promise<RepositoryRow>;
}

const DEFAULT_BRANCH = "main";

/** Narrows an arbitrary thrown value's `code` field, if present, without importing the Error class. */
function errorCode(err: unknown): string | undefined {
  return typeof err === "object" && err !== null && "code" in err
    ? (err as { code?: unknown }).code?.toString()
    : undefined;
}

/**
 * Pure decision core: validate `full_name` shape, resolve the single
 * installation, attempt the insert via the injected function, and map any
 * error to a client-safe result. Never throws.
 */
export async function resolveAddRepository(
  raw: { fullName: unknown; defaultBranch: unknown },
  deps: AddRepositoryDeps,
): Promise<AddRepositoryResult> {
  const fullNameRaw = typeof raw.fullName === "string" ? raw.fullName : "";
  const parsed = parseFullName(fullNameRaw);
  if (!parsed.ok) {
    return {
      ok: false,
      code: INVALID_REPOSITORY_FORMAT,
      message: 'Enter a repository as "owner/repo".',
      fieldErrors: {
        fullName: 'Must be "owner/repo" (letters, numbers, dots, dashes, underscores only).',
      },
    };
  }

  const defaultBranch =
    typeof raw.defaultBranch === "string" && raw.defaultBranch.trim() !== ""
      ? raw.defaultBranch.trim()
      : DEFAULT_BRANCH;

  let installation: { id: string };
  try {
    installation = await deps.getInstallation();
  } catch {
    return databaseErrorResult();
  }

  try {
    const repository = await deps.insert({
      installationId: installation.id,
      fullName: parsed.value,
      defaultBranch,
    });
    return { ok: true, repository };
  } catch (err) {
    if (errorCode(err) === REPOSITORY_ALREADY_EXISTS) {
      return {
        ok: false,
        code: REPOSITORY_ALREADY_EXISTS,
        message: `"${parsed.value}" is already registered.`,
        fieldErrors: { fullName: "This repository is already registered." },
      };
    }
    return databaseErrorResult();
  }
}

function databaseErrorResult(): AddRepositoryFailure {
  return {
    ok: false,
    code: "DATABASE_ERROR",
    message: "Could not add the repository. Try again.",
  };
}

/**
 * The `"use server"` action bound to `AddRepositoryForm`. Wires the real
 * service-role client and runs the pure core.
 *
 * @param _prev previous action state (unused; required by `useActionState`).
 * @param formData the submitted form data (`fullName`, optional `defaultBranch`).
 */
export async function addRepository(
  _prev: AddRepositoryResult | null,
  formData: FormData,
): Promise<AddRepositoryResult> {
  const client = createServerClient();
  return resolveAddRepository(
    { fullName: formData.get("fullName"), defaultBranch: formData.get("defaultBranch") },
    {
      getInstallation: () => getSingleInstallation(client),
      insert: (row) => insertRepository(client, row),
    },
  );
}
