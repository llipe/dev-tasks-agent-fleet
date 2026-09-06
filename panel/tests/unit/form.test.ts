import { describe, expect, it } from "vitest";
import { buildFieldDescriptors, type FieldDescriptor } from "@/lib/schema/form";

/**
 * S-113 (#126) — params_schema -> field-descriptor mapping (task 2.2, AC11).
 *
 * SD8: no generic JSON-Schema form library. The actual need is small:
 *   enum -> select, boolean -> toggle, bounded integer -> number,
 *   string -> text. Everything else -> a disabled field with a visible
 *   "unsupported type" note (parameters never vanish silently, AC4).
 */

function byName(fields: FieldDescriptor[], name: string): FieldDescriptor {
  const f = fields.find((x) => x.name === name);
  if (!f) throw new Error(`no field ${name}`);
  return f;
}

const DEP_UPDATE_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["fix_mode"],
  properties: {
    fix_mode: {
      type: "string",
      title: "Fix mode",
      description: "audit_only reports findings. llm_fix attempts a fix.",
      enum: ["audit_only", "llm_fix"],
      default: "audit_only",
    },
    fail_on_findings: {
      type: "boolean",
      title: "Fail if findings exist",
      description: "Only applies in audit_only mode.",
      default: true,
    },
    max_fix_attempts: {
      type: "integer",
      title: "Max LLM agent attempts",
      minimum: 0,
      maximum: 5,
      default: 3,
    },
    base_branch: {
      type: "string",
      title: "PR base branch",
      default: "main",
    },
  },
};

describe("buildFieldDescriptors — the dependency-update schema (AC11)", () => {
  const fields = buildFieldDescriptors(DEP_UPDATE_SCHEMA);

  it("produces exactly four fields in schema-property order", () => {
    expect(fields.map((f) => f.name)).toEqual([
      "fix_mode",
      "fail_on_findings",
      "max_fix_attempts",
      "base_branch",
    ]);
  });

  it("fix_mode (enum) -> select control with the enum options", () => {
    const f = byName(fields, "fix_mode");
    expect(f.control).toBe("select");
    expect(f.options).toEqual(["audit_only", "llm_fix"]);
    expect(f.label).toBe("Fix mode");
    expect(f.default).toBe("audit_only");
    expect(f.required).toBe(true);
  });

  it("fail_on_findings (boolean) -> toggle control", () => {
    const f = byName(fields, "fail_on_findings");
    expect(f.control).toBe("toggle");
    expect(f.default).toBe(true);
    expect(f.required).toBe(false);
  });

  it("max_fix_attempts (bounded integer) -> number control carrying min/max", () => {
    const f = byName(fields, "max_fix_attempts");
    expect(f.control).toBe("number");
    expect(f.min).toBe(0);
    expect(f.max).toBe(5);
    expect(f.default).toBe(3);
  });

  it("base_branch (string) -> text control", () => {
    const f = byName(fields, "base_branch");
    expect(f.control).toBe("text");
    expect(f.default).toBe("main");
  });
});

describe("buildFieldDescriptors — control mapping matrix", () => {
  it("integer without bounds -> number with undefined min/max", () => {
    const [f] = buildFieldDescriptors({
      type: "object",
      properties: { n: { type: "integer" } },
    });
    expect(f.control).toBe("number");
    expect(f.min).toBeUndefined();
    expect(f.max).toBeUndefined();
  });

  it("number (float) type -> number control", () => {
    const [f] = buildFieldDescriptors({
      type: "object",
      properties: { ratio: { type: "number", minimum: 0, maximum: 1 } },
    });
    expect(f.control).toBe("number");
    expect(f.min).toBe(0);
    expect(f.max).toBe(1);
  });

  it("string with an enum -> select (enum wins over the string base type)", () => {
    const [f] = buildFieldDescriptors({
      type: "object",
      properties: { color: { type: "string", enum: ["red", "green"] } },
    });
    expect(f.control).toBe("select");
    expect(f.options).toEqual(["red", "green"]);
  });
});

describe("buildFieldDescriptors — unsupported types (AC4, never vanish)", () => {
  it("oneOf -> unsupported control, disabled, with a note", () => {
    const [f] = buildFieldDescriptors({
      type: "object",
      properties: { x: { oneOf: [{ type: "string" }, { type: "number" }] } },
    });
    expect(f.control).toBe("unsupported");
    expect(f.disabled).toBe(true);
    expect(f.note).toMatch(/unsupported/i);
  });

  it("nested object -> unsupported control, disabled, with a note", () => {
    const [f] = buildFieldDescriptors({
      type: "object",
      properties: { cfg: { type: "object", properties: { a: { type: "string" } } } },
    });
    expect(f.control).toBe("unsupported");
    expect(f.disabled).toBe(true);
    expect(f.note).toMatch(/unsupported/i);
  });

  it("array -> unsupported control, disabled", () => {
    const [f] = buildFieldDescriptors({
      type: "object",
      properties: { tags: { type: "array", items: { type: "string" } } },
    });
    expect(f.control).toBe("unsupported");
    expect(f.disabled).toBe(true);
  });

  it("a property with no recognizable type -> unsupported, never dropped", () => {
    const fields = buildFieldDescriptors({
      type: "object",
      properties: { weird: { description: "no type at all" } },
    });
    expect(fields).toHaveLength(1);
    expect(fields[0].control).toBe("unsupported");
  });
});

describe("buildFieldDescriptors — labels, defaults, required", () => {
  it("missing title falls back to the property key name", () => {
    const [f] = buildFieldDescriptors({
      type: "object",
      properties: { some_key: { type: "string" } },
    });
    expect(f.label).toBe("some_key");
  });

  it("propagates description as help text", () => {
    const [f] = buildFieldDescriptors({
      type: "object",
      properties: { k: { type: "string", title: "K", description: "help me" } },
    });
    expect(f.help).toBe("help me");
  });

  it("marks required fields from the schema's required array", () => {
    const fields = buildFieldDescriptors({
      type: "object",
      required: ["a"],
      properties: { a: { type: "string" }, b: { type: "string" } },
    });
    expect(byName(fields, "a").required).toBe(true);
    expect(byName(fields, "b").required).toBe(false);
  });

  it("default is undefined when the schema omits it", () => {
    const [f] = buildFieldDescriptors({
      type: "object",
      properties: { k: { type: "string" } },
    });
    expect(f.default).toBeUndefined();
  });
});

describe("buildFieldDescriptors — empty schema (edge)", () => {
  it("an empty {} schema -> no fields", () => {
    expect(buildFieldDescriptors({})).toEqual([]);
  });

  it("a schema with an empty properties object -> no fields", () => {
    expect(buildFieldDescriptors({ type: "object", properties: {} })).toEqual([]);
  });
});
