"use client";

import { useCallback, useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/Button";
import { KLabel } from "@/components/KLabel";
import { NewScheduleIcon } from "@/components/icons";
import type { WebhookEndpointListRow } from "@/lib/supabase/queries";
import {
  createEndpointAction,
  deleteEndpointAction,
  rotateSecretAction,
  toggleEndpointAction,
  updateEndpointAction,
} from "@/app/(panel)/webhooks/actions";

import { EndpointForm, type EndpointFormValues, type EndpointSubmitResult } from "./EndpointForm";
import { SecretReveal } from "./SecretReveal";
import { webhookUrl } from "@/lib/webhooks/request-origin";
import { WebhooksTable } from "./WebhooksTable";
import styles from "./Webhooks.module.css";

/**
 * S-176 (issue 321) — the client controller for `/webhooks` (DESIGN.md §5.9). Owns
 * the New/Edit dialog, the delete and rotate confirms, and the show-once secret.
 * Every mutation ends in `router.refresh()`: the server re-reads the list, with
 * no optimistic edits.
 *
 * The secret returned by create or rotate is held in `reveal` state only
 * while the SecretReveal dialog is open. Dismissing sets it to null.
 */
export interface WebhooksClientProps {
  rows: WebhookEndpointListRow[];
  baseUrl: string;
}

type Reveal = { name: string; secret: string; url: string; rotated: boolean };

export function WebhooksClient({ rows, baseUrl }: WebhooksClientProps) {
  const router = useRouter();
  const [, startTransition] = useTransition();
  const [form, setForm] = useState<
    { mode: "new" } | { mode: "edit"; row: WebhookEndpointListRow } | null
  >(null);
  const [confirmDelete, setConfirmDelete] = useState<WebhookEndpointListRow | null>(null);
  const [confirmRotate, setConfirmRotate] = useState<WebhookEndpointListRow | null>(null);
  const [reveal, setReveal] = useState<Reveal | null>(null);
  const [alert, setAlert] = useState<string | null>(null);
  const [flashId, setFlashId] = useState<string | null>(null);

  const submit = useCallback(
    async (values: EndpointFormValues): Promise<EndpointSubmitResult> => {
      if (!form) return { ok: false, message: "Nothing to save." };
      if (form.mode === "new") {
        const res = await createEndpointAction(values);
        if (!res.ok)
          return {
            ok: false,
            message: res.message,
            fieldErrors: "fieldErrors" in res ? res.fieldErrors : undefined,
          };
        setForm(null);
        setFlashId(res.id);
        setReveal({
          name: values.name,
          secret: res.secret,
          url: webhookUrl(baseUrl, res.urlToken),
          rotated: false,
        });
        return { ok: true };
      }
      const res = await updateEndpointAction(form.row.id, values);
      if (!res.ok)
        return {
          ok: false,
          message: res.message,
          fieldErrors: "fieldErrors" in res ? res.fieldErrors : undefined,
        };
      setFlashId(form.row.id);
      setForm(null);
      router.refresh();
      return { ok: true };
    },
    [form, baseUrl, router],
  );

  const runMutation = useCallback(
    (fn: () => Promise<{ ok: boolean; message?: string }>) => {
      setAlert(null);
      startTransition(async () => {
        const res = await fn();
        if (!res.ok) setAlert(res.message ?? "Something went wrong. Try again.");
        router.refresh();
      });
    },
    [router],
  );

  async function rotate(row: WebhookEndpointListRow) {
    setConfirmRotate(null);
    setAlert(null);
    const res = await rotateSecretAction(row.id);
    if (!res.ok) {
      setAlert(res.message);
      return;
    }
    setReveal({
      name: row.name,
      secret: res.secret,
      url: webhookUrl(baseUrl, row.url_token),
      rotated: true,
    });
  }

  const newButton = (
    <Button variant="primary" onClick={() => setForm({ mode: "new" })}>
      <NewScheduleIcon size={14} aria-hidden="true" /> New endpoint
    </Button>
  );

  return (
    <>
      <div className={styles.actionsBar}>{newButton}</div>
      {alert && (
        <p className={styles.banner} role="alert">
          {alert}
        </p>
      )}

      {rows.length === 0 ? (
        <div className={styles.empty} role="status">
          <KLabel>Webhooks</KLabel>
          <p className={styles.emptyBody}>
            No webhook endpoints yet. Create one to get a URL and secret for GitHub.
          </p>
          {newButton}
        </div>
      ) : (
        <WebhooksTable
          rows={rows}
          baseUrl={baseUrl}
          flashId={flashId}
          onToggle={(row) => runMutation(() => toggleEndpointAction(row.id, !row.is_enabled))}
          onEdit={(row) => setForm({ mode: "edit", row })}
          onRotate={(row) => setConfirmRotate(row)}
          onDelete={(row) => setConfirmDelete(row)}
        />
      )}

      {form && (
        <EndpointForm
          mode={form.mode}
          endpoint={form.mode === "edit" ? form.row : null}
          onClose={() => setForm(null)}
          onSubmit={submit}
        />
      )}

      {confirmDelete && (
        <Confirm
          label="Delete endpoint"
          title="Delete endpoint?"
          confirmText="Delete endpoint"
          onCancel={() => setConfirmDelete(null)}
          onConfirm={() => {
            const row = confirmDelete;
            setConfirmDelete(null);
            runMutation(() => deleteEndpointAction(row.id));
          }}
        >
          <strong>{confirmDelete.name || "This endpoint"}</strong> and its{" "}
          <strong>
            {confirmDelete.rule_count} rule{confirmDelete.rule_count === 1 ? "" : "s"}
          </strong>{" "}
          will be deleted, along with its delivery log and its secret. Its URL stops working. Runs
          it already started are kept.
        </Confirm>
      )}

      {confirmRotate && (
        <Confirm
          label="Rotate secret"
          title="Rotate the signing secret?"
          confirmText="Rotate secret"
          onCancel={() => setConfirmRotate(null)}
          onConfirm={() => rotate(confirmRotate)}
        >
          The old secret stops working immediately for{" "}
          <strong>{confirmRotate.name || "this endpoint"}</strong>. Update the sender&apos;s secret
          right away, or its deliveries return 401.
        </Confirm>
      )}

      {reveal && (
        <SecretReveal
          endpointName={reveal.name}
          secret={reveal.secret}
          url={reveal.url}
          rotated={reveal.rotated}
          onDone={() => {
            setReveal(null);
            router.refresh();
          }}
        />
      )}
    </>
  );
}

function Confirm({
  label,
  title,
  confirmText,
  children,
  onCancel,
  onConfirm,
}: {
  label: string;
  title: string;
  confirmText: string;
  children: React.ReactNode;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className={styles.overlay}>
      <div
        className={`${styles.dialog} ${styles.small}`}
        role="alertdialog"
        aria-modal="true"
        aria-label={label}
        onKeyDown={(e) => {
          if (e.key === "Escape") onCancel();
        }}
      >
        <header className={styles.header}>
          <h2 className={styles.title}>{title}</h2>
        </header>
        <div className={styles.bodyPad}>
          <p className={styles.dialogBody}>{children}</p>
        </div>
        <div className={styles.footer}>
          <Button variant="ghost" size="sm" onClick={onCancel} autoFocus>
            Cancel
          </Button>
          <Button variant="secondary" size="sm" className={styles.destructive} onClick={onConfirm}>
            {confirmText}
          </Button>
        </div>
      </div>
    </div>
  );
}
