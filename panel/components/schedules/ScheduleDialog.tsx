"use client";

import { useEffect, useMemo, useRef, useState, useTransition } from "react";

import { Button } from "@/components/Button";
import { KLabel } from "@/components/KLabel";
import { Toggle } from "@/components/Toggle";
import { Input } from "@/components/Input";
import { LockIcon, CaretDownIcon, CaretRightIcon } from "@/components/icons";
import { FieldRow } from "@/components/invoke/FieldRow";
import { buildFieldDescriptors } from "@/lib/schema/form";
import { cadenceSummary, type CadenceKind } from "@/lib/domain/cadence";
import { saveScheduleAction, previewScheduleAction } from "@/app/(panel)/schedules/actions";
import type { Json, VScheduleRow } from "@/lib/supabase/types";

import { CadencePicker } from "./CadencePicker";
import styles from "./ScheduleDialog.module.css";

/**
 * S-162 (issue 274) — the New / Edit schedule dialog (DESIGN.md §5.7.2). Same dialog
 * shell family as the §5.4 Invoke dialog. Agent + (conditional) repository
 * selects, a schema-driven `FieldRow` param grid (reused from invoke), the
 * cadence segmented picker with a live Preview sourced from the authoritative
 * RPC (SD-T6, via `previewScheduleAction`), the collapsible guardrails, and the
 * submit that calls `saveScheduleAction` (create or edit).
 */
export interface AgentOption {
  id: string;
  slug: string;
  name: string;
  isEnabled: boolean;
  requiresRepository: boolean;
  paramsSchema: Json;
  defaultParams: Json;
}
export interface RepositoryOption {
  id: string;
  fullName: string;
  defaultBranch: string;
}

export interface ScheduleDialogProps {
  mode: "new" | "edit";
  schedule: VScheduleRow | null;
  agents: AgentOption[];
  repositories: RepositoryOption[];
  onClose: () => void;
  onSuccess: (id: string) => void;
}

interface CadenceState {
  kind: CadenceKind;
  minute: number | null;
  hour: number | null;
  weekday: number | null;
  intervalHours: number | null;
  cron: string | null;
  timezone: string;
}

export function ScheduleDialog(props: ScheduleDialogProps) {
  const { schedule } = props;
  const [pending, startTransition] = useTransition();

  const [agentId, setAgentId] = useState<string>(
    schedule?.agent_id ?? props.agents.find((a) => a.isEnabled)?.id ?? "",
  );
  const agent = useMemo(
    () => props.agents.find((a) => a.id === agentId) ?? null,
    [props.agents, agentId],
  );

  const fields = useMemo(() => (agent ? buildFieldDescriptors(agent.paramsSchema) : []), [agent]);

  const [repositoryId, setRepositoryId] = useState<string | null>(schedule?.repository_id ?? null);
  const [values, setValues] = useState<Record<string, unknown>>(
    (schedule?.params as Record<string, unknown> | undefined) ?? {},
  );
  const [cadence, setCadence] = useState<CadenceState>({
    kind: schedule?.cadence_kind ?? "daily",
    minute: schedule?.cadence_minute ?? 0,
    hour: schedule?.cadence_hour ?? 7,
    weekday: schedule?.cadence_weekday ?? 1,
    intervalHours: schedule?.cadence_interval_hours ?? 6,
    cron: schedule?.cadence_cron ?? "",
    timezone: schedule?.timezone ?? "America/Santiago",
  });
  const [threshold, setThreshold] = useState<number>(schedule?.auto_pause_threshold ?? 3);
  const [notifyOnSuccess, setNotifyOnSuccess] = useState<boolean>(
    schedule?.notify_on_success ?? false,
  );
  const [showGuardrails, setShowGuardrails] = useState(false);

  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [cadenceErrors, setCadenceErrors] = useState<Record<string, string>>({});
  const [banner, setBanner] = useState<string | null>(null);
  const [submittedInvalid, setSubmittedInvalid] = useState(false);

  // Live preview (next 3 runs) from the RPC — debounced on cadence change.
  const [preview, setPreview] = useState<string[]>([]);
  const previewSeq = useRef(0);
  useEffect(() => {
    const seq = ++previewSeq.current;
    const t = setTimeout(async () => {
      const res = await previewScheduleAction({
        kind: cadence.kind,
        minute: cadence.minute,
        hour: cadence.hour,
        weekday: cadence.weekday,
        intervalHours: cadence.intervalHours,
        cron: cadence.cron,
        timezone: cadence.timezone,
      });
      if (seq === previewSeq.current) setPreview(res);
    }, 250);
    return () => clearTimeout(t);
  }, [cadence]);

  // Changing the agent resets params to that agent's schema defaults.
  function onAgentChange(id: string) {
    setAgentId(id);
    const next = props.agents.find((a) => a.id === id);
    const defaults: Record<string, unknown> = {};
    if (next) {
      for (const f of buildFieldDescriptors(next.paramsSchema)) {
        if (f.default !== undefined) defaults[f.name] = f.default;
      }
      for (const [k, v] of Object.entries((next.defaultParams as Record<string, unknown>) ?? {})) {
        defaults[k] = v;
      }
    }
    setValues(defaults);
    setRepositoryId(null);
    setFieldErrors({});
  }

  function setField(name: string, value: unknown) {
    setValues((prev) => ({ ...prev, [name]: value }));
    setFieldErrors((prev) => {
      if (!prev[name]) return prev;
      const n = { ...prev };
      delete n[name];
      return n;
    });
  }

  function collectParams(): Record<string, unknown> {
    const params: Record<string, unknown> = {};
    for (const f of fields) {
      if (f.control === "unsupported") continue;
      if (values[f.name] !== undefined) params[f.name] = values[f.name];
    }
    return params;
  }

  const missingRepository = Boolean(agent?.requiresRepository) && !repositoryId;

  async function onSubmit() {
    setBanner(null);
    setFieldErrors({});
    setCadenceErrors({});
    const res = await new Promise<Awaited<ReturnType<typeof saveScheduleAction>>>((resolve) => {
      startTransition(async () => {
        resolve(
          await saveScheduleAction({
            scheduleId: schedule?.id ?? null,
            agentId,
            repositoryId,
            name: schedule?.name ?? null,
            params: collectParams(),
            cadenceKind: cadence.kind,
            cadenceMinute: cadence.minute,
            cadenceHour: cadence.hour,
            cadenceWeekday: cadence.weekday,
            cadenceIntervalHours: cadence.intervalHours,
            cadenceCron: cadence.cron,
            timezone: cadence.timezone,
            autoPauseThreshold: threshold,
            notifyOnSuccess,
          }),
        );
      });
    });

    if (res.ok) {
      props.onSuccess(res.id);
      return;
    }
    setSubmittedInvalid(true);
    if (res.fieldErrors) {
      const params: Record<string, string> = {};
      const cad: Record<string, string> = {};
      for (const [k, v] of Object.entries(res.fieldErrors)) {
        if (k.startsWith("params.")) params[k.slice("params.".length)] = v;
        else cad[k] = v;
      }
      setFieldErrors(params);
      setCadenceErrors(cad);
    }
    setBanner(res.message);
  }

  const cadenceValid = Object.keys(cadenceErrors).length === 0;
  const title = props.mode === "edit" ? "Edit schedule" : "New schedule";

  return (
    <div className={styles.overlay}>
      <div className={styles.dialog} role="dialog" aria-modal="true" aria-label={title}>
        <header className={styles.header}>
          <div>
            <h1 className={styles.title}>{title}</h1>
            {agent && <span className={styles.slug}>{agent.slug}</span>}
          </div>
          <Button variant="ghost" size="sm" aria-label="Close" onClick={props.onClose}>
            ✕
          </Button>
        </header>

        {banner && (
          <div className={styles.banner} role="alert">
            {banner}
          </div>
        )}

        <div className={styles.body}>
          <label className={styles.fieldLabel} htmlFor="sch-agent">
            Agent
          </label>
          <select
            id="sch-agent"
            className={styles.select}
            value={agentId}
            onChange={(e) => onAgentChange(e.target.value)}
          >
            {props.agents.map((a) => (
              <option key={a.id} value={a.id} disabled={!a.isEnabled}>
                {a.name}
                {a.isEnabled ? "" : " (disabled)"}
              </option>
            ))}
          </select>

          {agent?.requiresRepository && (
            <>
              <label className={styles.fieldLabel} htmlFor="sch-repo">
                Repository
              </label>
              <select
                id="sch-repo"
                className={styles.select}
                value={repositoryId ?? ""}
                onChange={(e) => setRepositoryId(e.target.value || null)}
              >
                <option value="" disabled>
                  Select a repository…
                </option>
                {props.repositories.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.fullName}
                  </option>
                ))}
              </select>
              <p
                className={
                  missingRepository && submittedInvalid ? styles.repoHintError : styles.repoHint
                }
              >
                {repositoryId
                  ? `branch: ${props.repositories.find((r) => r.id === repositoryId)?.defaultBranch ?? "main"} (default)`
                  : submittedInvalid
                    ? "required — pick a repository"
                    : `${props.repositories.length} repos connected`}
              </p>
            </>
          )}

          <KLabel>Parameters</KLabel>
          {fields.length === 0 ? (
            <p className={styles.noParams}>This agent takes no parameters.</p>
          ) : (
            fields.map((f) => (
              <FieldRow
                key={f.name}
                field={f}
                value={values[f.name]}
                onChange={setField}
                error={fieldErrors[f.name]}
              />
            ))
          )}

          <KLabel>Cadence</KLabel>
          <CadencePicker
            value={cadence}
            errors={cadenceErrors}
            summary={cadenceSummary({
              kind: cadence.kind,
              minute: cadence.minute,
              hour: cadence.hour,
              weekday: cadence.weekday,
              intervalHours: cadence.intervalHours,
              cron: cadence.cron,
            })}
            preview={preview}
            onChange={(patch) => setCadence((prev) => ({ ...prev, ...patch }))}
          />

          <button
            type="button"
            className={styles.disclosure}
            aria-expanded={showGuardrails}
            onClick={() => setShowGuardrails((s) => !s)}
          >
            {showGuardrails ? <CaretDownIcon size={13} /> : <CaretRightIcon size={13} />}
            Advanced · guardrails
            {!showGuardrails && (
              <span className={styles.disclosureHint}>
                pause after {threshold} · success email {notifyOnSuccess ? "on" : "off"}
              </span>
            )}
          </button>
          {showGuardrails && (
            <div className={styles.guardrails}>
              <label className={styles.guardLabel} htmlFor="sch-threshold">
                Auto-pause after failures
              </label>
              <Input
                id="sch-threshold"
                type="number"
                min={1}
                value={String(threshold)}
                onChange={(e) => setThreshold(Math.max(1, Number(e.target.value) || 1))}
              />
              <div className={styles.guardToggleRow}>
                <span>Email me when a run succeeds</span>
                <Toggle
                  checked={notifyOnSuccess}
                  aria-label="Email me when a run succeeds"
                  onChange={setNotifyOnSuccess}
                />
              </div>
              <p className={styles.guardNote}>
                Failures and auto-pauses always notify; successes otherwise appear only in the daily
                digest.
              </p>
              <p className={styles.guardAlways}>
                <LockIcon size={12} aria-hidden="true" /> Won&apos;t fire while a prior run is still
                active
              </p>
              <p className={styles.guardAlways}>
                <LockIcon size={12} aria-hidden="true" /> Won&apos;t fire while a prior run&apos;s
                PR is open
              </p>
            </div>
          )}
        </div>

        <footer className={styles.footer}>
          <span className={banner ? styles.footerHintError : styles.footerHint}>
            {banner ? "Fix the highlighted fields to continue" : "POST /schedules"}
          </span>
          <div className={styles.footerActions}>
            <Button variant="secondary" onClick={props.onClose} disabled={pending}>
              Cancel
            </Button>
            <Button variant="primary" onClick={onSubmit} disabled={pending || !cadenceValid}>
              {pending
                ? props.mode === "edit"
                  ? "Saving…"
                  : "Creating…"
                : props.mode === "edit"
                  ? "Save"
                  : "Create schedule"}
            </Button>
          </div>
        </footer>
      </div>
    </div>
  );
}
