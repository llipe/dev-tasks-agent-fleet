"use client";

import { useMemo, useState, useTransition, type CSSProperties } from "react";
import { useRouter } from "next/navigation";

import { KLabel } from "@/components/KLabel";
import { NotificationsIcon } from "@/components/icons";
import { toNotificationViewModel } from "@/lib/domain/notification-view";
import { formatRelative } from "@/lib/format";
import type { NotificationRow } from "@/lib/supabase/types";
import {
  markAllNotificationsReadAction,
  markNotificationReadAction,
} from "@/app/(panel)/notifications/actions";

import styles from "./NotificationBell.module.css";

/**
 * S-163 (#275) — the top-bar notification bell (DESIGN.md §5.8). A `btn-ghost`
 * icon with an unread badge (absent at zero), opening a 384px popover of the 5
 * newest items (closed by a full-viewport scrim). Initial data is server-fetched
 * in the authenticated layout and passed in; mark-read goes through the Server
 * Actions then `router.refresh()`.
 */
export interface NotificationBellProps {
  rows: NotificationRow[]; // 5 newest
  unread: number;
  total: number;
}

export function NotificationBell({ rows, unread, total }: NotificationBellProps) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [, startTransition] = useTransition();
  const nowMs = useMemo(() => Date.now(), []);
  const items = useMemo(() => rows.map(toNotificationViewModel), [rows]);

  function refresh() {
    startTransition(() => router.refresh());
  }

  function markOne(id: string, alreadyRead: boolean) {
    if (alreadyRead) return;
    startTransition(async () => {
      await markNotificationReadAction(id);
      router.refresh();
    });
  }

  function markAll() {
    startTransition(async () => {
      await markAllNotificationsReadAction();
      router.refresh();
    });
  }

  return (
    <div className={styles.wrap}>
      <button
        type="button"
        className={styles.bell}
        aria-label={unread > 0 ? `Notifications (${unread} unread)` : "Notifications"}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => {
          setOpen((o) => !o);
          if (!open) refresh();
        }}
      >
        <NotificationsIcon size={16} aria-hidden="true" />
        {unread > 0 && (
          <span className={styles.badge} aria-hidden="true">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>

      {open && (
        <>
          <button
            type="button"
            className={styles.scrim}
            aria-label="Close notifications"
            onClick={() => setOpen(false)}
          />
          <div className={styles.popover} role="dialog" aria-label="Notifications">
            <div className={styles.popHeader}>
              <span className={styles.popTitle}>Notifications</span>
              {unread > 0 && (
                <button type="button" className={styles.markAll} onClick={markAll}>
                  Mark all read
                </button>
              )}
            </div>

            {items.length === 0 ? (
              <div className={styles.empty}>
                <KLabel>Inbox</KLabel>
                <p className={styles.emptyBody}>No notifications.</p>
              </div>
            ) : (
              <ul className={styles.list}>
                {items.map((item) => (
                  <li key={item.id}>
                    <button
                      type="button"
                      className={`${styles.item} ${item.unread ? styles.unread : ""}`}
                      onClick={() => markOne(item.id, !item.unread)}
                    >
                      <span
                        className={styles.dot}
                        style={{ "--st-color": `var(${item.dotColor})` } as CSSProperties}
                        aria-hidden="true"
                      />
                      <span className={styles.itemContent}>
                        <span className={styles.itemTitle}>{item.title}</span>
                        <span className={styles.itemTime}>
                          {formatRelative(item.createdAtMs, nowMs)}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}

            <div className={styles.popFooter}>
              <span>
                {unread} unread · {total} total
              </span>
              <a href="/notifications" className={styles.viewAll} onClick={() => setOpen(false)}>
                View all ▸
              </a>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
