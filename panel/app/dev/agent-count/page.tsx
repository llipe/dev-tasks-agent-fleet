/**
 * Manual-verification placeholder route (S-104 / issue #117, task 1.16).
 *
 * Proves the SD2 server-side read boundary end-to-end with no UI: a Server
 * Component creates a per-request server client, runs the `getEnabledAgents`
 * helper, and renders the count. This is the manual counterpart to the Layer
 * 2.5 query tests — it exercises the real Next.js server runtime against the
 * live Supabase stack. It is intentionally minimal and lives under `app/dev/`;
 * the real screens land in Wave 3.
 *
 * It reads Supabase on the server only (never a client component), and is
 * `force-dynamic` so the count is never statically cached.
 */

import { createServerClient } from "@/lib/supabase/server";
import { getEnabledAgents } from "@/lib/supabase/queries";

// Data route: never statically cached, no Next.js data cache (AC7). Next.js
// only recognizes these route-segment exports when declared directly in the
// route module — a re-export from another file is NOT honored (it emits a
// "can't recognize the exported ... field" warning and falls back to defaults).
// So they are declared inline here; the shared route-config module documents
// the canonical values.
export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";

export default async function AgentCountPage() {
  const client = createServerClient();
  const agents = await getEnabledAgents(client);

  return (
    <main>
      <h1>Server-side read boundary check</h1>
      <p>
        Enabled agents (fetched server-side via <code>getEnabledAgents</code>):{" "}
        <strong data-testid="agent-count">{agents.length}</strong>
      </p>
      <ul>
        {agents.map((a) => (
          <li key={a.id}>
            <code>{a.slug}</code> — {a.name}
          </li>
        ))}
      </ul>
    </main>
  );
}
