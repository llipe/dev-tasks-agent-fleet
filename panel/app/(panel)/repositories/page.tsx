/**
 * S-147 (#207) — the Repositories screen `/repositories` (spec §10, DESIGN.md
 * §5.6 — first-pass layout, see the stub note there).
 *
 * A thin async server component: reads the non-archived repositories
 * (FR15's default view — `getRepositories(client)` with no
 * `includeArchived` opt-in) and renders the list plus the Add-repository
 * form. Route-segment config is declared INLINE (Next.js ignores re-exported
 * config — S-104 audit D4 / technical-guidelines §12): a newly added
 * repository must appear on next navigation without a rebuild, and this
 * screen must never be statically cached (the same posture as every other
 * `(panel)` route reading live data).
 */

import { createServerClient } from "@/lib/supabase/server";
import { getRepositories } from "@/lib/supabase/queries";
import { KLabel } from "@/components/KLabel";
import { RepositoryTable } from "@/components/repositories/RepositoryTable";
import { AddRepositoryForm } from "@/components/repositories/AddRepositoryForm";

import styles from "./page.module.css";

export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";

export default async function RepositoriesPage() {
  const client = createServerClient();
  const repositories = await getRepositories(client);

  return (
    <main className={styles.page}>
      <h1 className={styles.heading}>Repositories</h1>

      <section className={styles.section} aria-labelledby="repositories-list-heading">
        <KLabel>
          <span id="repositories-list-heading">Registered repositories</span>
        </KLabel>
        <RepositoryTable rows={repositories} />
      </section>

      <section className={styles.section} aria-labelledby="add-repository-heading">
        <KLabel>
          <span id="add-repository-heading">Add repository</span>
        </KLabel>
        <AddRepositoryForm />
      </section>
    </main>
  );
}
