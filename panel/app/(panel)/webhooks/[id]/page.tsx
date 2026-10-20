/**
 * S-177 (#322) — an endpoint's page `/webhooks/[id]` (DESIGN.md §5.9.4): its
 * settings summary, the ordered rule editor, and (S-178) the delivery log,
 * paged newest-first with an untrusted `?before=` keyset cursor that is
 * validated strictly before it reaches the query. Server component (SD2); reads the endpoint, its rules, and the
 * enabled agents and repositories that rules may target. Never cached.
 */

import Link from "next/link";
import { notFound } from "next/navigation";
import { headers } from "next/headers";

import { createServerClient } from "@/lib/supabase/server";
import {
  getEnabledAgents,
  getEnabledRepositories,
  getWebhookDeliveriesPage,
  getWebhookDeliveryRetentionDays,
  getWebhookEndpointById,
  getWebhookRulesForEndpoint,
} from "@/lib/supabase/queries";
import { DeliveryLog } from "@/components/webhooks/DeliveryLog";
import { decodeDeliveryCursor, encodeDeliveryCursor } from "@/lib/domain/delivery-view";
import { renderInstantMs } from "@/lib/time/render-instant";
import { RuleEditor } from "@/components/webhooks/RuleEditor";
import type { AgentOption, RepositoryOption } from "@/components/schedules/ScheduleDialog";
import { requestOrigin, webhookUrl } from "@/lib/webhooks/request-origin";

import styles from "../page.module.css";

export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function WebhookEndpointPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ before?: string | string[] }>;
}) {
  const [{ id }, { before }] = await Promise.all([params, searchParams]);
  const cursor = decodeDeliveryCursor(typeof before === "string" ? before : undefined);
  if (!UUID.test(id)) notFound();
  const client = createServerClient();
  const endpoint = await getWebhookEndpointById(client, id);
  if (!endpoint) notFound();

  const [rules, agents, repositories, h, deliveries, retentionDays] = await Promise.all([
    getWebhookRulesForEndpoint(client, id),
    getEnabledAgents(client),
    getEnabledRepositories(client),
    headers(),
    getWebhookDeliveriesPage(client, id, { before: cursor ?? undefined }),
    getWebhookDeliveryRetentionDays(client),
  ]);
  const ruleNames = new Map(rules.map((r) => [r.id, r.name]));

  const agentOptions: AgentOption[] = agents.map((a) => ({
    id: a.id,
    slug: a.slug,
    name: a.name,
    isEnabled: a.is_enabled,
    requiresRepository: a.requires_repository,
    paramsSchema: a.params_schema,
    defaultParams: a.default_params,
  }));
  const repositoryOptions: RepositoryOption[] = repositories.map((r) => ({
    id: r.id,
    fullName: r.full_name,
    defaultBranch: r.default_branch,
  }));

  return (
    <main className={styles.page}>
      <nav aria-label="Breadcrumb" className={styles.crumbs}>
        <Link href="/webhooks">Webhooks</Link> <span aria-hidden="true">/</span>{" "}
        <span>{endpoint.name || "endpoint"}</span>
      </nav>
      <div className={styles.headerRow}>
        <h1 className={styles.heading}>{endpoint.name || "Untitled endpoint"}</h1>
      </div>
      <p className={styles.stat}>
        {endpoint.source} · {endpoint.is_enabled ? "enabled" : "disabled"} · events{" "}
        {endpoint.event_allowlist.join(", ") || "none"}
      </p>
      <p className={styles.url}>{webhookUrl(requestOrigin(h), endpoint.url_token)}</p>

      <RuleEditor
        endpoint={{ id: endpoint.id, eventAllowlist: endpoint.event_allowlist }}
        rules={rules}
        agents={agentOptions}
        repositories={repositoryOptions}
      />

      <DeliveryLog
        rows={deliveries.rows}
        ruleNames={ruleNames}
        olderHref={
          deliveries.nextCursor
            ? `/webhooks/${id}?before=${encodeDeliveryCursor(deliveries.nextCursor)}`
            : null
        }
        newestHref={cursor ? `/webhooks/${id}` : null}
        retentionDays={retentionDays}
        nowMs={renderInstantMs()}
      />
    </main>
  );
}
