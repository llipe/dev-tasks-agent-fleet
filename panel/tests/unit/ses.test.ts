import { describe, expect, it, vi } from "vitest";
import {
  renderDigest,
  sendDigestEmail,
  SesSendFailedError,
  SES_SEND_FAILED,
  type DigestNotification,
} from "@/lib/aws/ses";

// Layer 1 — S-159 (#271): the digest renderer + SES sender. Pure render is
// exhaustively testable; the send is mocked at the SDK boundary (clientFactory).

const rows: DigestNotification[] = [
  {
    id: "1",
    kind: "run_failed",
    title: "Scheduled run failed",
    detail: "dependency-update · o/r · INVOCATION_FAILED",
    created_at: "2026-10-13T10:00:00Z",
  },
  {
    id: "2",
    kind: "pr_opened",
    title: "Scheduled run opened a pull request",
    detail: "o/r · https://github.com/o/r/pull/7",
    created_at: "2026-10-13T11:00:00Z",
  },
  {
    id: "3",
    kind: "schedule_auto_paused",
    title: "Schedule auto-paused after 3 consecutive failures",
    detail: null,
    created_at: "2026-10-13T12:00:00Z",
  },
];

describe("renderDigest — webhook kinds (S-173/S-174)", () => {
  it("includes auto-disabled webhook rules in the email instead of dropping them", () => {
    const d = renderDigest([
      {
        id: "w",
        kind: "webhook_rule_auto_disabled",
        title: "Webhook rule disabled after 3 consecutive failures (gh-main / comment-fix)",
        detail: "INVOCATION_FAILED",
        created_at: "2026-10-20T12:00:00Z",
      },
    ]);
    expect(d.subject).toBe("Agent Fleet — 1 notification");
    expect(d.text).toContain("Auto-disabled webhook rules (1)");
    expect(d.text).toContain("gh-main / comment-fix");
  });

  it("lists a webhook run failure under Failed runs with its endpoint in the title", () => {
    const d = renderDigest([
      {
        id: "f",
        kind: "run_failed",
        title: "Webhook run failed · gh-main / comment-fix",
        detail: "security-analyst · o/r · INVOCATION_FAILED",
        created_at: "2026-10-20T12:00:00Z",
      },
    ]);
    expect(d.text).toContain("Failed runs (1)");
    expect(d.text).toContain("Webhook run failed · gh-main / comment-fix");
  });

  it("never drops a row: every row of any known kind appears exactly once", () => {
    const kinds: DigestNotification["kind"][] = [
      "run_failed",
      "schedule_auto_paused",
      "webhook_rule_auto_disabled",
      "pr_opened",
      "run_succeeded",
    ];
    const all = kinds.map((kind, i) => ({
      id: String(i),
      kind,
      title: `t-${kind}`,
      detail: null,
      created_at: "2026-10-20T12:00:00Z",
    }));
    const d = renderDigest(all);
    for (const k of kinds) expect(d.text.split(`t-${k}`).length - 1, k).toBe(1);
  });
});

describe("renderDigest (pure)", () => {
  it("groups by kind, counts, and includes a subject with the total", () => {
    const d = renderDigest(rows);
    expect(d.subject).toBe("Agent Fleet — 3 notifications");
    expect(d.text).toContain("Failed runs (1)");
    expect(d.text).toContain("Pull requests opened (1)");
    expect(d.text).toContain("Auto-paused schedules (1)");
    expect(d.text).toContain("Scheduled run failed — dependency-update · o/r · INVOCATION_FAILED");
    expect(d.html).toContain("<h3");
  });

  it("singularizes the subject for one row and omits empty kinds", () => {
    const d = renderDigest([rows[0]!]);
    expect(d.subject).toBe("Agent Fleet — 1 notification");
    expect(d.text).toContain("Failed runs (1)");
    expect(d.text).not.toContain("Pull requests opened");
  });

  it("escapes untrusted detail as text in the HTML (no markup injection)", () => {
    const d = renderDigest([
      {
        id: "x",
        kind: "pr_opened",
        title: "PR",
        detail: '<script>alert(1)</script> & "x"',
        created_at: "2026-10-13T00:00:00Z",
      },
    ]);
    expect(d.html).not.toContain("<script>");
    expect(d.html).toContain("&lt;script&gt;");
    expect(d.html).toContain("&amp;");
    expect(d.html).toContain("&quot;");
  });

  it("is total over an empty list", () => {
    const d = renderDigest([]);
    expect(d.subject).toBe("Agent Fleet — 0 notifications");
    expect(d.text).toContain("0 notable events");
  });
});

describe("sendDigestEmail (SES mocked at the SDK boundary)", () => {
  const rendered = renderDigest(rows);

  it("resolves when SES accepts, passing sender/recipient/subject to the command", async () => {
    const send = vi.fn().mockResolvedValue({ MessageId: "m-1" });
    await expect(
      sendDigestEmail(
        { rendered, sender: "fleet@example.com", recipient: "ops@example.com" },
        () => ({ send }),
      ),
    ).resolves.toBeUndefined();
    expect(send).toHaveBeenCalledTimes(1);
    const cmd = send.mock.calls[0]![0] as { input: Record<string, unknown> };
    expect(cmd.input.Source).toBe("fleet@example.com");
    expect((cmd.input.Destination as { ToAddresses: string[] }).ToAddresses).toEqual([
      "ops@example.com",
    ]);
  });

  it("throws SesSendFailedError on a send failure WITHOUT leaking content/recipient/cred material", async () => {
    const send = vi.fn().mockRejectedValue(new Error("550 ops@example.com rejected: body=secret"));
    const err = await sendDigestEmail(
      { rendered, sender: "fleet@example.com", recipient: "ops@example.com" },
      () => ({ send }),
    ).catch((e) => e);
    expect(err).toBeInstanceOf(SesSendFailedError);
    expect((err as SesSendFailedError).code).toBe(SES_SEND_FAILED);
    expect((err as Error).message).not.toContain("ops@example.com");
    expect((err as Error).message).not.toContain("secret");
    expect((err as Error).message).not.toContain("550");
  });
});
