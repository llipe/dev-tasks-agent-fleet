/**
 * Pure route classification for the auth gate (S-116, spec §7.2/§7.3).
 *
 * The middleware (S-117) is the single authorization decision point. The
 * redirect-vs-401 split is security-relevant, so the decision is factored into
 * this **pure** function — no `NextRequest`, no I/O — so it can be exhaustively
 * unit-tested without a running server (spec §7.2 requirement 3).
 *
 * Fail-closed: an unrecognized path is treated as `ui`, i.e. gated behind a
 * redirect to login. A new route added later without touching this file is
 * therefore protected by default rather than exposed by default.
 */

export type RoutePolicy = "public" | "ui" | "api";

/**
 * Classifies a request pathname into a gate policy.
 *
 * | Pathname            | Policy   |
 * | ------------------- | -------- |
 * | `/login`            | `public` |
 * | `/api/**`           | `api`    | (incl. `/api/auth/logout` — session required)
 * | everything else     | `ui`     | (incl. `/dev/**`, unknown paths — fail-closed)
 *
 * @param pathname the URL pathname (no query/hash), e.g. `request.nextUrl.pathname`.
 */
export function classifyRoute(pathname: string): RoutePolicy {
  // Defensive: a non-string or empty input is treated as a gated UI route.
  if (typeof pathname !== "string" || pathname.length === 0) {
    return "ui";
  }

  // Exact public routes. `/login` is the only public page.
  if (pathname === "/login") {
    return "public";
  }

  // API surface (route handlers + the SSE stream). These must receive a JSON
  // 401 on denial, never an HTML redirect. `/api/auth/logout` is API too — it
  // requires a session and is idempotent.
  if (pathname === "/api" || pathname.startsWith("/api/")) {
    return "api";
  }

  // Everything else — pages, and any unknown path — is a gated UI route.
  return "ui";
}
