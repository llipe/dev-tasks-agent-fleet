/**
 * Unit tests for scope action input schemas — S-022, sub-task 22.12.
 *
 * Tests that Zod schemas accept valid input and reject invalid input.
 */

import { describe, it, expect } from "vitest";
import {
  SetSubjectEnabledSchema,
  SetSubjectParamsSchema,
  AddSubjectToAgentSchema,
} from "./scope.js";

describe("scope action schemas", () => {
  describe("SetSubjectEnabledSchema", () => {
    it("accepts valid input", () => {
      const result = SetSubjectEnabledSchema.safeParse({
        subjectId: "owner/repo",
        agentName: "dep-updater",
        enabled: true,
      });
      expect(result.success).toBe(true);
      if (result.success) {
        expect(result.data.subjectId).toBe("owner/repo");
        expect(result.data.agentName).toBe("dep-updater");
        expect(result.data.enabled).toBe(true);
      }
    });

    it("accepts enabled=false", () => {
      const result = SetSubjectEnabledSchema.safeParse({
        subjectId: "owner/repo",
        agentName: "dep-updater",
        enabled: false,
      });
      expect(result.success).toBe(true);
    });

    it("rejects missing subjectId", () => {
      const result = SetSubjectEnabledSchema.safeParse({
        agentName: "dep-updater",
        enabled: true,
      });
      expect(result.success).toBe(false);
    });

    it("rejects empty subjectId", () => {
      const result = SetSubjectEnabledSchema.safeParse({
        subjectId: "",
        agentName: "dep-updater",
        enabled: true,
      });
      expect(result.success).toBe(false);
    });

    it("rejects missing agentName", () => {
      const result = SetSubjectEnabledSchema.safeParse({
        subjectId: "owner/repo",
        enabled: true,
      });
      expect(result.success).toBe(false);
    });

    it("rejects empty agentName", () => {
      const result = SetSubjectEnabledSchema.safeParse({
        subjectId: "owner/repo",
        agentName: "",
        enabled: true,
      });
      expect(result.success).toBe(false);
    });

    it("rejects missing enabled", () => {
      const result = SetSubjectEnabledSchema.safeParse({
        subjectId: "owner/repo",
        agentName: "dep-updater",
      });
      expect(result.success).toBe(false);
    });

    it("rejects non-boolean enabled", () => {
      const result = SetSubjectEnabledSchema.safeParse({
        subjectId: "owner/repo",
        agentName: "dep-updater",
        enabled: "true",
      });
      expect(result.success).toBe(false);
    });

    it("parses from unknown (untyped input)", () => {
      const unknownInput: unknown = {
        subjectId: "owner/repo",
        agentName: "dep-updater",
        enabled: true,
      };
      const result = SetSubjectEnabledSchema.safeParse(unknownInput);
      expect(result.success).toBe(true);
    });
  });

  describe("SetSubjectParamsSchema", () => {
    it("accepts valid input with params", () => {
      const result = SetSubjectParamsSchema.safeParse({
        subjectId: "owner/repo",
        agentName: "dep-updater",
        params: { allow_fixes: true, max_fix_attempts: 3 },
      });
      expect(result.success).toBe(true);
      if (result.success) {
        expect(result.data.params).toEqual({ allow_fixes: true, max_fix_attempts: 3 });
      }
    });

    it("accepts empty params", () => {
      const result = SetSubjectParamsSchema.safeParse({
        subjectId: "owner/repo",
        agentName: "dep-updater",
        params: {},
      });
      expect(result.success).toBe(true);
    });

    it("rejects missing params", () => {
      const result = SetSubjectParamsSchema.safeParse({
        subjectId: "owner/repo",
        agentName: "dep-updater",
      });
      expect(result.success).toBe(false);
    });

    it("rejects non-object params", () => {
      const result = SetSubjectParamsSchema.safeParse({
        subjectId: "owner/repo",
        agentName: "dep-updater",
        params: "not an object",
      });
      expect(result.success).toBe(false);
    });

    it("rejects missing subjectId", () => {
      const result = SetSubjectParamsSchema.safeParse({
        agentName: "dep-updater",
        params: {},
      });
      expect(result.success).toBe(false);
    });

    it("rejects empty agentName", () => {
      const result = SetSubjectParamsSchema.safeParse({
        subjectId: "owner/repo",
        agentName: "",
        params: {},
      });
      expect(result.success).toBe(false);
    });

    it("parses from unknown (untyped input)", () => {
      const unknownInput: unknown = {
        subjectId: "owner/repo",
        agentName: "dep-updater",
        params: { allow_fixes: false },
      };
      const result = SetSubjectParamsSchema.safeParse(unknownInput);
      expect(result.success).toBe(true);
    });
  });

  describe("AddSubjectToAgentSchema", () => {
    it("accepts valid input", () => {
      const result = AddSubjectToAgentSchema.safeParse({
        subjectId: "owner/repo",
        agentName: "dep-updater",
      });
      expect(result.success).toBe(true);
      if (result.success) {
        expect(result.data.enabled).toBe(true); // default
      }
    });

    it("accepts explicit enabled=false", () => {
      const result = AddSubjectToAgentSchema.safeParse({
        subjectId: "owner/repo",
        agentName: "dep-updater",
        enabled: false,
      });
      expect(result.success).toBe(true);
      if (result.success) {
        expect(result.data.enabled).toBe(false);
      }
    });

    it("defaults enabled to true", () => {
      const result = AddSubjectToAgentSchema.safeParse({
        subjectId: "owner/repo",
        agentName: "dep-updater",
      });
      expect(result.success).toBe(true);
      if (result.success) {
        expect(result.data.enabled).toBe(true);
      }
    });

    it("rejects missing subjectId", () => {
      const result = AddSubjectToAgentSchema.safeParse({
        agentName: "dep-updater",
      });
      expect(result.success).toBe(false);
    });

    it("rejects empty subjectId", () => {
      const result = AddSubjectToAgentSchema.safeParse({
        subjectId: "",
        agentName: "dep-updater",
      });
      expect(result.success).toBe(false);
    });

    it("rejects missing agentName", () => {
      const result = AddSubjectToAgentSchema.safeParse({
        subjectId: "owner/repo",
      });
      expect(result.success).toBe(false);
    });

    it("parses from unknown (untyped input)", () => {
      const unknownInput: unknown = {
        subjectId: "owner/repo",
        agentName: "dep-updater",
        enabled: true,
      };
      const result = AddSubjectToAgentSchema.safeParse(unknownInput);
      expect(result.success).toBe(true);
    });
  });

  describe("params validation with paramsSchemaFor", () => {
    it("dep-updater accepts valid params", () => {
      const result = SetSubjectParamsSchema.safeParse({
        subjectId: "owner/repo",
        agentName: "dep-updater",
        params: { allow_fixes: true, max_fix_attempts: 3 },
      });
      expect(result.success).toBe(true);
    });

    it("dep-updater rejects unknown keys via strict schema (checked in action)", () => {
      // Note: The Zod schema in the action allows any record — the strict
      // paramsSchemaFor validation is done in the action body, not the input schema.
      // This test verifies the action schema accepts the params object shape.
      const result = SetSubjectParamsSchema.safeParse({
        subjectId: "owner/repo",
        agentName: "dep-updater",
        params: { allow_fixes: true, unknown_key: "bad" },
      });
      // The base schema accepts this — it's z.record(z.unknown())
      expect(result.success).toBe(true);
    });
  });
});
