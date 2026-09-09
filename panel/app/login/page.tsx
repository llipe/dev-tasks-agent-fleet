import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { LoginForm } from "@/components/auth/LoginForm";
import { createAuthServerClient } from "@/lib/supabase/auth-server";
import { safeRedirectTarget } from "@/lib/auth/redirect";
import styles from "./login.module.css";

/**
 * The public `/login` screen (Story S-119, spec §10.1).
 *
 * A thin async **server component**. Route-segment config is declared **inline**
 * (S-104 audit D4 / §12): an auth response can carry a refreshed `Set-Cookie`,
 * and a cached login response could hand one operator another's session — so it
 * must never be cached or statically rendered.
 *
 * Responsibilities:
 *   - If the visitor is ALREADY authenticated (verified via `getClaims()`, never
 *     `getSession()`), redirect to `/` — signing in again is pointless and a
 *     signed-in operator should never see the form.
 *   - Read and pre-sanitize the untrusted `?redirect` target so the form carries
 *     only a safe same-origin value; the action sanitizes again authoritatively.
 *   - Render the Nocturne mockup (brand mark + wordmark, "Sign in" heading,
 *     invitation subtitle, faded rule) and the client `LoginForm`.
 *
 * NOT wrapped in `AppShell`: `/login` is outside the `(panel)` route group, so
 * `app/login/layout.tsx` renders it shell-free.
 */
export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";

/** Non-secret display region for the footer tag (§7.4). */
function regionLabel(): string {
  return process.env.AWS_REGION ?? "us-east-1";
}

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ redirect?: string | string[] }>;
}) {
  const cookieStore = await cookies();

  // Already signed in? Skip the form entirely (verified identity, not session).
  const supabase = createAuthServerClient(cookieStore);
  try {
    const { data, error } = await supabase.auth.getClaims();
    if (!error && data?.claims != null) {
      redirect("/");
    }
  } catch {
    // Treat any auth-check failure as "not signed in" (fail-open to the form is
    // safe here — the middleware gate still protects every real destination).
  }

  const params = await searchParams;
  const rawRedirect = Array.isArray(params.redirect) ? params.redirect[0] : params.redirect;
  const redirectTarget = safeRedirectTarget(rawRedirect);

  return (
    <main className={styles.page}>
      <section className={styles.card} aria-labelledby="login-heading">
        <div className={styles.brand}>
          <span className={styles.mark} aria-hidden="true">
            <span className={styles.markDot} />
          </span>
          <span className={styles.brandName}>Agent Fleet</span>
        </div>

        <h1 id="login-heading" className={styles.heading}>
          Sign in
        </h1>
        <p className={styles.subtitle}>Invitation-only. Contact an administrator for access.</p>

        <div className={styles.rule} aria-hidden="true" />

        <LoginForm redirectTarget={redirectTarget} region={regionLabel()} />
      </section>
    </main>
  );
}
