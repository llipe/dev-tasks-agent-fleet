"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import type { AnySchema } from "ajv";

import { buildFieldDescriptors } from "@/lib/schema/form";
import { getValidator } from "@/lib/schema/ajv";
import { Button } from "@/components/Button";
import { KLabel } from "@/components/KLabel";
import { FieldRow } from "./FieldRow";
import { RepositorySelect, type RepositoryOption } from "./RepositorySelect";
import { SchemaPreview } from "./SchemaPreview";
import { SuccessState } from "./SuccessState";
import styles from "./InvokeDialog.module.css";

/**
 * S-113 (issue 126) — the schema-driven invoke dialog (DESIGN §5.4).
 *
 * A centered dialog (max-width 760px, `--shadow-lg`) whose entire field list is
 * generated from `agents.params_schema` via `buildFieldDescriptors` — proving
 * FR16/AC7 (a new agent is a row, not a deploy). The repository selector renders
 * separately (outside params) only when `requiresRepository` is true.
 *
 * Client Ajv re-validation shares `lib/schema/ajv.ts` with the S-112 route, so
 * the client is never more lenient than the server; the server remains
 * authoritative (a rejected submission leaves no `runs` row).
 *
 * On 202 → navigate to `/runs/[id]` (SuccessState first). On 502 → also
 * navigate (the run shows `failed_to_start`). Errors render inline per field
 * for INVALID_PARAMS, as a banner otherwise.
 */
export interface InvokeDialogProps {
  slug: string;
  agentName: string;
  schema: unknown;
  defaultParams: Record<string, unknown>;
  requiresRepository: boolean;
  repositories: RepositoryOption[];
}

type FieldErrors = Record<string, string>;

export function InvokeDialog(props: InvokeDialogProps) {
  const router = useRouter();
  const fields = useMemo(() => buildFieldDescriptors(props.schema), [props.schema]);

  // Initial values: schema `default` first, then agents.default_params overrides
  // (task 2.11). Descriptor defaults are the source of truth for shape.
  const initialValues = useMemo(() => {
    const v: Record<string, unknown> = {};
    for (const f of fields) {
      if (f.default !== undefined) v[f.name] = f.default;
    }
    for (const [k, val] of Object.entries(props.defaultParams ?? {})) {
      if (fields.some((f) => f.name === k)) v[k] = val;
    }
    return v;
  }, [fields, props.defaultParams]);

  const [values, setValues] = useState<Record<string, unknown>>(initialValues);
  const [repositoryId, setRepositoryId] = useState<string | null>(
    props.repositories.length > 0 ? null : null,
  );
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [banner, setBanner] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState<{ runId: string; accepted: boolean } | null>(null);

  const noRepositories = props.requiresRepository && props.repositories.length === 0;
  const missingRepository = props.requiresRepository && !repositoryId;

  function setField(name: string, value: unknown) {
    setValues((prev) => ({ ...prev, [name]: value }));
    setFieldErrors((prev) => {
      if (!prev[name]) return prev;
      const next = { ...prev };
      delete next[name];
      return next;
    });
  }

  /** Project current values to schema-present keys only (never extra keys). */
  function collectParams(): Record<string, unknown> {
    const params: Record<string, unknown> = {};
    for (const f of fields) {
      if (f.control === "unsupported") continue; // never submit an uneditable key
      if (values[f.name] !== undefined) params[f.name] = values[f.name];
    }
    return params;
  }

  /** Client Ajv re-validation (shared strictness with the server). */
  function validateClientSide(params: Record<string, unknown>): FieldErrors | null {
    const validate = getValidator(props.slug, props.schema as AnySchema);
    if (validate(params)) return null;
    const errs: FieldErrors = {};
    for (const e of validate.errors ?? []) {
      // instancePath like "/fix_mode"; missingProperty for required at root.
      const path = e.instancePath.replace(/^\//, "");
      const key =
        path ||
        (e.params && "missingProperty" in e.params
          ? (e.params as { missingProperty: string }).missingProperty
          : "");
      if (key) errs[key] = e.message ?? "is invalid";
      else setBanner(e.message ?? "Invalid parameters.");
    }
    return Object.keys(errs).length > 0 ? errs : null;
  }

  async function onSubmit() {
    setBanner(null);
    setFieldErrors({});

    if (missingRepository) {
      setBanner("Select a repository before running.");
      return;
    }

    const params = collectParams();
    const clientErrors = validateClientSide(params);
    if (clientErrors) {
      setFieldErrors(clientErrors);
      return;
    }

    setSubmitting(true);
    try {
      const res = await fetch(`/api/agents/${props.slug}/invoke`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          repository_id: props.requiresRepository ? repositoryId : undefined,
          params,
        }),
      });

      const json = (await res.json().catch(() => ({}))) as {
        run_id?: string;
        status?: string;
        error?: { code?: string; message?: string; details?: unknown };
      };

      if (res.status === 202 && json.run_id) {
        setSuccess({ runId: json.run_id, accepted: true });
        router.push(`/runs/${json.run_id}`);
        return;
      }

      // A 502 that carries a run_id still navigates — the run is visible as
      // failed_to_start (AC24).
      if (res.status === 502 && json.run_id) {
        setSuccess({ runId: json.run_id, accepted: false });
        router.push(`/runs/${json.run_id}`);
        return;
      }

      // Error handling: inline per-field for INVALID_PARAMS, banner otherwise.
      const code = json.error?.code ?? "ERROR";
      if (code === "INVALID_PARAMS" && Array.isArray(json.error?.details)) {
        const errs: FieldErrors = {};
        for (const d of json.error!.details as Array<{ instancePath?: string; message?: string }>) {
          const key = (d.instancePath ?? "").replace(/^\//, "");
          if (key) errs[key] = d.message ?? "is invalid";
        }
        if (Object.keys(errs).length > 0) setFieldErrors(errs);
        else setBanner(json.error?.message ?? "Invalid parameters.");
      } else {
        setBanner(json.error?.message ?? "The invocation failed.");
      }
    } catch {
      setBanner("Could not reach the server. Try again.");
    } finally {
      setSubmitting(false);
    }
  }

  if (success) {
    return (
      <div className={styles.overlay}>
        <div className={styles.dialog} role="dialog" aria-modal="true" aria-label="Invoke result">
          <SuccessState runId={success.runId} accepted={success.accepted} />
        </div>
      </div>
    );
  }

  const runDisabled = submitting || noRepositories || missingRepository;

  return (
    <div className={styles.overlay}>
      <div
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-label={`Invoke ${props.agentName}`}
      >
        <header className={styles.header}>
          <div className={styles.headings}>
            <KLabel>Invoke agent</KLabel>
            <h1 className={styles.title}>{props.agentName}</h1>
            <span className={styles.slug}>{props.slug}</span>
          </div>
          <Button
            variant="ghost"
            size="sm"
            aria-label="Cancel"
            onClick={() => router.push(`/agents/${props.slug}`)}
          >
            Close
          </Button>
        </header>

        {banner && (
          <div className={styles.banner} role="alert">
            {banner}
          </div>
        )}

        <div className={styles.body}>
          {props.requiresRepository && (
            <RepositorySelect
              repositories={props.repositories}
              value={repositoryId}
              onChange={setRepositoryId}
            />
          )}

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

          <SchemaPreview schema={props.schema} />
        </div>

        <footer className={styles.footer}>
          <span className={styles.hint}>
            Submits to <code>POST /api/agents/{props.slug}/invoke</code>
          </span>
          <div className={styles.actions}>
            <Button variant="secondary" onClick={() => router.push(`/agents/${props.slug}`)}>
              Cancel
            </Button>
            <Button variant="primary" onClick={onSubmit} disabled={runDisabled}>
              {submitting ? "Running…" : "Run"}
            </Button>
          </div>
        </footer>
      </div>
    </div>
  );
}
