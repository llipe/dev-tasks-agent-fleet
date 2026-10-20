"use client";

import { useEffect, useId, useMemo, useRef, useState, useTransition } from "react";

import { Button } from "@/components/Button";
import { Toggle } from "@/components/Toggle";
import { FieldRow } from "@/components/invoke/FieldRow";
import type { AgentOption, RepositoryOption } from "@/components/schedules/ScheduleDialog";
import { buildFieldDescriptors } from "@/lib/schema/form";
import type { RuleFieldErrors } from "@/lib/domain/webhook-rule-save";
import type { WebhookCondition, WebhookConditionOp, WebhookRuleRow } from "@/lib/supabase/types";
import { saveRuleAction } from "@/app/(panel)/webhooks/actions";

import styles from "./Webhooks.module.css";
import rs from "./RuleEditor.module.css";

/**
 * S-177 (issue 322) — the New / Edit rule dialog (DESIGN.md §5.9.5).
 * Sections, top to bottom:
 *  - When: events from the endpoint's allowlist, plus ANDed condition rows
 *    (field / op / value; `in` takes a comma list, `exists` takes no value).
 *    A default rule hides this section: it runs only when nothing else matches.
 *  - Run: the agent, then the repository (from a payload path or fixed), then
 *    the schema-driven param grid reused from invoke/schedule, plus optional
 *    "fill from the payload" rows for declared parameters.
 *  - Guardrails: auto-disable threshold, success notification, enabled.
 * The server validates on save (`resolveSaveRule`); its field errors render
 * inline and nothing is stored.
 */

const OPS: WebhookConditionOp[] = [
  "equals",
  "not_equals",
  "contains",
  "prefix",
  "suffix",
  "in",
  "exists",
];

interface CondRow {
  field: string;
  op: WebhookConditionOp;
  value: string;
}
interface PayloadRow {
  key: string;
  path: string;
}

function toRows(conditions: WebhookCondition[]): CondRow[] {
  return conditions.map((c) => ({
    field: c.field,
    op: c.op,
    value: Array.isArray(c.value) ? c.value.join(", ") : (c.value ?? ""),
  }));
}

function toConditions(rows: CondRow[]): WebhookCondition[] {
  return rows.map((r) => {
    if (r.op === "exists") return { field: r.field.trim(), op: r.op };
    if (r.op === "in") {
      return {
        field: r.field.trim(),
        op: r.op,
        value: r.value
          .split(",")
          .map((v) => v.trim())
          .filter(Boolean),
      };
    }
    return { field: r.field.trim(), op: r.op, value: r.value };
  });
}

function schemaDefaults(agent: AgentOption | undefined): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (!agent) return out;
  for (const f of buildFieldDescriptors(agent.paramsSchema))
    if (f.default !== undefined) out[f.name] = f.default;
  for (const [k, v] of Object.entries((agent.defaultParams as Record<string, unknown>) ?? {}))
    out[k] = v;
  return out;
}

export interface RuleDialogProps {
  endpointId: string;
  eventAllowlist: string[];
  rule: WebhookRuleRow | null;
  agents: AgentOption[];
  repositories: RepositoryOption[];
  onClose: () => void;
  onSaved: () => void;
}

export function RuleDialog({
  endpointId,
  eventAllowlist,
  rule,
  agents,
  repositories,
  onClose,
  onSaved,
}: RuleDialogProps) {
  const uid = useId();
  const nameRef = useRef<HTMLInputElement>(null);
  const [pending, startTransition] = useTransition();
  const enabledAgents = agents.filter((a) => a.isEnabled);

  const [name, setName] = useState(rule?.name ?? "");
  const [isDefault, setIsDefault] = useState(rule?.is_default ?? false);
  const [events, setEvents] = useState<string[]>(rule?.event_types ?? []);
  const [conds, setConds] = useState<CondRow[]>(toRows(rule?.conditions ?? []));
  const [agentId, setAgentId] = useState(rule?.agent_id ?? enabledAgents[0]?.id ?? "");
  const [repoMode, setRepoMode] = useState<"payload_field" | "fixed">(
    rule?.repo_mode ?? "payload_field",
  );
  const [repoPath, setRepoPath] = useState(rule?.repo_payload_field ?? "repository.full_name");
  const [repoId, setRepoId] = useState(rule?.repository_id ?? "");
  const agent = agents.find((a) => a.id === agentId);
  const [statics, setStatics] = useState<Record<string, unknown>>(
    rule ? { ...((rule.params.static as Record<string, unknown>) ?? {}) } : schemaDefaults(agent),
  );
  const [fromPayload, setFromPayload] = useState<PayloadRow[]>(
    Object.entries(rule?.params.from_payload ?? {}).map(([key, path]) => ({ key, path })),
  );
  const [threshold, setThreshold] = useState(String(rule?.auto_disable_threshold ?? 3));
  const [notify, setNotify] = useState(rule?.notify_on_success ?? false);
  const [enabled, setEnabled] = useState(rule?.is_enabled ?? true);
  const [errors, setErrors] = useState<RuleFieldErrors>({});
  const [banner, setBanner] = useState<string | null>(null);

  const fields = useMemo(() => (agent ? buildFieldDescriptors(agent.paramsSchema) : []), [agent]);

  useEffect(() => {
    nameRef.current?.focus();
  }, []);

  function onAgentChange(id: string) {
    setAgentId(id);
    setStatics(schemaDefaults(agents.find((a) => a.id === id)));
    setFromPayload([]);
  }

  function setCond(i: number, patch: Partial<CondRow>) {
    setConds((cur) => cur.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  }
  function setPayload(i: number, patch: Partial<PayloadRow>) {
    setFromPayload((cur) => cur.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  }

  function save() {
    const raw = {
      name,
      eventTypes: isDefault ? [] : events,
      conditions: isDefault ? [] : toConditions(conds),
      isDefault,
      agentId,
      repoMode,
      repositoryId: repoMode === "fixed" ? repoId || null : null,
      repoPayloadField: repoMode === "payload_field" ? repoPath : null,
      params: {
        static: statics,
        // Every row is sent, even half-filled, so the server flags it instead of it being dropped.
        from_payload: Object.fromEntries(fromPayload.map((r) => [r.key, r.path])),
      },
      autoDisableThreshold: Number(threshold),
      notifyOnSuccess: notify,
      isEnabled: enabled,
    };
    startTransition(async () => {
      const res = await saveRuleAction(endpointId, rule?.id ?? null, raw);
      if (res.ok) {
        onSaved();
        return;
      }
      setErrors("fieldErrors" in res ? res.fieldErrors : {});
      setBanner(res.message);
    });
  }

  const title = rule ? "Edit rule" : "New rule";
  const id = (s: string) => `${uid}-${s}`;
  const err = (k: keyof RuleFieldErrors) =>
    errors[k] ? (
      <span id={id(`${k}-err`)} className={styles.error}>
        {errors[k]}
      </span>
    ) : null;

  return (
    <div className={styles.overlay}>
      <div
        className={`${styles.dialog} ${rs.wide}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onKeyDown={(e) => {
          if (e.key === "Escape") onClose();
        }}
      >
        <header className={styles.header}>
          <h2 className={styles.title}>{title}</h2>
          <Button variant="ghost" size="sm" aria-label="Close" onClick={onClose}>
            ✕
          </Button>
        </header>

        <form
          className={styles.bodyPad}
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            save();
          }}
        >
          <div className={styles.field}>
            <label className={styles.label} htmlFor={id("name")}>
              Rule name
            </label>
            <input
              ref={nameRef}
              id={id("name")}
              className={styles.input}
              value={name}
              maxLength={100}
              placeholder="e.g. /audit comment → security-analyst"
              onChange={(e) => setName(e.target.value)}
            />
            {err("name")}
          </div>

          <div className={styles.switchRow}>
            <div className={styles.field}>
              <span className={styles.label} id={id("default")}>
                Default rule
              </span>
              <span className={styles.hint}>
                Runs only when no other rule matches. One per endpoint.
              </span>
              {err("isDefault")}
            </div>
            <Toggle checked={isDefault} onChange={setIsDefault} aria-labelledby={id("default")} />
          </div>

          {!isDefault && (
            <fieldset className={rs.group}>
              <legend className={rs.groupTitle}>When</legend>
              <div className={styles.checks} role="group" aria-label="Events">
                {eventAllowlist.map((e) => (
                  <label key={e} className={styles.check}>
                    <input
                      type="checkbox"
                      checked={events.includes(e)}
                      onChange={() =>
                        setEvents((cur) =>
                          cur.includes(e) ? cur.filter((x) => x !== e) : [...cur, e],
                        )
                      }
                    />
                    {e}
                  </label>
                ))}
              </div>
              {err("eventTypes")}

              <span className={styles.hint}>
                All conditions must hold. Paths use dots, e.g. comment.body.
              </span>
              {conds.map((c, i) => {
                const n = i + 1;
                const ops = OPS.includes(c.op) ? OPS : [...OPS, c.op];
                return (
                  <div key={i} className={rs.condRow}>
                    {c.op !== "matches_event" && (
                      <input
                        className={styles.input}
                        aria-label={`Condition ${n} field`}
                        placeholder="comment.body"
                        value={c.field}
                        onChange={(e) => setCond(i, { field: e.target.value })}
                      />
                    )}
                    <select
                      className={styles.input}
                      aria-label={`Condition ${n} operator`}
                      value={c.op}
                      onChange={(e) => setCond(i, { op: e.target.value as WebhookConditionOp })}
                    >
                      {ops.map((o) => (
                        <option key={o} value={o}>
                          {o.replace("_", " ")}
                        </option>
                      ))}
                    </select>
                    {c.op !== "exists" && (
                      <input
                        className={styles.input}
                        aria-label={`Condition ${n} value`}
                        placeholder={c.op === "in" ? "opened, reopened" : "/audit"}
                        value={c.value}
                        onChange={(e) => setCond(i, { value: e.target.value })}
                      />
                    )}
                    <button
                      type="button"
                      className={`${styles.iconBtn} ${styles.deleteBtn}`}
                      aria-label={`Remove condition ${n}`}
                      onClick={() => setConds((cur) => cur.filter((_, j) => j !== i))}
                    >
                      ✕
                    </button>
                  </div>
                );
              })}
              <div>
                <Button
                  variant="ghost"
                  size="sm"
                  type="button"
                  onClick={() =>
                    setConds((cur) => [...cur, { field: "", op: "equals", value: "" }])
                  }
                >
                  + Add condition
                </Button>
              </div>
              {err("conditions")}
            </fieldset>
          )}

          <fieldset className={rs.group}>
            <legend className={rs.groupTitle}>Run</legend>
            <div className={styles.field}>
              <label className={styles.label} htmlFor={id("agent")}>
                Agent
              </label>
              <select
                id={id("agent")}
                className={styles.input}
                value={agentId}
                onChange={(e) => onAgentChange(e.target.value)}
              >
                {agents.map((a) => (
                  <option key={a.id} value={a.id} disabled={!a.isEnabled}>
                    {a.name}
                    {a.isEnabled ? "" : " (disabled)"}
                  </option>
                ))}
              </select>
              {err("agentId")}
            </div>

            <div className={styles.field} role="radiogroup" aria-label="Repository source">
              <span className={styles.label}>Repository</span>
              <div className={styles.seg}>
                <label className={styles.segOpt}>
                  <input
                    type="radio"
                    name={id("repomode")}
                    checked={repoMode === "payload_field"}
                    onChange={() => setRepoMode("payload_field")}
                  />
                  From the payload
                </label>
                <label className={styles.segOpt}>
                  <input
                    type="radio"
                    name={id("repomode")}
                    checked={repoMode === "fixed"}
                    onChange={() => setRepoMode("fixed")}
                  />
                  Fixed repository
                </label>
              </div>
              {repoMode === "payload_field" ? (
                <>
                  <input
                    className={styles.input}
                    aria-label="Repository path"
                    value={repoPath}
                    onChange={(e) => setRepoPath(e.target.value)}
                  />
                  <span className={styles.hint}>
                    Must name a registered, enabled repository, or the delivery is rejected.
                  </span>
                  {err("repoPayloadField")}
                </>
              ) : (
                <>
                  <label className={styles.srOnly} htmlFor={id("repo")}>
                    Repository
                  </label>
                  <select
                    id={id("repo")}
                    className={styles.input}
                    value={repoId}
                    onChange={(e) => setRepoId(e.target.value)}
                  >
                    <option value="">Select…</option>
                    {repositories.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.fullName}
                      </option>
                    ))}
                  </select>
                  {err("repositoryId")}
                </>
              )}
            </div>

            <div className={styles.field}>
              <span className={styles.label}>Parameters</span>
              <div>
                {fields.map((f) => (
                  <FieldRow
                    key={`${agentId}-${f.name}`}
                    field={f}
                    value={statics[f.name]}
                    onChange={(k, v) => setStatics((cur) => ({ ...cur, [k]: v }))}
                  />
                ))}
                {fields.length === 0 && (
                  <span className={styles.hint}>This agent takes no parameters.</span>
                )}
              </div>
            </div>

            <div className={styles.field}>
              <span className={styles.label}>Fill from the payload</span>
              <span className={styles.hint}>
                Overrides the value above when the path exists. Only declared, single-value
                parameters.
              </span>
              {fromPayload.map((r, i) => (
                <div key={i} className={rs.condRow}>
                  <select
                    className={styles.input}
                    aria-label={`Payload parameter ${i + 1} name`}
                    value={r.key}
                    onChange={(e) => setPayload(i, { key: e.target.value })}
                  >
                    <option value="">Select…</option>
                    {fields
                      .filter((f) => f.control !== "unsupported")
                      .map((f) => (
                        <option key={f.name} value={f.name}>
                          {f.name}
                        </option>
                      ))}
                    {r.key && !fields.some((f) => f.name === r.key) && (
                      <option value={r.key}>{r.key}</option>
                    )}
                  </select>
                  <input
                    className={styles.input}
                    aria-label={`Payload parameter ${i + 1} path`}
                    placeholder="issue.number"
                    value={r.path}
                    onChange={(e) => setPayload(i, { path: e.target.value })}
                  />
                  <button
                    type="button"
                    className={`${styles.iconBtn} ${styles.deleteBtn}`}
                    aria-label={`Remove payload parameter ${i + 1}`}
                    onClick={() => setFromPayload((cur) => cur.filter((_, j) => j !== i))}
                  >
                    ✕
                  </button>
                </div>
              ))}
              <div>
                <Button
                  variant="ghost"
                  size="sm"
                  type="button"
                  aria-label="Fill a parameter from the payload"
                  onClick={() => setFromPayload((cur) => [...cur, { key: "", path: "" }])}
                >
                  + Add payload value
                </Button>
              </div>
              {err("params")}
            </div>
          </fieldset>

          <fieldset className={rs.group}>
            <legend className={rs.groupTitle}>Guardrails</legend>
            <div className={styles.field}>
              <label className={styles.label} htmlFor={id("threshold")}>
                Disable after consecutive failed starts
              </label>
              <input
                id={id("threshold")}
                type="number"
                min={1}
                max={100}
                className={`${styles.input} ${rs.narrow}`}
                value={threshold}
                onChange={(e) => setThreshold(e.target.value)}
              />
              {err("autoDisableThreshold")}
            </div>
            <div className={styles.switchRow}>
              <span className={styles.label} id={id("notify")}>
                Notify me when a run succeeds
              </span>
              <Toggle checked={notify} onChange={setNotify} aria-labelledby={id("notify")} />
            </div>
            <div className={styles.switchRow}>
              <span className={styles.label} id={id("enabled")}>
                Enabled
              </span>
              <Toggle checked={enabled} onChange={setEnabled} aria-labelledby={id("enabled")} />
            </div>
            <span className={styles.hint}>
              Always on: no run starts while one is active for the same agent and repository, or
              while its last PR is open, and the fleet-wide concurrency cap applies.
            </span>
          </fieldset>

          <div className={styles.footer} style={{ padding: 0, border: 0 }}>
            {/* Next to Save, so it's visible however far the form is scrolled. */}
            {banner && (
              <span className={styles.footerError} role="status">
                {banner}
              </span>
            )}
            <Button variant="ghost" type="button" onClick={onClose}>
              Cancel
            </Button>
            <Button variant="primary" type="submit" disabled={pending}>
              {pending ? "Saving…" : "Save rule"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
