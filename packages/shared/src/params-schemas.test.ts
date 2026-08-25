import { describe, it, expect } from "vitest";
import { PARAMS_SCHEMAS, paramsSchemaFor } from "./params-schemas.js";

describe("PARAMS_SCHEMAS", () => {
  const depUpdaterSchema = paramsSchemaFor("dep-updater");

  describe("registry", () => {
    it("has dep-updater registered", () => {
      expect(PARAMS_SCHEMAS["dep-updater"]).toBeDefined();
    });
  });

  describe("dep-updater schema", () => {
    it("accepts valid params", () => {
      const result = depUpdaterSchema.safeParse({
        allow_fixes: true,
        max_fix_attempts: 3,
      });
      expect(result.success).toBe(true);
    });

    it("accepts allow_fixes as false", () => {
      const result = depUpdaterSchema.safeParse({
        allow_fixes: false,
        max_fix_attempts: 1,
      });
      expect(result.success).toBe(true);
    });

    it("rejects unknown keys (strict mode)", () => {
      const result = depUpdaterSchema.safeParse({
        allow_fixes: true,
        max_fix_attempts: 3,
        evil_key: true,
      });
      expect(result.success).toBe(false);
    });

    it("rejects wrong type for allow_fixes", () => {
      const result = depUpdaterSchema.safeParse({
        allow_fixes: "yes",
        max_fix_attempts: 3,
      });
      expect(result.success).toBe(false);
    });

    it("rejects wrong type for max_fix_attempts (string)", () => {
      const result = depUpdaterSchema.safeParse({
        allow_fixes: true,
        max_fix_attempts: "three",
      });
      expect(result.success).toBe(false);
    });

    it("rejects max_fix_attempts below 1", () => {
      const result = depUpdaterSchema.safeParse({
        allow_fixes: true,
        max_fix_attempts: 0,
      });
      expect(result.success).toBe(false);
    });

    it("rejects max_fix_attempts above 5", () => {
      const result = depUpdaterSchema.safeParse({
        allow_fixes: true,
        max_fix_attempts: 6,
      });
      expect(result.success).toBe(false);
    });

    it("accepts max_fix_attempts at boundary 1", () => {
      const result = depUpdaterSchema.safeParse({
        allow_fixes: true,
        max_fix_attempts: 1,
      });
      expect(result.success).toBe(true);
    });

    it("accepts max_fix_attempts at boundary 5", () => {
      const result = depUpdaterSchema.safeParse({
        allow_fixes: true,
        max_fix_attempts: 5,
      });
      expect(result.success).toBe(true);
    });

    it("rejects non-integer max_fix_attempts", () => {
      const result = depUpdaterSchema.safeParse({
        allow_fixes: true,
        max_fix_attempts: 2.5,
      });
      expect(result.success).toBe(false);
    });
  });

  describe("paramsSchemaFor", () => {
    it("returns dep-updater schema for known agent", () => {
      const schema = paramsSchemaFor("dep-updater");
      const result = schema.safeParse({ allow_fixes: true, max_fix_attempts: 3 });
      expect(result.success).toBe(true);
    });

    it("returns empty strict object for unknown agent", () => {
      const schema = paramsSchemaFor("unknown-agent");
      // Should accept empty object
      const validResult = schema.safeParse({});
      expect(validResult.success).toBe(true);
      // Should reject any keys
      const invalidResult = schema.safeParse({ some_key: "value" });
      expect(invalidResult.success).toBe(false);
    });

    it("returns empty strict object for undefined", () => {
      const schema = paramsSchemaFor(undefined as unknown as string);
      const validResult = schema.safeParse({});
      expect(validResult.success).toBe(true);
    });
  });
});
