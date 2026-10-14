"use server";

import { createServerClient } from "@/lib/supabase/server";
import { markAllNotificationsRead, markNotificationRead } from "@/lib/supabase/queries";

/**
 * S-163 (#275) — mark-read Server Actions for the notifications feed + bell
 * (SD-N5). Thin `"use server"` wrappers over the service-role queries (RLS
 * deny-all, D11); reachable only when authenticated. The feed/bell re-read
 * server-side on `router.refresh()` — these never return row data. A missing/
 * blank id is a no-op success (nothing to mark), never an error.
 */

export async function markNotificationReadAction(id: string): Promise<{ ok: boolean }> {
  const notificationId = typeof id === "string" ? id.trim() : "";
  if (notificationId === "") {
    return { ok: true };
  }
  try {
    await markNotificationRead(createServerClient(), notificationId);
    return { ok: true };
  } catch {
    return { ok: false };
  }
}

export async function markAllNotificationsReadAction(): Promise<{ ok: boolean }> {
  try {
    await markAllNotificationsRead(createServerClient());
    return { ok: true };
  } catch {
    return { ok: false };
  }
}
