"use client";

import { useMemo, useState, useTransition, type CSSProperties } from "react";
import { useRouter } from "next/navigation";

import { KLabel } from "@/components/KLabel";
import { renderInstantMs } from "@/lib/time/render-instant";
import { groupNotifications } from "@/lib/domain/notification-view";
import { formatRelative } from "@/lib/format";
import type { NotificationRow } from "@/lib/supabase/types";
import {
  markAllNotificationsReadAction,
  markNotificationReadAction,
} from "@/app/(panel)/notifications/actions";

import styles from "./NotificationsFeed.module.css";

/**
 * S-163 (issue 275) — the `/notifications` feed (DESIGN.md §5.8). A single-column
 * surface grouped by day (Today / Earlier). Each item row: a kind dot (glow when
 * unread), the title (unread = accent edge + weight), the UNTRUSTED detail
 * rendered as text only, the structured links, and a relative timestamp.
 * Clicking an item marks it read; "Mark all read" clears every unread. Both go
 * through Server Actions then `router.refresh()` (server-refetch-is-truth).
 */
export interface NotificationsFeedProps {
  rows: NotificationRow[];
  unread: number;
  total: number;
}

export function NotificationsFeed({ rows, unread, total }: NotificationsFeedProps) {
  const router = useRouter();
  const [, startTransition] = useTransition();
  // Capture "now" once on mount via a lazy useState initializer rather than
  // `useMemo(() => Date.now(), [])` (react-hooks/purity bans the impure call in
  // a memo). Behavior is identical: a single instant frozen for this mount. (issue 217)
  const [nowMs] = useState(() => renderInstantMs());
  const groups = useMemo(() => groupNotifications(rows, nowMs), [rows, nowMs]);
  const [busy, setBusy] = useState(false);

  function markOne(id: string, alreadyRead: boolean) {
    if (alreadyRead) return;
    startTransition(async () => {
      await markNotificationReadAction(id);
      router.refresh();
    });
  }

  function markAll() {
    setBusy(true);
    startTransition(async () => {
      await markAllNotificationsReadAction();
      router.refresh();
      setBusy(false);
    });
  }

  return (
    <main className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.heading}>Notifications</h1>
        <span className={styles.stat}>
          {unread} unread · {total} total · newest first
        </span>
        <button
          type="button"
          className={styles.markAll}
          onClick={markAll}
          disabled={unread === 0 || busy}
          aria-disabled={unread === 0 || busy}
        >
          Mark all read
        </button>
      </div>

      {groups.length === 0 ? (
        <div className={styles.empty} role="status">
          <KLabel>Inbox</KLabel>
          <p className={styles.emptyBody}>No notifications.</p>
        </div>
      ) : (
        groups.map((group) => (
          <section key={group.label} className={styles.group}>
            <div className={styles.groupLabel}>{group.label}</div>
            {group.items.map((item) => (
              <button
                key={item.id}
                type="button"
                className={`${styles.item} ${item.unread ? styles.unread : styles.read}`}
                onClick={() => markOne(item.id, !item.unread)}
              >
                <span
                  className={`${styles.dot} ${item.unread ? styles.dotGlow : ""}`}
                  style={{ "--st-color": `var(${item.dotColor})` } as CSSProperties}
                  aria-hidden="true"
                />
                <span className={styles.content}>
                  <span className={styles.title}>{item.title}</span>
                  {/* Untrusted detail — text only, never markup/link. */}
                  {item.detail && <span className={styles.detail}>{item.detail}</span>}
                  {item.links.length > 0 && (
                    <span className={styles.links}>
                      {item.links.map((l) => (
                        <a key={l.href} href={l.href} className={styles.link}>
                          {l.label}
                        </a>
                      ))}
                    </span>
                  )}
                </span>
                <span className={styles.time}>{formatRelative(item.createdAtMs, nowMs)}</span>
              </button>
            ))}
          </section>
        ))
      )}

      <p className={styles.footer}>
        A daily email digest of these is sent at 08:00 America/Santiago.
      </p>
    </main>
  );
}
