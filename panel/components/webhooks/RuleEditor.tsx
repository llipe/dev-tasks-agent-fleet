"use client";

import { useState, useTransition, type CSSProperties } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/Button";
import { KLabel } from "@/components/KLabel";
import { Tag } from "@/components/Tag";
import { DeleteIcon, EditIcon, NewScheduleIcon } from "@/components/icons";
import type { AgentOption, RepositoryOption } from "@/components/schedules/ScheduleDialog";
import type { WebhookCondition, WebhookRuleRow } from "@/lib/supabase/types";
import {
  deleteRuleAction,
  reorderRulesAction,
  toggleRuleAction,
} from "@/app/(panel)/webhooks/actions";

import { RuleDialog } from "./RuleDialog";
import styles from "./Webhooks.module.css";
import rs from "./RuleEditor.module.css";

/**
 * S-177 (issue 322) — the ordered rule list on `/webhooks/[id]` (DESIGN.md
 * §5.9.4). Rules are evaluated top to bottom and the first match fires; the
 * default rule is shown in its own section because it only runs when nothing
 * else matches, whatever its position. Moving a rule sends the full new order
 * (one atomic renumber on the server). Every mutation re-reads via
 * `router.refresh()`.
 */
export interface RuleEditorProps {
  endpoint: { id: string; eventAllowlist: string[] };
  rules: WebhookRuleRow[];
  agents: AgentOption[];
  repositories: RepositoryOption[];
}

export function conditionText(c: WebhookCondition): string {
  if (c.op === "exists") return `${c.field} exists`;
  if (c.op === "matches_event") return `event is ${String(c.value ?? "")}`;
  const v = Array.isArray(c.value) ? c.value.join(", ") : (c.value ?? "");
  return `${c.field} ${c.op.replace("_", " ")} ${v}`;
}

export function RuleEditor({ endpoint, rules, agents, repositories }: RuleEditorProps) {
  const router = useRouter();
  const [, startTransition] = useTransition();
  const [dialog, setDialog] = useState<{ rule: WebhookRuleRow | null } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<WebhookRuleRow | null>(null);
  const [alert, setAlert] = useState<string | null>(null);

  const ordered = [...rules].filter((r) => !r.is_default).sort((a, b) => a.position - b.position);
  const defaults = rules.filter((r) => r.is_default);
  const agentName = (id: string) => agents.find((a) => a.id === id)?.name ?? "unavailable agent";
  const repoName = (id: string | null) =>
    repositories.find((r) => r.id === id)?.fullName ?? "unavailable repository";

  function mutate(fn: () => Promise<{ ok: boolean; message?: string }>) {
    setAlert(null);
    startTransition(async () => {
      const res = await fn();
      if (!res.ok) setAlert(res.message ?? "Something went wrong. Try again.");
      router.refresh();
    });
  }

  function move(index: number, delta: -1 | 1) {
    const next = [...ordered];
    const [r] = next.splice(index, 1);
    next.splice(index + delta, 0, r!);
    const ids = [...next, ...defaults].map((x) => x.id);
    mutate(() => reorderRulesAction(endpoint.id, ids));
  }

  function row(rule: WebhookRuleRow, index: number | null) {
    const label = rule.name || "Untitled rule";
    const failing = rule.consecutive_failures > 0;
    return (
      <li key={rule.id} className={rs.rule}>
        <span className={rs.pos} data-testid="rule-pos" aria-hidden={index === null}>
          {index === null ? "—" : index + 1}
        </span>
        <div className={rs.body}>
          <div className={rs.titleRow}>
            <span className={rs.name}>{label}</span>
            <span
              className={styles.pill}
              style={
                { "--st-color": rule.is_enabled ? "var(--st-ok)" : "var(--muted)" } as CSSProperties
              }
            >
              <span
                className={`${styles.dot} ${rule.is_enabled ? "" : styles.hollow}`}
                aria-hidden="true"
              />
              {rule.is_enabled ? "enabled" : "disabled"}
            </span>
            {failing && (
              <span className={rs.failing}>
                {rule.consecutive_failures}/{rule.auto_disable_threshold} failed starts
              </span>
            )}
          </div>
          <div className={rs.summary}>
            {rule.is_default ? (
              <span className={rs.when}>when no other rule matches</span>
            ) : (
              <>
                <span className={rs.when}>on</span>
                {rule.event_types.map((e) => (
                  <Tag key={e} size="sm">
                    {e}
                  </Tag>
                ))}
                {rule.conditions.map((c, i) => (
                  <span key={i} className={rs.cond}>
                    {conditionText(c)}
                  </span>
                ))}
              </>
            )}
          </div>
          <div className={rs.target}>
            → {agentName(rule.agent_id)} ·{" "}
            {rule.repo_mode === "fixed"
              ? repoName(rule.repository_id)
              : `repo from ${rule.repo_payload_field ?? "?"}`}
          </div>
        </div>
        <div className={styles.actions}>
          {index !== null && (
            <>
              <button
                type="button"
                className={styles.iconBtn}
                aria-label={`Move rule ${label} up`}
                disabled={index === 0}
                onClick={() => move(index, -1)}
              >
                ↑
              </button>
              <button
                type="button"
                className={styles.iconBtn}
                aria-label={`Move rule ${label} down`}
                disabled={index === ordered.length - 1}
                onClick={() => move(index, 1)}
              >
                ↓
              </button>
            </>
          )}
          <button
            type="button"
            className={styles.toggleBtn}
            aria-label={`${rule.is_enabled ? "Disable" : "Enable"} rule ${label}`}
            onClick={() => mutate(() => toggleRuleAction(rule.id, !rule.is_enabled))}
          >
            {rule.is_enabled ? "Disable" : "Enable"}
          </button>
          <button
            type="button"
            className={styles.iconBtn}
            aria-label={`Edit rule ${label}`}
            onClick={() => setDialog({ rule })}
          >
            <EditIcon size={14} aria-hidden="true" />
          </button>
          <button
            type="button"
            className={`${styles.iconBtn} ${styles.deleteBtn}`}
            aria-label={`Delete rule ${label}`}
            onClick={() => setConfirmDelete(rule)}
          >
            <DeleteIcon size={14} aria-hidden="true" />
          </button>
        </div>
      </li>
    );
  }

  const addButton = (
    <Button variant="primary" onClick={() => setDialog({ rule: null })}>
      <NewScheduleIcon size={14} aria-hidden="true" /> Add rule
    </Button>
  );

  return (
    <section className={rs.section} aria-labelledby="rules-heading">
      <div className={rs.head}>
        <div>
          <h2 id="rules-heading" className={rs.heading}>
            Rules
          </h2>
          <p className={rs.note}>
            The first matching rule wins, top to bottom. The default rule runs only when nothing
            else matches.
          </p>
        </div>
        {addButton}
      </div>

      {alert && (
        <p className={styles.banner} role="alert">
          {alert}
        </p>
      )}

      {rules.length === 0 ? (
        <div className={styles.empty} role="status">
          <KLabel>Rules</KLabel>
          <p className={styles.emptyBody}>
            No rules yet. Every delivery to this endpoint is recorded as no match until you add one.
          </p>
          {addButton}
        </div>
      ) : (
        <>
          {ordered.length > 0 && (
            <ol className={rs.list} aria-label="Rules in match order">
              {ordered.map((r, i) => row(r, i))}
            </ol>
          )}
          {defaults.length > 0 && (
            <section className={rs.defaultSection} aria-label="Default rule">
              <KLabel>Default rule</KLabel>
              <ul className={rs.list}>{defaults.map((r) => row(r, null))}</ul>
            </section>
          )}
        </>
      )}

      {dialog && (
        <RuleDialog
          endpointId={endpoint.id}
          eventAllowlist={endpoint.eventAllowlist}
          rule={dialog.rule}
          agents={agents}
          repositories={repositories}
          onClose={() => setDialog(null)}
          onSaved={() => {
            setDialog(null);
            router.refresh();
          }}
        />
      )}

      {confirmDelete && (
        <div className={styles.overlay}>
          <div
            className={`${styles.dialog} ${styles.small}`}
            role="alertdialog"
            aria-modal="true"
            aria-label="Delete rule"
            onKeyDown={(e) => {
              if (e.key === "Escape") setConfirmDelete(null);
            }}
          >
            <header className={styles.header}>
              <h2 className={styles.title}>Delete rule?</h2>
            </header>
            <div className={styles.bodyPad}>
              <p className={styles.dialogBody}>
                <strong>{confirmDelete.name || "This rule"}</strong> stops matching deliveries. Runs
                it already started are kept; their deliveries no longer link to a rule.
              </p>
            </div>
            <div className={styles.footer}>
              <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(null)} autoFocus>
                Cancel
              </Button>
              <Button
                variant="secondary"
                size="sm"
                className={styles.destructive}
                onClick={() => {
                  const r = confirmDelete;
                  setConfirmDelete(null);
                  mutate(() => deleteRuleAction(r.id));
                }}
              >
                Delete rule
              </Button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
