/**
 * S-112 (#125) — the panel→agent invocation payload contract (FR14, SD5, F1).
 *
 * This is the boundary that closes #89. The authoritative contract is the
 * agent's `_REQUIRED_FIELDS` in
 * `agents/dependency-update/app/dependencyUpdate/main.py`:
 *
 *     _REQUIRED_FIELDS = ("run_id", "repository_org", "repository_name")
 *
 * — three non-empty top-level strings, validated by the agent's
 * `validate_payload`. `buildAgentPayload` emits exactly those three plus
 * `base_branch` and `params`.
 *
 * It NEVER emits `repository_id`: that is a panel-internal foreign key the
 * agent has no knowledge of. The agent derives the clone URL from
 * `repository_org` / `repository_name` (main.py `clone_repo`), so the panel
 * splits `repositories.full_name` ("org/name") into the two halves the agent
 * expects.
 *
 * Nothing type-checks this boundary at runtime — it is JSON over
 * `InvokeAgentRuntime` into a Python validator. The shared fixture
 * `tests/fixtures/agent-invocation-payload.json` (repo root) is asserted by
 * both this module's unit test and a Python test in the agent suite, so a
 * dropped/renamed/nested field fails a test on one side (SR4).
 *
 * Pure module — no Next.js, no I/O, no ambient clock. Fully unit-testable.
 */

/** Stable error code + HTTP status for a `full_name` that is not "org/name". */
export const MALFORMED_REPOSITORY = "MALFORMED_REPOSITORY" as const;

/**
 * A repository `full_name` did not split into exactly two non-empty halves on a
 * single slash. Surfaced as 400 *before any database insert* — a malformed
 * repository is a client error, not a launch that should leave a `runs` row
 * (AC4, security-negative #4).
 */
export class MalformedRepositoryError extends Error {
  readonly code = MALFORMED_REPOSITORY;
  readonly status = 400;

  constructor(received: string) {
    // Name the received value so the operator sees what was rejected; it is a
    // repository name, not a secret.
    super(
      `Repository full_name must be "org/name" (exactly two non-empty halves separated by a single "/"); received ${JSON.stringify(
        received,
      )}.`,
    );
    this.name = "MalformedRepositoryError";
  }
}

export interface SplitRepository {
  org: string;
  name: string;
}

/**
 * Splits a `repositories.full_name` into `{ org, name }`.
 *
 * Accepts only exactly two non-empty, non-whitespace halves separated by a
 * single "/". Every other shape — no slash, leading/trailing slash, multiple
 * slashes, empty or whitespace-only halves — throws `MalformedRepositoryError`.
 * The halves are trimmed; a half that is only whitespace is rejected.
 */
export function splitRepositoryFullName(fullName: string): SplitRepository {
  const parts = fullName.split("/");
  if (parts.length !== 2) {
    throw new MalformedRepositoryError(fullName);
  }
  const org = parts[0].trim();
  const name = parts[1].trim();
  if (org === "" || name === "") {
    throw new MalformedRepositoryError(fullName);
  }
  return { org, name };
}

/** Inputs the route handler already has in hand once it resolved the repo. */
export interface BuildAgentPayloadInput {
  /** The panel-generated run id (uuid, D1). */
  runId: string;
  /** `repositories.full_name`, "org/name". */
  repositoryFullName: string;
  /** The PR base branch (from params or the repo default). */
  baseBranch: string;
  /** The Ajv-validated params object (schema-present keys only). */
  params: Record<string, unknown>;
}

/**
 * The exact JSON shape delivered to the agent. Kept as an explicit interface so
 * a field rename is a compile error on the panel side and a fixture mismatch on
 * the Python side.
 */
export interface AgentInvocationPayload {
  run_id: string;
  repository_org: string;
  repository_name: string;
  base_branch: string;
  params: Record<string, unknown>;
}

/**
 * Builds the agent invocation payload. Splits `full_name` first (throwing
 * `MalformedRepositoryError` before any partial object is produced), then emits
 * exactly the five contract keys. `repository_id` is deliberately absent.
 */
export function buildAgentPayload(input: BuildAgentPayloadInput): AgentInvocationPayload {
  const { org, name } = splitRepositoryFullName(input.repositoryFullName);
  return {
    run_id: input.runId,
    repository_org: org,
    repository_name: name,
    base_branch: input.baseBranch,
    params: input.params,
  };
}
