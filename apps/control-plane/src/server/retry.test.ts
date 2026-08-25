import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { withRetry, _isRetryable } from "./retry.js";

describe("retry policy helper", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe("isRetryable", () => {
    it("retries ThrottlingException", () => {
      const error = Object.assign(new Error("throttled"), { name: "ThrottlingException" });
      expect(_isRetryable(error)).toBe(true);
    });

    it("retries TooManyRequestsException", () => {
      const error = Object.assign(new Error("too many"), { name: "TooManyRequestsException" });
      expect(_isRetryable(error)).toBe(true);
    });

    it("retries 5xx errors", () => {
      const error = { name: "InternalServerError", $metadata: { httpStatusCode: 500 } };
      expect(_isRetryable(error)).toBe(true);
    });

    it("retries 503 errors", () => {
      const error = { name: "ServiceUnavailable", $metadata: { httpStatusCode: 503 } };
      expect(_isRetryable(error)).toBe(true);
    });

    it("retries 429 errors (HTTP-level throttle)", () => {
      const error = { name: "SomeError", $metadata: { httpStatusCode: 429 } };
      expect(_isRetryable(error)).toBe(true);
    });

    it("does NOT retry ValidationException", () => {
      const error = Object.assign(new Error("invalid"), { name: "ValidationException" });
      expect(_isRetryable(error)).toBe(false);
    });

    it("does NOT retry AccessDeniedException", () => {
      const error = Object.assign(new Error("denied"), { name: "AccessDeniedException" });
      expect(_isRetryable(error)).toBe(false);
    });

    it("does NOT retry 400 errors", () => {
      const error = { name: "BadRequest", $metadata: { httpStatusCode: 400 } };
      expect(_isRetryable(error)).toBe(false);
    });

    it("does NOT retry ConditionalCheckFailedException", () => {
      const error = Object.assign(new Error("cond"), { name: "ConditionalCheckFailedException" });
      expect(_isRetryable(error)).toBe(false);
    });

    it("does NOT retry null", () => {
      expect(_isRetryable(null)).toBe(false);
    });

    it("does NOT retry non-objects", () => {
      expect(_isRetryable("string error")).toBe(false);
    });
  });

  describe("withRetry", () => {
    it("returns result on first success", async () => {
      const fn = vi.fn().mockResolvedValue("success");
      const result = await withRetry(fn);
      expect(result).toBe("success");
      expect(fn).toHaveBeenCalledTimes(1);
    });

    it("retries on throttle and succeeds", async () => {
      const throttleError = Object.assign(new Error("throttled"), {
        name: "ThrottlingException",
      });
      const fn = vi.fn().mockRejectedValueOnce(throttleError).mockResolvedValueOnce("success");

      const resultPromise = withRetry(fn, { baseDelayMs: 10, maxDelayMs: 50 });

      // Advance timers to allow the retry delay to pass
      await vi.advanceTimersByTimeAsync(100);

      const result = await resultPromise;
      expect(result).toBe("success");
      expect(fn).toHaveBeenCalledTimes(2);
    });

    it("throws ValidationException immediately without retry", async () => {
      const validationError = Object.assign(new Error("invalid"), {
        name: "ValidationException",
      });
      const fn = vi.fn().mockRejectedValue(validationError);

      await expect(withRetry(fn)).rejects.toThrow("invalid");
      expect(fn).toHaveBeenCalledTimes(1);
    });

    it("throws AccessDeniedException immediately without retry", async () => {
      const accessError = Object.assign(new Error("denied"), {
        name: "AccessDeniedException",
      });
      const fn = vi.fn().mockRejectedValue(accessError);

      await expect(withRetry(fn)).rejects.toThrow("denied");
      expect(fn).toHaveBeenCalledTimes(1);
    });

    it("throws after exhausting retries", async () => {
      vi.useRealTimers();
      const throttleError = Object.assign(new Error("throttled"), {
        name: "ThrottlingException",
      });
      const fn = vi.fn().mockRejectedValue(throttleError);

      await expect(withRetry(fn, { baseDelayMs: 1, maxDelayMs: 5, maxRetries: 2 })).rejects.toThrow(
        "throttled",
      );
      // Initial attempt + 2 retries = 3 calls
      expect(fn).toHaveBeenCalledTimes(3);
      vi.useFakeTimers();
    });

    it("retries 5xx then succeeds on next attempt", async () => {
      const serverError = Object.assign(new Error("internal"), {
        name: "InternalServerError",
        $metadata: { httpStatusCode: 500 },
      });
      const fn = vi
        .fn()
        .mockRejectedValueOnce(serverError)
        .mockRejectedValueOnce(serverError)
        .mockResolvedValueOnce("recovered");

      const resultPromise = withRetry(fn, { baseDelayMs: 10, maxDelayMs: 50, maxRetries: 3 });
      await vi.advanceTimersByTimeAsync(500);

      const result = await resultPromise;
      expect(result).toBe("recovered");
      expect(fn).toHaveBeenCalledTimes(3);
    });
  });
});
