import Link from "next/link";
import type { CSSProperties } from "react";

import { KLabel } from "@/components/KLabel";
import { toDeliveryView } from "@/lib/domain/delivery-view";
import { formatClock, formatRelative } from "@/lib/format";
import type { WebhookDeliveryRow } from "@/lib/supabase/types";

import styles from "./Webhooks.module.css";
import ds from "./DeliveryLog.module.css";

/**
 * S-178 (issue 323) — the per-endpoint delivery log (DESIGN.md §5.9.6). Newest
 * first, one keyset page at a time. It answers "why didn't a run happen?":
 * each row shows when, the event, the sender's delivery id, whether the
 * signature verified, the matched rule, and the outcome with a plain reason.
 * `fired` links to the run.
 *
 * Event type, delivery id and reason are untrusted. They render as React
 * text only (escaped), never as markup or links. Server-safe: no client state.
 */
export interface DeliveryLogProps {
  rows: WebhookDeliveryRow[];
  ruleNames: Map<string, string>;
  olderHref: string | null;
  newestHref: string | null;
  retentionDays: number;
  nowMs: number;
}

export function DeliveryLog({
  rows,
  ruleNames,
  olderHref,
  newestHref,
  retentionDays,
  nowMs,
}: DeliveryLogProps) {
  const views = rows.map((r) => toDeliveryView(r, ruleNames));
  return (
    <section className={ds.section} aria-labelledby="deliveries-heading">
      <div className={ds.head}>
        <h2 id="deliveries-heading" className={ds.heading}>
          Deliveries
        </h2>
        <p className={ds.note}>
          Every request to this URL, newest first. Kept for {retentionDays} days.
        </p>
      </div>

      {views.length === 0 ? (
        <div className={styles.empty} role="status">
          <KLabel>Deliveries</KLabel>
          <p className={styles.emptyBody}>
            No deliveries yet. Every request to this endpoint lands here, including rejected ones.
          </p>
        </div>
      ) : (
        <div className={styles.scroll}>
          <table className={ds.table} aria-label="Deliveries">
            <thead>
              <tr className={`${ds.row} ${ds.headRow}`}>
                {["Received", "Event", "Delivery ID", "Signature", "Rule", "Outcome"].map((h) => (
                  <th key={h} scope="col" className={styles.headCell}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className={styles.body}>
              {views.map((v) => (
                <tr key={v.id} className={ds.row}>
                  <td className={styles.cell}>
                    <div className={styles.mono}>{formatRelative(v.receivedAt, nowMs)}</div>
                    <div className={styles.faint}>
                      {v.receivedAt.slice(0, 10)} {formatClock(v.receivedAt)} UTC
                    </div>
                  </td>
                  <td className={styles.cell}>
                    <span className={styles.mono}>{v.eventType ?? "—"}</span>
                  </td>
                  <td className={styles.cell}>
                    <span className={ds.id} title={v.deliveryId ?? undefined}>
                      {v.deliveryId ?? "—"}
                    </span>
                  </td>
                  <td className={styles.cell}>
                    <span className={v.verification === "verified" ? styles.faint : ds.failed}>
                      {v.verification}
                    </span>
                  </td>
                  <td className={styles.cell}>
                    <span className={styles.faint}>{v.ruleLabel ?? "—"}</span>
                  </td>
                  <td className={styles.cell}>
                    <div className={ds.outcome}>
                      <span
                        className={styles.pill}
                        style={{ "--st-color": `var(${v.color})` } as CSSProperties}
                      >
                        <span className={styles.dot} aria-hidden="true" />
                        {v.outcomeLabel}
                      </span>
                      {v.runHref && (
                        <Link className={ds.runLink} href={v.runHref}>
                          Open run ▸
                        </Link>
                      )}
                    </div>
                    {v.reason && <div className={ds.reason}>{v.reason}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {(olderHref || newestHref) && (
        <nav className={ds.pager} aria-label="Delivery pages">
          {newestHref && (
            <Link className={ds.runLink} href={newestHref}>
              ◂ Newest
            </Link>
          )}
          {olderHref && (
            <Link className={ds.runLink} href={olderHref}>
              Older ▸
            </Link>
          )}
        </nav>
      )}
    </section>
  );
}
