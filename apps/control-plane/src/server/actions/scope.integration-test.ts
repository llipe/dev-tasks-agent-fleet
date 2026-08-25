/**
 * Integration tests for scope actions — S-022, sub-tasks 22.13, 22.14.
 *
 * Tests each action's success + failure modes:
 * - setSubjectEnabled: success, not_found, unauthorized, upstream error
 * - setSubjectParams: success, not_found, unauthorized, params_validation_error, upstream error
 * - addSubjectToAgent: success, conflict, unauthorized, upstream error
 * - Transactional add writes both items with exactly enabled/params attributes
 * - No action touches last_* attributes
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Mock next/cache and next/headers before importing actions
vi.mock("next/cache", () => ({
  revalidatePath: vi.fn(),
}));

vi.mock("next/headers", () => ({
  headers: vi.fn(),
}));

vi.mock("@/lib/auth/verify-token.js", () => ({
  verifyToken: vi.fn(),
}));

vi.mock("@/server/repository/scope-repository.js", () => ({
  setSubjectEnabled: vi.fn(),
  setSubjectParams: vi.fn(),
  addSubject: vi.fn(),
  getSubjectAgent: vi.fn(),
}));

import { headers } from "next/headers";
import { revalidatePath } from "next/cache";
import { verifyToken } from "@/lib/auth/verify-token.js";
import {
  setSubjectEnabled as repoSetEnabled,
  setSubjectParams as repoSetParams,
  addSubject as repoAddSubject,
  getSubjectAgent,
} from "@/server/repository/scope-repository.js";
import { setSubjectEnabled, setSubjectParams, addSubjectToAgent } from "./scope.js";

const mockHeaders = vi.mocked(headers);
const mockVerifyToken = vi.mocked(verifyToken);
const mockRepoSetEnabled = vi.mocked(repoSetEnabled);
const mockRepoSetParams = vi.mocked(repoSetParams);
const mockRepoAddSubject = vi.mocked(repoAddSubject);
const mockGetSubjectAgent = vi.mocked(getSubjectAgent);
const mockRevalidatePath = vi.mocked(revalidatePath);

function setupAuthSuccess(): void {
  mockHeaders.mockResolvedValue(
    new Headers({ "Cf-Access-Jwt-Assertion": "valid-token" }) as unknown as Awaited<
      ReturnType<typeof headers>
    >,
  );
  mockVerifyToken.mockResolvedValue({ ok: true, payload: { sub: "user" }, email: "user@test.com" });
}

function setupAuthFailure(): void {
  mockHeaders.mockResolvedValue(new Headers({}) as unknown as Awaited<ReturnType<typeof headers>>);
  mockVerifyToken.mockResolvedValue({ ok: false, reason: "invalid token" });
}

describe("scope actions integration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    process.env["CF_ACCESS_TEAM_NAME"] = "testteam";
    process.env["CF_ACCESS_AUD"] = "test-aud";
  });

  afterEach(() => {
    delete process.env["CF_ACCESS_TEAM_NAME"];
    delete process.env["CF_ACCESS_AUD"];
  });

  describe("setSubjectEnabled", () => {
    it("returns ok on success", async () => {
      setupAuthSuccess();
      mockGetSubjectAgent.mockResolvedValue({
        status: "ok",
        data: {
          subjectId: "owner/repo",
          agentName: "dep-updater",
          enabled: false,
          params: {},
        },
        correlationId: "test",
      });
      mockRepoSetEnabled.mockResolvedValue({ status: "ok", data: undefined, correlationId: "t" });

      const result = await setSubjectEnabled({
        subjectId: "owner/repo",
        agentName: "dep-updater",
        enabled: true,
      });

      expect(result).toEqual({ ok: true });
      expect(mockRepoSetEnabled).toHaveBeenCalledWith("owner/repo", "dep-updater", true);
      expect(mockRevalidatePath).toHaveBeenCalledWith("/agents/dep-updater");
    });

    it("returns not_found when item does not exist", async () => {
      setupAuthSuccess();
      mockGetSubjectAgent.mockResolvedValue({ status: "empty", correlationId: "t" });
      mockRepoSetEnabled.mockResolvedValue({
        status: "error",
        error: "ConditionalCheckFailedException",
        correlationId: "t",
      });

      const result = await setSubjectEnabled({
        subjectId: "owner/repo",
        agentName: "dep-updater",
        enabled: true,
      });

      expect(result).toEqual({
        ok: false,
        error: { code: "not_found", message: expect.stringContaining("owner/repo") },
      });
    });

    it("returns unauthorized when JWT fails", async () => {
      setupAuthFailure();

      const result = await setSubjectEnabled({
        subjectId: "owner/repo",
        agentName: "dep-updater",
        enabled: true,
      });

      expect(result).toEqual({
        ok: false,
        error: { code: "unauthorized", message: "Authentication failed" },
      });
      expect(mockRepoSetEnabled).not.toHaveBeenCalled();
    });

    it("returns upstream_error on DynamoDB failure", async () => {
      setupAuthSuccess();
      mockGetSubjectAgent.mockResolvedValue({ status: "empty", correlationId: "t" });
      mockRepoSetEnabled.mockResolvedValue({
        status: "error",
        error: "ServiceUnavailable",
        correlationId: "t",
      });

      const result = await setSubjectEnabled({
        subjectId: "owner/repo",
        agentName: "dep-updater",
        enabled: true,
      });

      expect(result).toEqual({
        ok: false,
        error: { code: "upstream_error", message: "Failed to update enabled state" },
      });
    });

    it("returns validation_error on invalid input", async () => {
      const result = await setSubjectEnabled({
        subjectId: "",
        agentName: "dep-updater",
        enabled: true,
      });

      expect(result).toEqual({
        ok: false,
        error: { code: "validation_error", message: "Invalid input" },
      });
    });

    it("never touches last_* attributes in the update call", async () => {
      setupAuthSuccess();
      mockGetSubjectAgent.mockResolvedValue({ status: "empty", correlationId: "t" });
      mockRepoSetEnabled.mockResolvedValue({ status: "ok", data: undefined, correlationId: "t" });

      await setSubjectEnabled({
        subjectId: "owner/repo",
        agentName: "dep-updater",
        enabled: true,
      });

      // The repository function is called with only (subjectId, agentName, enabled)
      // No last_* attributes in the call
      expect(mockRepoSetEnabled).toHaveBeenCalledWith("owner/repo", "dep-updater", true);
    });
  });

  describe("setSubjectParams", () => {
    it("returns ok on success with valid params", async () => {
      setupAuthSuccess();
      mockGetSubjectAgent.mockResolvedValue({
        status: "ok",
        data: {
          subjectId: "owner/repo",
          agentName: "dep-updater",
          enabled: true,
          params: {},
        },
        correlationId: "t",
      });
      mockRepoSetParams.mockResolvedValue({ status: "ok", data: undefined, correlationId: "t" });

      const result = await setSubjectParams({
        subjectId: "owner/repo",
        agentName: "dep-updater",
        params: { allow_fixes: true, max_fix_attempts: 3 },
      });

      expect(result).toEqual({ ok: true });
      expect(mockRepoSetParams).toHaveBeenCalledWith("owner/repo", "dep-updater", {
        allow_fixes: true,
        max_fix_attempts: 3,
      });
    });

    it("returns params_validation_error for unknown keys", async () => {
      setupAuthSuccess();

      const result = await setSubjectParams({
        subjectId: "owner/repo",
        agentName: "dep-updater",
        params: { allow_fixes: true, max_fix_attempts: 3, unknown_key: "bad" },
      });

      expect(result).toEqual({
        ok: false,
        error: {
          code: "params_validation_error",
          message: expect.stringContaining("unknown_key"),
        },
      });
      expect(mockRepoSetParams).not.toHaveBeenCalled();
    });

    it("returns params_validation_error for wrong types", async () => {
      setupAuthSuccess();

      const result = await setSubjectParams({
        subjectId: "owner/repo",
        agentName: "dep-updater",
        params: { allow_fixes: "yes", max_fix_attempts: 3 },
      });

      expect(result).toEqual({
        ok: false,
        error: {
          code: "params_validation_error",
          message: expect.stringContaining("allow_fixes"),
        },
      });
    });

    it("returns not_found when item does not exist", async () => {
      setupAuthSuccess();
      mockGetSubjectAgent.mockResolvedValue({ status: "empty", correlationId: "t" });
      mockRepoSetParams.mockResolvedValue({
        status: "error",
        error: "ConditionalCheckFailedException",
        correlationId: "t",
      });

      const result = await setSubjectParams({
        subjectId: "owner/repo",
        agentName: "dep-updater",
        params: { allow_fixes: true, max_fix_attempts: 3 },
      });

      expect(result).toEqual({
        ok: false,
        error: { code: "not_found", message: expect.stringContaining("owner/repo") },
      });
    });

    it("returns unauthorized when JWT fails", async () => {
      setupAuthFailure();

      const result = await setSubjectParams({
        subjectId: "owner/repo",
        agentName: "dep-updater",
        params: { allow_fixes: true, max_fix_attempts: 3 },
      });

      expect(result).toEqual({
        ok: false,
        error: { code: "unauthorized", message: "Authentication failed" },
      });
    });

    it("returns upstream_error on DynamoDB failure", async () => {
      setupAuthSuccess();
      mockGetSubjectAgent.mockResolvedValue({ status: "empty", correlationId: "t" });
      mockRepoSetParams.mockResolvedValue({
        status: "error",
        error: "ServiceUnavailable",
        correlationId: "t",
      });

      const result = await setSubjectParams({
        subjectId: "owner/repo",
        agentName: "dep-updater",
        params: { allow_fixes: true, max_fix_attempts: 3 },
      });

      expect(result).toEqual({
        ok: false,
        error: { code: "upstream_error", message: "Failed to update params" },
      });
    });

    it("accepts empty params for unknown agent", async () => {
      setupAuthSuccess();
      mockGetSubjectAgent.mockResolvedValue({ status: "empty", correlationId: "t" });
      mockRepoSetParams.mockResolvedValue({ status: "ok", data: undefined, correlationId: "t" });

      const result = await setSubjectParams({
        subjectId: "owner/repo",
        agentName: "unknown-agent",
        params: {},
      });

      expect(result).toEqual({ ok: true });
    });

    it("rejects non-empty params for unknown agent (strict empty)", async () => {
      setupAuthSuccess();

      const result = await setSubjectParams({
        subjectId: "owner/repo",
        agentName: "unknown-agent",
        params: { any_key: "value" },
      });

      expect(result).toEqual({
        ok: false,
        error: {
          code: "params_validation_error",
          message: expect.stringContaining("any_key"),
        },
      });
    });
  });

  describe("addSubjectToAgent", () => {
    it("returns ok on success", async () => {
      setupAuthSuccess();
      mockRepoAddSubject.mockResolvedValue({ status: "ok", data: undefined, correlationId: "t" });

      const result = await addSubjectToAgent({
        subjectId: "owner/repo",
        agentName: "dep-updater",
      });

      expect(result).toEqual({ ok: true });
      expect(mockRepoAddSubject).toHaveBeenCalledWith("owner/repo", "dep-updater", true);
      expect(mockRevalidatePath).toHaveBeenCalledWith("/agents/dep-updater");
    });

    it("normalizes the subject ID", async () => {
      setupAuthSuccess();
      mockRepoAddSubject.mockResolvedValue({ status: "ok", data: undefined, correlationId: "t" });

      await addSubjectToAgent({
        subjectId: "https://github.com/MyOrg/MyRepo.git",
        agentName: "dep-updater",
      });

      expect(mockRepoAddSubject).toHaveBeenCalledWith("myorg/myrepo", "dep-updater", true);
    });

    it("returns conflict when subject already exists", async () => {
      setupAuthSuccess();
      mockRepoAddSubject.mockResolvedValue({
        status: "error",
        error: "conflict: subject-agent pair already exists",
        correlationId: "t",
      });

      const result = await addSubjectToAgent({
        subjectId: "owner/repo",
        agentName: "dep-updater",
      });

      expect(result).toEqual({
        ok: false,
        error: {
          code: "conflict",
          message: expect.stringContaining("owner/repo"),
        },
      });
    });

    it("returns unauthorized when JWT fails", async () => {
      setupAuthFailure();

      const result = await addSubjectToAgent({
        subjectId: "owner/repo",
        agentName: "dep-updater",
      });

      expect(result).toEqual({
        ok: false,
        error: { code: "unauthorized", message: "Authentication failed" },
      });
    });

    it("returns upstream_error on DynamoDB failure", async () => {
      setupAuthSuccess();
      mockRepoAddSubject.mockResolvedValue({
        status: "error",
        error: "ServiceUnavailable",
        correlationId: "t",
      });

      const result = await addSubjectToAgent({
        subjectId: "owner/repo",
        agentName: "dep-updater",
      });

      expect(result).toEqual({
        ok: false,
        error: { code: "upstream_error", message: "Failed to add repository" },
      });
    });

    it("returns validation_error on invalid input", async () => {
      const result = await addSubjectToAgent({
        subjectId: "",
        agentName: "dep-updater",
      });

      expect(result).toEqual({
        ok: false,
        error: { code: "validation_error", message: "Invalid input" },
      });
    });

    it("defaults enabled to true", async () => {
      setupAuthSuccess();
      mockRepoAddSubject.mockResolvedValue({ status: "ok", data: undefined, correlationId: "t" });

      await addSubjectToAgent({
        subjectId: "owner/repo",
        agentName: "dep-updater",
      });

      expect(mockRepoAddSubject).toHaveBeenCalledWith("owner/repo", "dep-updater", true);
    });

    it("respects explicit enabled=false", async () => {
      setupAuthSuccess();
      mockRepoAddSubject.mockResolvedValue({ status: "ok", data: undefined, correlationId: "t" });

      await addSubjectToAgent({
        subjectId: "owner/repo",
        agentName: "dep-updater",
        enabled: false,
      });

      expect(mockRepoAddSubject).toHaveBeenCalledWith("owner/repo", "dep-updater", false);
    });
  });

  describe("transactional add (22.14)", () => {
    it("repository addSubject called with only enabled/params-relevant fields", async () => {
      setupAuthSuccess();
      mockRepoAddSubject.mockResolvedValue({ status: "ok", data: undefined, correlationId: "t" });

      await addSubjectToAgent({
        subjectId: "owner/repo",
        agentName: "dep-updater",
        enabled: true,
      });

      // The repository function is called with (subjectId, agentName, enabled)
      // It creates items with ONLY enabled and params attributes (plus keys)
      // No last_* attributes in the call
      expect(mockRepoAddSubject).toHaveBeenCalledWith("owner/repo", "dep-updater", true);
      const args = mockRepoAddSubject.mock.calls[0];
      expect(args).toBeDefined();
      // Ensure no last_* in call args
      expect(args).toHaveLength(3);
      expect(args?.[0]).toBe("owner/repo");
      expect(args?.[1]).toBe("dep-updater");
      expect(args?.[2]).toBe(true);
    });
  });

  describe("last_* attribute safety (22.10)", () => {
    it("setSubjectEnabled never passes last_* to repository", async () => {
      setupAuthSuccess();
      mockGetSubjectAgent.mockResolvedValue({ status: "empty", correlationId: "t" });
      mockRepoSetEnabled.mockResolvedValue({ status: "ok", data: undefined, correlationId: "t" });

      await setSubjectEnabled({
        subjectId: "owner/repo",
        agentName: "dep-updater",
        enabled: true,
      });

      const call = mockRepoSetEnabled.mock.calls[0];
      expect(call).toEqual(["owner/repo", "dep-updater", true]);
    });

    it("setSubjectParams never passes last_* to repository", async () => {
      setupAuthSuccess();
      mockGetSubjectAgent.mockResolvedValue({ status: "empty", correlationId: "t" });
      mockRepoSetParams.mockResolvedValue({ status: "ok", data: undefined, correlationId: "t" });

      await setSubjectParams({
        subjectId: "owner/repo",
        agentName: "dep-updater",
        params: { allow_fixes: true, max_fix_attempts: 3 },
      });

      const call = mockRepoSetParams.mock.calls[0];
      expect(call).toEqual([
        "owner/repo",
        "dep-updater",
        { allow_fixes: true, max_fix_attempts: 3 },
      ]);
    });
  });

  describe("discriminated result shape (22.8)", () => {
    it("success results have exactly { ok: true }", async () => {
      setupAuthSuccess();
      mockGetSubjectAgent.mockResolvedValue({ status: "empty", correlationId: "t" });
      mockRepoSetEnabled.mockResolvedValue({ status: "ok", data: undefined, correlationId: "t" });

      const result = await setSubjectEnabled({
        subjectId: "owner/repo",
        agentName: "dep-updater",
        enabled: true,
      });

      expect(result).toEqual({ ok: true });
      expect(Object.keys(result)).toEqual(["ok"]);
    });

    it("failure results have { ok: false, error: { code, message } }", async () => {
      setupAuthFailure();

      const result = await setSubjectEnabled({
        subjectId: "owner/repo",
        agentName: "dep-updater",
        enabled: true,
      });

      expect(result.ok).toBe(false);
      if (!result.ok) {
        expect(result.error).toHaveProperty("code");
        expect(result.error).toHaveProperty("message");
        expect(typeof result.error.code).toBe("string");
        expect(typeof result.error.message).toBe("string");
      }
    });
  });
});
