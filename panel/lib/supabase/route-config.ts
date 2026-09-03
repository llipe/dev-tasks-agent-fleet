/**
 * Shared route segment config for pages and route handlers that read live run
 * state (AC7). Re-export these from a route/page module so Next.js never
 * statically caches operator-facing data:
 *
 *   export { dynamic, revalidate, fetchCache } from "@/lib/supabase/route-config";
 *
 * `force-dynamic` opts the segment out of static rendering; `revalidate = 0`
 * and `fetchCache = "force-no-store"` ensure no Next.js Data Cache is
 * introduced for run data. Run state changes second-to-second (a live tail),
 * so a cached read would show a stale run status — exactly the failure SD4's
 * read-time derivation exists to prevent.
 */

export const dynamic = "force-dynamic" as const;
export const revalidate = 0 as const;
export const fetchCache = "force-no-store" as const;
