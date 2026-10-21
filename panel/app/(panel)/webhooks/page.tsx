/**
 * S-176 (#321) — the Webhooks screen `/webhooks` (DESIGN.md §5.9).
 *
 * Async server component (SD2). It reads the endpoints with their rule counts
 * (never a secret) and hands them to the `WebhooksClient` controller. The
 * payload URL's origin comes from the request (the host the operator is
 * using), so it reads correctly on Fly and locally. It is display-only; the
 * route itself never trusts it. Never cached: a new endpoint must appear on
 * the next navigation.
 */

import { headers } from "next/headers";

import { createServerClient } from "@/lib/supabase/server";
import { getWebhookEndpointsForList } from "@/lib/supabase/queries";
import { WebhooksClient } from "@/components/webhooks/WebhooksClient";
import { requestOrigin } from "@/lib/webhooks/request-origin";

import styles from "./page.module.css";

export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";

export default async function WebhooksPage() {
  const client = createServerClient();
  const [rows, h] = await Promise.all([getWebhookEndpointsForList(client), headers()]);
  const enabled = rows.filter((r) => r.is_enabled).length;
  const rules = rows.reduce((n, r) => n + r.rule_count, 0);

  return (
    <main className={styles.page}>
      <div className={styles.headerRow}>
        <h1 className={styles.heading}>Webhooks</h1>
      </div>
      <p className={styles.stat}>
        {rows.length} endpoint{rows.length === 1 ? "" : "s"} · {enabled} enabled · {rules} rule
        {rules === 1 ? "" : "s"}
        <span className={styles.note}> · every delivery is signature-checked</span>
      </p>
      <WebhooksClient rows={rows} baseUrl={requestOrigin(h)} />
    </main>
  );
}
