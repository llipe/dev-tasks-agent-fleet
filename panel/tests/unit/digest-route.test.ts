import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Issue #306 (2026-10-19 scope addition) — the notification digest route.
 *
 * The 2026-10-19 11:00Z production digest logged `send_failed` / `SES_SEND_FAILED`
 * with NO AWS error name, so the failure could not be diagnosed. This suite
 * pins the fix: the `send_failed` event carries the allowlisted AWS error
 * fields (aws_error/http/request_id) extracted from the SES error's `cause`,
 * and NEVER the recipient, sender, message body, or the SES message text.
 *
 * All externals are mocked: Supabase queries, auth, and the SES send.
 */

const q = vi.hoisted(() => ({
  getUndeliveredNotifications: vi.fn(),
  markNotificationsEmailed: vi.fn(),
}));
const auth = vi.hoisted(() => ({ authorizeInternalRequest: vi.fn() }));
const ses = vi.hoisted(() => ({ sendDigestEmail: vi.fn() }));

vi.mock("@/lib/supabase/server", () => ({ createServerClient: () => ({ __mock: "client" }) }));
vi.mock("@/lib/supabase/queries", () => q);
vi.mock("@/lib/auth/internal-secret", () => auth);
// Keep the real renderDigest + SesSendFailedError + SES_SEND_FAILED; mock only
// the SDK-bound send.
vi.mock("@/lib/aws/ses", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/aws/ses")>();
  return { ...actual, sendDigestEmail: ses.sendDigestEmail };
});

import { POST } from "@/app/api/internal/notifications/digest/route";
import { SesSendFailedError } from "@/lib/aws/ses";

const SENDER = "fleet-sender@example.com";
const RECIPIENT = "ops-recipient@example.com";

function notification(over: Record<string, unknown> = {}) {
  return {
    id: "n-1",
    kind: "run_failed",
    title: "Scheduled run failed",
    detail: "dependency-update · o/r · INVOCATION_FAILED",
    created_at: "2026-10-19T10:00:00Z",
    ...over,
  };
}

function digestRequest(): Request {
  return new Request("http://x/api/internal/notifications/digest", { method: "POST" });
}

const savedEnv = { ...process.env };

beforeEach(() => {
  vi.clearAllMocks();
  auth.authorizeInternalRequest.mockReturnValue({ ok: true });
  q.getUndeliveredNotifications.mockResolvedValue([notification()]);
  q.markNotificationsEmailed.mockResolvedValue(undefined);
  ses.sendDigestEmail.mockResolvedValue(undefined);
  process.env.NOTIFICATION_SENDER = SENDER;
  process.env.NOTIFICATION_RECIPIENT = RECIPIENT;
});

afterEach(() => {
  process.env = { ...savedEnv };
  vi.restoreAllMocks();
});

describe("digest route — AWS error name on send_failed (#306)", () => {
  it("adds aws_error/http/request_id, never the recipient/sender/body/message", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    const sesErr = Object.assign(
      new Error("550 ops-recipient@example.com rejected body=SENTINEL-DO-NOT-LOG"),
      { name: "MessageRejected", $metadata: { httpStatusCode: 400, requestId: "req-ses" } },
    );
    ses.sendDigestEmail.mockRejectedValue(new SesSendFailedError({ cause: sesErr }));

    const res = await POST(digestRequest());
    expect(res.status).toBe(502);

    const lines = error.mock.calls.map((c) => String(c[0]));
    const failed = lines.find((l) => l.includes('"event":"send_failed"'));
    expect(failed).toBeDefined();
    const parsed = JSON.parse(failed!);
    expect(parsed.error_code).toBe("SES_SEND_FAILED");
    expect(parsed.aws_error).toBe("MessageRejected");
    expect(parsed.http).toBe(400);
    expect(parsed.request_id).toBe("req-ses");

    // Security-negative: no captured log line carries the recipient, the
    // sender, or the SES message/body sentinel.
    const all = lines.join(" ");
    expect(all).not.toContain("SENTINEL-DO-NOT-LOG");
    expect(all).not.toContain(RECIPIENT);
    expect(all).not.toContain(SENDER);
    expect(all).not.toContain("550");
    // The window is NOT marked emailed on failure (retried next day).
    expect(q.markNotificationsEmailed).not.toHaveBeenCalled();
    error.mockRestore();
  });

  it("logs aws_error=unknown for a non-AWS send failure", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    ses.sendDigestEmail.mockRejectedValue(new SesSendFailedError({ cause: new Error("plain") }));
    const res = await POST(digestRequest());
    expect(res.status).toBe(502);
    const failed = error.mock.calls
      .map((c) => String(c[0]))
      .find((l) => l.includes('"event":"send_failed"'));
    expect(failed).toBeDefined();
    expect(JSON.parse(failed!).aws_error).toBe("unknown");
    error.mockRestore();
  });

  it("still returns 200 and marks emailed on a clean send (no regression)", async () => {
    const res = await POST(digestRequest());
    expect(res.status).toBe(200);
    expect(q.markNotificationsEmailed).toHaveBeenCalledTimes(1);
  });
});
