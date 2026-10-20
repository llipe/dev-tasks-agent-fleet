/**
 * S-159 (#271) — the daily notification digest sender (SD-N6/N7/N8, FR19/FR21).
 *
 * Two concerns, deliberately split so the rendering is pure (L1-testable without
 * AWS) and only the thin send is SDK-bound:
 *
 *   renderDigest(rows)  — pure. Groups notable notifications by kind into a
 *                         plain-text + minimal-HTML body. No I/O, no secrets.
 *   sendDigestEmail(...) — thin SES SendEmailCommand wrapper reusing the panel's
 *                         single credential provider (lib/aws/credentials.ts —
 *                         Fly OIDC → STS, or the local chain; no static keys).
 *
 * A send failure is classified `SES_SEND_FAILED` and NEVER leaks the email body,
 * recipient address, or any credential/response material into the thrown
 * message (mirrors lib/aws/errors.ts). The caller leaves `emailed_at` null on
 * failure so the window retries next day rather than dropping (SD-N8 / R-S9).
 *
 * This module MUST stay free of Next.js imports so it is unit-testable in
 * isolation (SES mocked at the SDK boundary).
 *
 * Requires: @aws-sdk/client-ses
 * Env (read by the route, passed in here): NOTIFICATION_SENDER (SES-verified
 *   identity), NOTIFICATION_RECIPIENT.
 */

import { SESClient, SendEmailCommand } from "@aws-sdk/client-ses";
import { awsCredentials } from "./credentials";
import type { NotificationKind } from "@/lib/supabase/types";

export const SES_SEND_FAILED = "SES_SEND_FAILED" as const;

/** A send failure that carries no content, recipient, or credential material. */
export class SesSendFailedError extends Error {
  readonly code = SES_SEND_FAILED;
  readonly status = 502;
  constructor(options?: { cause?: unknown }) {
    super("Sending the notification digest via SES failed.", options);
    this.name = "SesSendFailedError";
  }
}

/** The subset of a notification row the digest needs (no PII beyond what the row holds). */
export interface DigestNotification {
  id: string;
  kind: NotificationKind;
  title: string;
  detail: string | null;
  created_at: string;
}

export interface RenderedDigest {
  subject: string;
  text: string;
  html: string;
}

const KIND_LABEL: Record<DigestNotification["kind"], string> = {
  run_failed: "Failed runs",
  schedule_auto_paused: "Auto-paused schedules",
  webhook_rule_auto_disabled: "Auto-disabled webhook rules",
  pr_opened: "Pull requests opened",
  run_succeeded: "Succeeded runs",
};

// Stable section order: problems first, then informational.
const KIND_ORDER: DigestNotification["kind"][] = [
  "run_failed",
  "schedule_auto_paused",
  "webhook_rule_auto_disabled",
  "pr_opened",
  "run_succeeded",
];

/** Minimal HTML escaping — the detail text is untrusted (PR titles, errors). */
function esc(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/**
 * Render the digest from the undelivered rows. Pure. Groups by kind in a fixed
 * order; a kind with no rows is omitted entirely. The caller only calls this
 * when there is at least one row (the empty-window case returns 204 upstream and
 * never renders — SD-N7), but render is still total over an empty list.
 */
export function renderDigest(rows: readonly DigestNotification[]): RenderedDigest {
  const count = rows.length;
  const subject = `Agent Fleet — ${count} notification${count === 1 ? "" : "s"}`;

  const textLines: string[] = [
    `Agent Fleet daily digest — ${count} notable event${count === 1 ? "" : "s"}.`,
    "",
  ];
  const htmlParts: string[] = [
    `<h2 style="font:600 16px system-ui,sans-serif">Agent Fleet daily digest</h2>`,
    `<p style="font:14px system-ui,sans-serif;color:#555">${count} notable event${count === 1 ? "" : "s"}.</p>`,
  ];

  for (const kind of KIND_ORDER) {
    const group = rows.filter((r) => r.kind === kind);
    if (group.length === 0) continue;

    textLines.push(`${KIND_LABEL[kind]} (${group.length})`);
    htmlParts.push(
      `<h3 style="font:600 14px system-ui,sans-serif;margin:16px 0 4px">${esc(KIND_LABEL[kind])} (${group.length})</h3><ul style="font:13px system-ui,sans-serif;padding-left:18px">`,
    );
    for (const r of group) {
      const line = r.detail ? `${r.title} — ${r.detail}` : r.title;
      textLines.push(`  • ${line}`);
      // Untrusted detail rendered as text only (escaped) — no links, no markup.
      htmlParts.push(`<li>${esc(line)}</li>`);
    }
    textLines.push("");
    htmlParts.push(`</ul>`);
  }

  return { subject, text: textLines.join("\n"), html: htmlParts.join("") };
}

export interface SendDigestInput {
  rendered: RenderedDigest;
  sender: string;
  recipient: string;
  region?: string;
}

/**
 * Send the rendered digest via SES. Resolves on an accepted send (the caller
 * then marks emailed_at), throws `SesSendFailedError` on any SES/transport
 * failure (the caller leaves emailed_at null to retry next day). The thrown
 * error carries no content, recipient, or credential material.
 *
 * Accepts an injectable client factory for unit testing (SES mocked at the SDK
 * boundary); production uses the default SESClient with the shared provider.
 */
export async function sendDigestEmail(
  input: SendDigestInput,
  clientFactory: () => Pick<SESClient, "send"> = () =>
    new SESClient({
      region: input.region ?? process.env.AWS_REGION ?? "us-east-1",
      credentials: awsCredentials,
    }),
): Promise<void> {
  const client = clientFactory();
  try {
    await client.send(
      new SendEmailCommand({
        Source: input.sender,
        Destination: { ToAddresses: [input.recipient] },
        Message: {
          Subject: { Data: input.rendered.subject, Charset: "UTF-8" },
          Body: {
            Text: { Data: input.rendered.text, Charset: "UTF-8" },
            Html: { Data: input.rendered.html, Charset: "UTF-8" },
          },
        },
      }) as Parameters<SESClient["send"]>[0],
    );
  } catch (err) {
    // Never surface the SES error message/response (may echo address/body).
    throw new SesSendFailedError({ cause: err });
  }
}
