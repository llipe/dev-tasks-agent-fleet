/**
 * S-159 (#271) — `POST /api/internal/notifications/digest` (SD-N6/N7/N8, FR19).
 *
 * The internal endpoint the daily `pg_cron` job (`scheduler-daily-digest`) calls
 * via `pg_net` (same shared secret as the fire endpoint). It:
 *
 *   1. authorizes fail-closed, constant-time (SD-A1) — NOT a session;
 *   2. selects `notifications where emailed_at is null` oldest-first;
 *   3. if empty → 204 and sends NOTHING (SD-N7, empty-window suppression, FR19);
 *   4. else renders a plain-text + minimal-HTML digest grouped by kind and
 *      sends it via SES (SD-N7, lib/aws/ses.ts, the shared OIDC credentials);
 *   5. ONLY on a confirmed send marks exactly those rows `emailed_at = now()`
 *      (SD-N8) — a send failure leaves them null so the window retries next day
 *      rather than dropping (R-S9), and returns 502.
 *
 * Recording knows nothing about email (SD-N8/channel-agnostic): this route is
 * one consumer of the `notifications` table; the panel feed is another.
 *
 * Route-segment config inline (never cached).
 */

import { NextResponse } from "next/server";

import { authorizeInternalRequest } from "@/lib/auth/internal-secret";
import { createServerClient } from "@/lib/supabase/server";
import { getUndeliveredNotifications, markNotificationsEmailed } from "@/lib/supabase/queries";
import { renderDigest, sendDigestEmail, SES_SEND_FAILED } from "@/lib/aws/ses";

export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";
export const runtime = "nodejs";

/** Secret-free structured log line (never logs the secret, recipient, or body). */
function logDigest(
  fields: { event: string; count?: number; error_code?: string },
  logger: Pick<Console, "info" | "error"> = console,
): void {
  const line = JSON.stringify({ at: "notification_digest", ...fields });
  if (fields.error_code) logger.error(line);
  else logger.info(line);
}

export async function POST(request: Request): Promise<NextResponse> {
  // 1. Authorize — fail-closed, constant-time, before ANY work (SD-A1).
  const auth = authorizeInternalRequest(request);
  if (!auth.ok) {
    logDigest({ event: "unauthorized", error_code: "UNAUTHORIZED" });
    return NextResponse.json({ error: "UNAUTHORIZED" }, { status: 401 });
  }

  const client = createServerClient();

  // 2. Select the undelivered window.
  const rows = await getUndeliveredNotifications(client);

  // 3. Empty window → 204, send nothing (SD-N7 / FR19).
  if (rows.length === 0) {
    logDigest({ event: "empty_window", count: 0 });
    return new NextResponse(null, { status: 204 });
  }

  // 4. Config: sender + recipient from fly secrets. A missing config is a
  //    misconfiguration (500), not a silent drop.
  const sender = process.env.NOTIFICATION_SENDER;
  const recipient = process.env.NOTIFICATION_RECIPIENT;
  if (!sender || !recipient) {
    logDigest({ event: "config_missing", count: rows.length, error_code: "DIGEST_NOT_CONFIGURED" });
    return NextResponse.json({ error: { code: "DIGEST_NOT_CONFIGURED" } }, { status: 500 });
  }

  // 5. Render + send. Mark emailed ONLY on a confirmed send (SD-N8 / R-S9).
  const rendered = renderDigest(
    rows.map((r) => ({
      id: r.id,
      kind: r.kind,
      title: r.title,
      detail: r.detail,
      created_at: r.created_at,
    })),
  );

  try {
    await sendDigestEmail({ rendered, sender, recipient });
  } catch (err) {
    const code = (err as { code?: string } | null)?.code ?? SES_SEND_FAILED;
    logDigest({ event: "send_failed", count: rows.length, error_code: code });
    // emailed_at stays null -> retried next day. 502 (downstream failure).
    return NextResponse.json({ error: { code } }, { status: 502 });
  }

  await markNotificationsEmailed(
    client,
    rows.map((r) => r.id),
  );
  logDigest({ event: "sent", count: rows.length });
  return NextResponse.json({ sent: rows.length }, { status: 200 });
}
