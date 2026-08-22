import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import {
  KEY_ATTRIBUTES,
  CONTROL_PLANE_WRITE_ATTRIBUTES,
  AGENT_EXEC_WRITE_ATTRIBUTES,
  TABLE_NAME,
} from "@fleet/shared";

/**
 * Drift guard for the vended AgentCore CDK app's IAM allowlist mirror.
 *
 * The deployed dep-updater runtime's real permissions are governed by
 * `agents/dep-updater/agentcore/cdk/lib/cdk-stack.ts`, not by
 * `infra/lib/iam-stack.ts` — AgentCore provisions its own execution role and
 * never assumes `agent-fleet-agent-exec-role`. That vended app is a standalone
 * npm project outside the pnpm workspace, so it cannot resolve `@fleet/shared`
 * and has to mirror the allowlists in `lib/fleet-iam-attributes.ts`.
 *
 * This test is the CI-enforced side of that mirror: it imports the real source
 * of truth from `@fleet/shared` and fails the moment the mirrored copy diverges.
 * Without it, the write-separation control that S-004 enforces could silently
 * weaken on the only role that actually matters at runtime.
 */

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, "../..");
const VENDED_CDK_LIB = resolve(REPO_ROOT, "agents/dep-updater/agentcore/cdk/lib");
const MIRROR_PATH = resolve(VENDED_CDK_LIB, "fleet-iam-attributes.ts");
const STACK_PATH = resolve(VENDED_CDK_LIB, "cdk-stack.ts");

function readMirror(): string {
  return readFileSync(MIRROR_PATH, "utf-8");
}

/**
 * Extract a string-literal array export from the mirror module.
 *
 * The mirror is deliberately written as flat literal arrays (no spreads, no
 * computed members) precisely so a regex can read it without a TS parser. If
 * that ever stops being true, this throws rather than silently passing.
 */
function parseArrayExport(source: string, constName: string): string[] {
  const match = new RegExp(`export const ${constName}\\s*=\\s*\\[([^\\]]*)\\]`, "s").exec(source);
  if (!match?.[1]) {
    throw new Error(`${constName} is not a literal array export in fleet-iam-attributes.ts`);
  }
  const body = match[1];
  if (body.includes("...")) {
    throw new Error(
      `${constName} must be a flat literal array so this drift guard can parse it without a TS compiler`,
    );
  }
  const values = [...body.matchAll(/['"]([^'"]+)['"]/g)]
    .map((m) => m[1])
    .filter((value): value is string => value !== undefined);
  expect(values.length, `${constName} must contain at least one entry`).toBeGreaterThan(0);
  return values;
}

function parseStringExport(source: string, constName: string): string {
  const match = new RegExp(`export const ${constName}\\s*=\\s*['"]([^'"]+)['"]`).exec(source);
  if (!match?.[1]) {
    throw new Error(`${constName} is not a string literal export in fleet-iam-attributes.ts`);
  }
  return match[1];
}

/**
 * The attributes the agent must never write. `infra/lib/iam-stack.ts` denies
 * exactly `enabled` / `params`, which is `CONTROL_PLANE_WRITE_ATTRIBUTES` minus
 * the key attributes — the keys are excluded deliberately, since a Deny keyed on
 * `pk` / `sk` under `ForAnyValue` would block every UpdateItem the agent makes.
 */
const CONTROL_PLANE_ONLY_ATTRIBUTES = CONTROL_PLANE_WRITE_ATTRIBUTES.filter(
  (attribute) => !(KEY_ATTRIBUTES as readonly string[]).includes(attribute),
);

describe("vended CDK IAM mirror — no drift from @fleet/shared", () => {
  it("AGENT_EXEC_WRITE_ATTRIBUTES matches @fleet/shared exactly, in order", () => {
    const mirrored = parseArrayExport(readMirror(), "AGENT_EXEC_WRITE_ATTRIBUTES");
    expect(mirrored).toEqual([...AGENT_EXEC_WRITE_ATTRIBUTES]);
  });

  it("AGENT_EXEC_FORBIDDEN_ATTRIBUTES matches the control-plane-only attributes", () => {
    const mirrored = parseArrayExport(readMirror(), "AGENT_EXEC_FORBIDDEN_ATTRIBUTES");
    expect(mirrored).toEqual([...CONTROL_PLANE_ONLY_ATTRIBUTES]);
  });

  it("FLEET_TABLE_NAME matches @fleet/shared TABLE_NAME", () => {
    expect(parseStringExport(readMirror(), "FLEET_TABLE_NAME")).toBe(TABLE_NAME);
  });
});

describe("vended CDK IAM mirror — write separation invariants hold", () => {
  it("does not allow the agent to write any control-plane-only attribute", () => {
    const write = parseArrayExport(readMirror(), "AGENT_EXEC_WRITE_ATTRIBUTES");
    for (const forbidden of CONTROL_PLANE_ONLY_ATTRIBUTES) {
      expect(write, `agent must not be able to write ${forbidden}`).not.toContain(forbidden);
    }
  });

  it("keeps the key attributes in the write allowlist", () => {
    // DynamoDB counts pk/sk among `dynamodb:Attributes` on every UpdateItem, so
    // omitting them from the ForAllValues allowlist denies all agent writes.
    const write = parseArrayExport(readMirror(), "AGENT_EXEC_WRITE_ATTRIBUTES");
    expect(write).toEqual(expect.arrayContaining([...KEY_ATTRIBUTES]));
  });

  it("never lists a key attribute among the forbidden attributes", () => {
    const forbidden = parseArrayExport(readMirror(), "AGENT_EXEC_FORBIDDEN_ATTRIBUTES");
    for (const key of KEY_ATTRIBUTES) {
      expect(forbidden, `${key} must not be denied`).not.toContain(key);
    }
  });
});

describe("vended CDK stack — consumes the mirror rather than inlining values", () => {
  it("imports the allowlist from ./fleet-iam-attributes", () => {
    const stack = readFileSync(STACK_PATH, "utf-8");
    expect(stack).toMatch(/from\s+['"]\.\/fleet-iam-attributes['"]/);
  });

  it("does not inline attribute names in the policy statements", () => {
    const stack = readFileSync(STACK_PATH, "utf-8");
    const policySource = stack
      .split("\n")
      .filter((line) => !line.trimStart().startsWith("*") && !line.trimStart().startsWith("//"))
      .join("\n");
    for (const attribute of ["last_outcome_url", "last_status", "enabled", "params"]) {
      expect(policySource, `${attribute} must come from the mirror, not a literal`).not.toContain(
        `'${attribute}'`,
      );
    }
  });
});
