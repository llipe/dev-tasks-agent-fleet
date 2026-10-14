/**
 * S-163 (#275) — pure presentation helpers for the notifications feed + bell
 * (DESIGN.md §5.8). Maps a notification kind to its dot color, groups rows into
 * "Today"/"Earlier" (clock-injected), and derives the optional inline links from
 * the row's run/schedule ids. The `detail` text is UNTRUSTED and is rendered as
 * text only by the view — this module never builds a link out of it.
 */

import type { NotificationKind, NotificationRow } from "@/lib/supabase/types";

export const KIND_DOT_COLOR: Record<NotificationKind, string> = {
  run_succeeded: "--st-ok",
  run_failed: "--st-fail",
  schedule_auto_paused: "--st-timeout",
  pr_opened: "--color-accent",
};

export interface NotificationLink {
  label: string;
  href: string;
}

export interface NotificationViewModel {
  id: string;
  kind: NotificationKind;
  dotColor: string;
  title: string;
  detail: string | null;
  unread: boolean;
  links: NotificationLink[];
  createdAtMs: number;
}

export interface NotificationGroup {
  label: "Today" | "Earlier";
  items: NotificationViewModel[];
}

/** Links derived ONLY from structured ids — never from the untrusted detail. */
function linksFor(row: NotificationRow): NotificationLink[] {
  const links: NotificationLink[] = [];
  if (row.run_id) links.push({ label: "Open run ▸", href: `/runs/${row.run_id}` });
  if (row.schedule_id) links.push({ label: "View schedule ▸", href: "/schedules" });
  return links;
}

/** Shape one row into its view model. Pure. */
export function toNotificationViewModel(row: NotificationRow): NotificationViewModel {
  return {
    id: row.id,
    kind: row.kind,
    dotColor: KIND_DOT_COLOR[row.kind],
    title: row.title,
    detail: row.detail,
    unread: row.read_at === null,
    links: linksFor(row),
    createdAtMs: new Date(row.created_at).getTime(),
  };
}

function isSameDay(aMs: number, bMs: number): boolean {
  const a = new Date(aMs);
  const b = new Date(bMs);
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

/** Group newest-first rows into Today / Earlier (clock-injected). Omits empties. */
export function groupNotifications(rows: NotificationRow[], nowMs: number): NotificationGroup[] {
  const today: NotificationViewModel[] = [];
  const earlier: NotificationViewModel[] = [];
  for (const row of rows) {
    const vm = toNotificationViewModel(row);
    if (isSameDay(vm.createdAtMs, nowMs)) today.push(vm);
    else earlier.push(vm);
  }
  const groups: NotificationGroup[] = [];
  if (today.length > 0) groups.push({ label: "Today", items: today });
  if (earlier.length > 0) groups.push({ label: "Earlier", items: earlier });
  return groups;
}
