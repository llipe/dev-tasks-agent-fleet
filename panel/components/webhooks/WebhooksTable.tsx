"use client";

import { useState, type CSSProperties } from "react";

import { Tag } from "@/components/Tag";
import { CopyIcon, DeleteIcon, EditIcon, RotateIcon } from "@/components/icons";
import type { WebhookEndpointListRow } from "@/lib/supabase/queries";

import styles from "./Webhooks.module.css";

/**
 * S-176 (issue 321) — the `/webhooks` endpoint table (DESIGN.md §5.9). A semantic
 * `<table>` on the Schedules grid. Columns: status pill, name + source, events
 * (first 3 + overflow), rule count, the copyable payload URL, and actions.
 * The signing secret is never part of a row.
 */

export const EVENTS_SHOWN = 3;

export function webhookUrl(baseUrl: string, urlToken: string): string {
  return `${baseUrl.replace(/\/+$/, "")}/api/webhooks/${urlToken}`;
}

export interface WebhooksTableProps {
  rows: WebhookEndpointListRow[];
  baseUrl: string;
  flashId: string | null;
  onToggle: (row: WebhookEndpointListRow) => void;
  onEdit: (row: WebhookEndpointListRow) => void;
  onRotate: (row: WebhookEndpointListRow) => void;
  onDelete: (row: WebhookEndpointListRow) => void;
}

export function WebhooksTable({
  rows,
  baseUrl,
  flashId,
  onToggle,
  onEdit,
  onRotate,
  onDelete,
}: WebhooksTableProps) {
  return (
    <div className={styles.scroll}>
      <table className={styles.table} aria-label="Webhook endpoints">
        <thead>
          <tr className={`${styles.row} ${styles.headRow}`}>
            {["Status", "Endpoint", "Events", "Rules", "Payload URL"].map((h) => (
              <th key={h} scope="col" className={styles.headCell}>
                {h}
              </th>
            ))}
            <th scope="col" className={styles.headCell}>
              <span className={styles.srOnly}>Actions</span>
            </th>
          </tr>
        </thead>
        <tbody className={styles.body}>
          {rows.map((row) => (
            <EndpointRow
              key={row.id}
              row={row}
              url={webhookUrl(baseUrl, row.url_token)}
              flash={row.id === flashId}
              onToggle={onToggle}
              onEdit={onEdit}
              onRotate={onRotate}
              onDelete={onDelete}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EndpointRow({
  row,
  url,
  flash,
  onToggle,
  onEdit,
  onRotate,
  onDelete,
}: {
  row: WebhookEndpointListRow;
  url: string;
  flash: boolean;
} & Pick<WebhooksTableProps, "onToggle" | "onEdit" | "onRotate" | "onDelete">) {
  const [copied, setCopied] = useState(false);
  const shown = row.event_allowlist.slice(0, EVENTS_SHOWN);
  const hidden = row.event_allowlist.slice(EVENTS_SHOWN);
  const label = row.name || "endpoint";

  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  return (
    <tr className={`${styles.row} ${flash ? styles.flash : ""}`}>
      <td className={styles.cell}>
        <span
          className={styles.pill}
          style={
            { "--st-color": row.is_enabled ? "var(--st-ok)" : "var(--muted)" } as CSSProperties
          }
        >
          <span
            className={`${styles.dot} ${row.is_enabled ? "" : styles.hollow}`}
            aria-hidden="true"
          />
          {row.is_enabled ? "enabled" : "disabled"}
        </span>
      </td>
      <td className={styles.cell}>
        <div className={styles.name}>{label}</div>
        <div className={styles.source}>{row.source}</div>
      </td>
      <td className={styles.cell}>
        <div className={styles.events}>
          {shown.map((e) => (
            <Tag key={e} size="sm">
              {e}
            </Tag>
          ))}
          {hidden.length > 0 && (
            <span title={hidden.join(", ")}>
              <Tag size="sm" variant="outline">
                +{hidden.length}
              </Tag>
            </span>
          )}
        </div>
      </td>
      <td className={styles.cell}>
        <span className={styles.mono}>
          {row.rule_count} rule{row.rule_count === 1 ? "" : "s"}
        </span>
      </td>
      <td className={styles.cell}>
        <div className={styles.url}>
          <span className={styles.urlText} title={url}>
            {url}
          </span>
          <button
            type="button"
            className={styles.iconBtn}
            aria-label={`Copy URL for ${label}`}
            onClick={copy}
          >
            <CopyIcon size={14} aria-hidden="true" />
          </button>
          <span className={styles.copied} aria-live="polite">
            {copied ? "Copied" : ""}
          </span>
        </div>
      </td>
      <td className={styles.cell}>
        <div className={styles.actions}>
          <button
            type="button"
            className={styles.toggleBtn}
            aria-label={`${row.is_enabled ? "Disable" : "Enable"} ${label}`}
            onClick={() => onToggle(row)}
          >
            {row.is_enabled ? "Disable" : "Enable"}
          </button>
          <button
            type="button"
            className={styles.iconBtn}
            aria-label={`Edit ${label}`}
            onClick={() => onEdit(row)}
          >
            <EditIcon size={14} aria-hidden="true" />
          </button>
          <button
            type="button"
            className={styles.iconBtn}
            aria-label={`Rotate secret for ${label}`}
            onClick={() => onRotate(row)}
          >
            <RotateIcon size={14} aria-hidden="true" />
          </button>
          <button
            type="button"
            className={`${styles.iconBtn} ${styles.deleteBtn}`}
            aria-label={`Delete ${label}`}
            onClick={() => onDelete(row)}
          >
            <DeleteIcon size={14} aria-hidden="true" />
          </button>
        </div>
      </td>
    </tr>
  );
}
