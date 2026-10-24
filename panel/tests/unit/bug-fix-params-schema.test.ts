import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { AnySchema } from "ajv";
import { describe, expect, it } from "vitest";
import { validateParams } from "@/lib/schema/validate";

// L1 — S-184 (#366) TC-184-07 and the 5.9 edge cases: the boundary table for
// the bug-fix params_schema (spec §5.2 v2.0) through the panel's own Ajv path.
// The schema is the shared contract fixture; the L2.5 seed test proves the
// seeded row deep-equals it, and the agent's test_params.py uses the same
// fixture, so the panel and the agent enforce identical bounds (D-82).

const FIXTURE = fileURLToPath(
  new URL(
    "../../../agents/bug-fix/app/bugFix/tests/fixtures/contract/params_schema.json",
    import.meta.url,
  ),
);
const schema = JSON.parse(readFileSync(FIXTURE, "utf8")) as AnySchema;
const check = (extra: Record<string, unknown>) =>
  validateParams("bug-fix-l1", schema, { issue_number: 7, ...extra });

const ACCEPTED: Array<[string, unknown]> = [
  ["issue_number", 1],
  ["trigger_comment_id", 1],
  ["trigger_comment_id", 2 ** 40],
  ["max_turns", 5],
  ["max_turns", 100],
  ["cli_timeout_minutes", 5],
  ["cli_timeout_minutes", 45],
  ["run_budget_minutes", 10],
  ["run_budget_minutes", 55],
  ["max_code_files", 1],
  ["max_code_files", 50],
  ["max_code_lines", 10],
  ["max_code_lines", 2000],
  ["status_ready", "x"],
  ["status_ready", "a".repeat(100)],
  ["status_in_progress", "a".repeat(100)],
  ["status_in_review", "a".repeat(100)],
  ["project", "llipe/5"],
  ["project", "my-org/1234567"],
];

const REJECTED: Array<[string, unknown]> = [
  ["issue_number", 0],
  ["issue_number", "12"],
  ["trigger_comment_id", 0],
  ["trigger_comment_id", "123"],
  ["max_turns", 4],
  ["max_turns", 101],
  ["cli_timeout_minutes", 4],
  ["cli_timeout_minutes", 46],
  ["run_budget_minutes", 9],
  ["run_budget_minutes", 56],
  ["max_code_files", 0],
  ["max_code_files", 51],
  ["max_code_lines", 9],
  ["max_code_lines", 2001],
  ["status_ready", ""],
  ["status_ready", "a".repeat(101)],
  ["project", "llipe/0"],
  ["project", "llipe"],
  ["project", "a/b/1"],
  ["project", "llipe/12345678"],
  ["project", "under_score/1"],
];

describe("bug-fix params_schema boundary table (TC-184-07)", () => {
  it.each(ACCEPTED)("accepts %s = %j", (key, value) => {
    expect(check({ [key]: value })).toEqual({
      valid: true,
      params: { issue_number: 7, [key]: value },
    });
  });

  it.each(REJECTED)("rejects %s = %j", (key, value) => {
    const res = check({ [key]: value });
    expect(res.valid).toBe(false);
    if (!res.valid) expect(res.errors.map((e) => e.instancePath)).toContain(`/${key}`);
  });

  it("requires issue_number and nothing else", () => {
    expect(validateParams("bug-fix-l1", schema, {}).valid).toBe(false);
    expect(validateParams("bug-fix-l1", schema, { issue_number: 1 }).valid).toBe(true);
  });
});
