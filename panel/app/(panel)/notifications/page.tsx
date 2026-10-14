/**
 * S-163 (#275) — the Notifications feed `/notifications` (DESIGN.md §5.8).
 *
 * Async server component (SD2): reads notifications newest-first + the unread
 * and total counts, hands them to the client feed. Route-segment config inline
 * (never cached — a new notification must appear on next navigation).
 */

import { createServerClient } from "@/lib/supabase/server";
import { getNotificationTotal, getNotifications, getUnreadCount } from "@/lib/supabase/queries";
import { NotificationsFeed } from "@/components/notifications/NotificationsFeed";

export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";

export default async function NotificationsPage() {
  const client = createServerClient();
  const [rows, unread, total] = await Promise.all([
    getNotifications(client),
    getUnreadCount(client),
    getNotificationTotal(client),
  ]);

  return <NotificationsFeed rows={rows} unread={unread} total={total} />;
}
