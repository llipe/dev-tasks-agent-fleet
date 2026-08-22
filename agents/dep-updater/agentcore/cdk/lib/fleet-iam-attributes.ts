/**
 * Mirror of the fleet IAM allowlists from `@fleet/shared`.
 *
 * WHY THIS IS A COPY AND NOT AN IMPORT
 * ------------------------------------
 * This CDK app is vended by the AgentCore CLI and lives as a standalone npm
 * project (its own `package.json` / `package-lock.json` / `tsconfig.json`),
 * outside the repository's pnpm workspace. Importing `@fleet/shared` fails for
 * three independent reasons:
 *
 *  1. The package is not resolvable here — this project's `node_modules` is
 *     installed by npm from its own lockfile and has no workspace link.
 *  2. `tsconfig.json` sets `rootDir: "."`, so a relative import reaching into
 *     `packages/shared` fails the build with TS6059.
 *  3. `@fleet/shared` ships raw TypeScript (`main: ./src/index.ts`) with no JS
 *     build output, while `cdk.json` runs this app as compiled `dist/bin/cdk.js`.
 *     Type-checking would pass and synthesis would then fail at runtime with
 *     ERR_MODULE_NOT_FOUND.
 *
 * Additionally, the CLI regenerates and overwrites this directory on
 * `agentcore create` / upgrade, so anything here must stay self-contained.
 *
 * The copy is therefore guarded from both sides:
 *  - `infra/test/vended-cdk-iam-drift.test.ts` (the CI-enforced guard) imports
 *    `@fleet/shared` and fails if these values diverge.
 *  - `test/cdk.test.ts` asserts the same invariant from inside this project.
 *
 * Keep every export below a flat literal — no spreads, no computed members —
 * because the drift guards read this file as text.
 */

/** Mirror of `TABLE_NAME` in `@fleet/shared` (packages/shared/src/keys.ts). */
export const FLEET_TABLE_NAME = 'agent-fleet-config';

/**
 * Mirror of `AGENT_EXEC_WRITE_ATTRIBUTES` in `@fleet/shared`.
 *
 * The attributes the agent execution role may write via `dynamodb:UpdateItem`.
 * `pk` / `sk` are included because DynamoDB counts the key attributes among
 * `dynamodb:Attributes` on every request — leaving them out of a
 * `ForAllValues:StringEquals` condition denies all agent writes.
 */
export const AGENT_EXEC_WRITE_ATTRIBUTES = ['pk', 'sk', 'last_status', 'last_outcome_url'];

/**
 * The control-plane-only attributes the agent must never write, denied
 * explicitly as defence in depth. This is `CONTROL_PLANE_WRITE_ATTRIBUTES` minus
 * the key attributes: a Deny keyed on `pk` / `sk` under `ForAnyValue` would
 * match every UpdateItem and lock the agent out entirely.
 */
export const AGENT_EXEC_FORBIDDEN_ATTRIBUTES = ['enabled', 'params'];

/**
 * Secrets Manager name prefix for the agent's GitHub credential.
 *
 * The wildcard covers both `dep-agent/github-pat` (current) and
 * `dep-agent/github-app` (post-migration) so the cutover does not need an IAM
 * change between creating the App secret and flipping `GITHUB_SECRET_ID`.
 *
 * TIGHTEN AFTER CUTOVER: once the GitHub App secret is live and the PAT secret
 * has been deleted, replace this prefix with the single full secret name so the
 * grant resolves to exactly one ARN.
 */
export const FLEET_GITHUB_SECRET_NAME_PREFIX = 'dep-agent/github-';
