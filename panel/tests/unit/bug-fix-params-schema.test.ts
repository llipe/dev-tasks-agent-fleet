import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { AnySchema } from "ajv";
import { describe, expect, it } from "vitest";
import { buildFieldDescriptors } from "@/lib/schema/form";
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

  it("drives an invoke form with issue_number as the only required field (TC-184-17 support)", () => {
    // Automated support for the manual UI check (5.10), which stays manual.
    const fields = buildFieldDescriptors(schema);
    expect(fields.filter((f) => f.required).map((f) => f.name)).toEqual(["issue_number"]);
    expect(fields.find((f) => f.name === "issue_number")).toMatchObject({
      label: "Issue number",
      min: 1,
    });
    const names = fields.map((f) => f.name);
    for (const gone of ["select_labels", "assignee", "repo", "schedule"]) {
      expect(names).not.toContain(gone);
    }
    expect(fields.every((f) => !f.disabled)).toBe(true);
  });

  it("requires issue_number and nothing else", () => {
    expect(validateParams("bug-fix-l1", schema, {}).valid).toBe(false);
    expect(validateParams("bug-fix-l1", schema, { issue_number: 1 }).valid).toBe(true);
  });
});

// The shared accept/reject corpus. The agent's tests/unit/test_params_cases.py
// runs the same file through parse_params, so Ajv and Python must agree on
// every case (D-82). The corpus covers integral floats, astral-plane string
// length, `$` before a trailing newline, and non-ASCII digits.
interface CorpusCase {
  name: string;
  params: Record<string, unknown>;
  valid: boolean;
  key?: string;
}
const CORPUS = JSON.parse(
  readFileSync(
    fileURLToPath(
      new URL(
        "../../../agents/bug-fix/app/bugFix/tests/fixtures/contract/params_cases.json",
        import.meta.url,
      ),
    ),
    "utf8",
  ),
) as { cases: CorpusCase[]; unknown_keys: string[] };

describe("bug-fix params shared corpus (panel side, D-82)", () => {
  it.each(CORPUS.cases.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    const res = validateParams("bug-fix-l1", schema, c.params);
    expect(res.valid).toBe(c.valid);
    if (res.valid) {
      expect(res.params).toEqual(c.params);
      return;
    }
    // A missing required key is reported at the root with keyword `required`.
    const failing = res.errors.map((e) =>
      e.keyword === "required" ? "issue_number" : e.instancePath.split("/")[1],
    );
    expect(failing).toContain(c.key);
  });

  it.each(CORPUS.unknown_keys)(
    "rejects the unknown key %j (additionalProperties: false)",
    (key) => {
      const res = validateParams("bug-fix-l1", schema, { issue_number: 7, [key]: "SENTINEL" });
      expect(res.valid).toBe(false);
      if (!res.valid) expect(res.errors.map((e) => e.keyword)).toContain("additionalProperties");
    },
  );

  it("never forwards an unknown key, even next to valid params", () => {
    const res = validateParams("bug-fix-l1", schema, { issue_number: 7, __probe: { cmd: "x" } });
    expect(res).toMatchObject({ valid: false });
    expect(JSON.stringify(res)).not.toContain("cmd");
  });
});

describe("bug-fix params errors never echo a value", () => {
  const SENTINEL = "SENTINEL-VALUE-" + "q".repeat(120);
  const keys = Object.keys((schema as { properties: Record<string, unknown> }).properties);
  const inputs: Array<[string, unknown]> = keys.flatMap(
    (key): Array<[string, unknown]> => [
      [key, SENTINEL],
      [key, [SENTINEL]],
      [key, { v: SENTINEL }],
    ],
  );

  it.each(inputs)("%s = <sentinel %#>", (key, value) => {
    const res = validateParams("bug-fix-l1", schema, { issue_number: 7, [key]: value });
    expect(res.valid).toBe(false);
    if (res.valid) return;
    expect(res.errors.map((e) => e.instancePath)).toContain(`/${key}`);
    expect(JSON.stringify(res.errors)).not.toContain("SENTINEL");
  });

  it("an unknown key's error carries neither its value nor its name", () => {
    const res = validateParams("bug-fix-l1", schema, { issue_number: 7, SENTINEL_KEY: SENTINEL });
    expect(res.valid).toBe(false);
    expect(JSON.stringify(res)).not.toContain("SENTINEL");
  });
});
