/**
 * S-177 (#322) — an endpoint's page `/webhooks/[id]` (DESIGN.md §5.9.4): its
 * settings summary and the ordered rule editor. S-178 adds the delivery log
 * below. Server component (SD2); reads the endpoint, its rules, and the
 * enabled agents and repositories that rules may target. Never cached.
 */

import Link from "next/link";
import { notFound } from "next/navigation";
import { headers } from "next/headers";

import { createServerClient } from "@/lib/supabase/server";
import {
  getEnabledAgents,
  getEnabledRepositories,
  getWebhookEndpointById,
  getWebhookRulesForEndpoint,
} from "@/lib/supabase/queries";
import { RuleEditor } from "@/components/webhooks/RuleEditor";
import type { AgentOption, RepositoryOption } from "@/components/schedules/ScheduleDialog";
import { requestOrigin, webhookUrl } from "@/lib/webhooks/request-origin";

import styles from "../page.module.css";

export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function WebhookEndpointPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  const client = createServerClient();
  const endpoint = await getWebhookEndpointById(client, id);
  if (!endpoint) notFound();

  const [rules, agents, repositories, h] = await Promise.all([
    getWebhookRulesForEndpoint(client, id),
    getEnabledAgents(client),
    getEnabledRepositories(client),
    headers(),
  ]);

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
    </main>
  );
}
