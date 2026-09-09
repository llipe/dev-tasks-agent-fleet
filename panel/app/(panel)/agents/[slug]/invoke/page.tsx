/**
 * S-113 (#126) — the invoke form route `/agents/[slug]/invoke` (DESIGN §5.4).
 *
 * A thin async server component: it reads the agent and (when required) the
 * enabled repositories server-side, 404s on an unknown OR disabled agent (a
 * disabled agent is not-found, never an empty form), and hands the raw
 * `params_schema` + `default_params` to the client `InvokeDialog`, which
 * generates the field list from the schema alone (AC7).
 *
 * Route-segment config is declared INLINE (Next.js ignores re-exported config —
 * S-104 audit D4 / technical-guidelines §12); the repository list must be fresh
 * (a newly enabled repo should appear without a rebuild).
 */

import { notFound } from "next/navigation";
import { createServerClient } from "@/lib/supabase/server";
import { getAgentBySlug, getEnabledRepositories } from "@/lib/supabase/queries";
import { InvokeDialog } from "@/components/invoke/InvokeDialog";

export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";

export default async function InvokePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const client = createServerClient();

  const agent = await getAgentBySlug(client, slug);
  if (!agent || !agent.is_enabled) {
    notFound();
  }

  const repositories = agent.requires_repository
    ? (await getEnabledRepositories(client)).map((r) => ({ id: r.id, full_name: r.full_name }))
    : [];

  return (
    <InvokeDialog
      slug={agent.slug}
      agentName={agent.name}
      schema={agent.params_schema}
      defaultParams={(agent.default_params ?? {}) as Record<string, unknown>}
      requiresRepository={agent.requires_repository}
      repositories={repositories}
    />
  );
}
