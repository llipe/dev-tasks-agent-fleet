"use client";

import { useEffect, useId, useRef, useState, useTransition } from "react";

import { Button } from "@/components/Button";
import { Toggle } from "@/components/Toggle";
import {
  GITHUB_DEFAULT_HEADERS,
  GITHUB_EVENT_OPTIONS,
  type EndpointFieldErrors,
} from "@/lib/domain/webhook-endpoint-save";
import type { WebhookSource } from "@/lib/supabase/types";
import type { WebhookEndpointListRow } from "@/lib/supabase/queries";

import styles from "./Webhooks.module.css";

/**
 * S-176 (issue 321) — the New / Edit endpoint dialog (DESIGN.md §5.9.1). The source
 * is chosen at creation and fixed afterwards. GitHub's header names are fixed;
 * a generic sender sets its own (D-W15). Events are common GitHub names as
 * checkboxes plus a free-text "Other events" field. The server re-validates
 * everything; its field errors render inline.
 */

export interface EndpointFormValues {
  name: string;
  source: WebhookSource;
  eventAllowlist: string[];
  ignoreBotAuthor: boolean;
  signatureHeader: string;
  deliveryIdHeader: string;
  isEnabled: boolean;
}

export type EndpointSubmitResult =
  | { ok: true }
  | { ok: false; message: string; fieldErrors?: EndpointFieldErrors };

const GENERIC_DEFAULT_HEADERS = {
  signatureHeader: "x-signature-256",
  deliveryIdHeader: "x-delivery-id",
};

export interface EndpointFormProps {
  mode: "new" | "edit";
  endpoint: WebhookEndpointListRow | null;
  onClose: () => void;
  onSubmit: (values: EndpointFormValues) => Promise<EndpointSubmitResult>;
}

export function EndpointForm({ mode, endpoint, onClose, onSubmit }: EndpointFormProps) {
  const uid = useId();
  const nameRef = useRef<HTMLInputElement>(null);
  const [pending, startTransition] = useTransition();
  const known = new Set<string>(GITHUB_EVENT_OPTIONS);

  const [name, setName] = useState(endpoint?.name ?? "");
  const [source, setSource] = useState<WebhookSource>(endpoint?.source ?? "github");
  const [checked, setChecked] = useState<string[]>(
    endpoint ? endpoint.event_allowlist.filter((e) => known.has(e)) : [],
  );
  const [other, setOther] = useState(
    endpoint ? endpoint.event_allowlist.filter((e) => !known.has(e)).join(", ") : "",
  );
  const [ignoreBot, setIgnoreBot] = useState(endpoint?.ignore_bot_author ?? true);
  const [enabled, setEnabled] = useState(endpoint?.is_enabled ?? true);
  const [sigHeader, setSigHeader] = useState(
    endpoint?.source === "generic"
      ? endpoint.signature_header
      : GENERIC_DEFAULT_HEADERS.signatureHeader,
  );
  const [delHeader, setDelHeader] = useState(
    endpoint?.source === "generic"
      ? endpoint.delivery_id_header
      : GENERIC_DEFAULT_HEADERS.deliveryIdHeader,
  );
  const [errors, setErrors] = useState<EndpointFieldErrors>({});
  const [banner, setBanner] = useState<string | null>(null);

  useEffect(() => {
    nameRef.current?.focus();
  }, []);

  function toggleEvent(e: string) {
    setChecked((cur) => (cur.includes(e) ? cur.filter((x) => x !== e) : [...cur, e]));
  }

  function submit() {
    const extra = other
      .split(/[\s,]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    const values: EndpointFormValues = {
      name,
      source,
      eventAllowlist: [...checked, ...extra],
      ignoreBotAuthor: ignoreBot,
      ...(source === "generic"
        ? { signatureHeader: sigHeader, deliveryIdHeader: delHeader }
        : { ...GITHUB_DEFAULT_HEADERS }),
      isEnabled: enabled,
    };
    startTransition(async () => {
      const res = await onSubmit(values);
      if (!res.ok) {
        setErrors(res.fieldErrors ?? {});
        setBanner(res.message);
      }
    });
  }

  const title = mode === "edit" ? "Edit endpoint" : "New endpoint";
  const ids = {
    name: `${uid}-name`,
    other: `${uid}-other`,
    sig: `${uid}-sig`,
    del: `${uid}-del`,
    bot: `${uid}-bot`,
    enabled: `${uid}-enabled`,
  };

  return (
    <div className={styles.overlay}>
      <div
        className={styles.dialog}
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
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
          noValidate
        >
          {banner && <p className={styles.banner}>{banner}</p>}

          <div className={styles.field}>
            <label className={styles.label} htmlFor={ids.name}>
              Name
            </label>
            <input
              ref={nameRef}
              id={ids.name}
              className={`${styles.input} ${errors.name ? styles.invalid : ""}`}
              value={name}
              maxLength={100}
              onChange={(e) => setName(e.target.value)}
              aria-invalid={Boolean(errors.name)}
              aria-describedby={errors.name ? `${ids.name}-err` : undefined}
            />
            {errors.name && (
              <span id={`${ids.name}-err`} className={styles.error}>
                {errors.name}
              </span>
            )}
          </div>

          {mode === "new" ? (
            <fieldset className={styles.field} style={{ border: 0, padding: 0, margin: 0 }}>
              <legend className={styles.label}>Source</legend>
              <div className={styles.seg}>
                {(["github", "generic"] as const).map((s) => (
                  <label key={s} className={styles.segOpt}>
                    <input
                      type="radio"
                      name={`${uid}-source`}
                      value={s}
                      checked={source === s}
                      onChange={() => setSource(s)}
                    />
                    {s === "github" ? "GitHub" : "Generic"}
                  </label>
                ))}
              </div>
              <span className={styles.hint}>
                {source === "github"
                  ? "Signed with X-Hub-Signature-256. The source can't be changed later."
                  : "HMAC-SHA256 sha256=<hex> over the raw body, in a header you choose."}
              </span>
            </fieldset>
          ) : (
            <div className={styles.field}>
              <span className={styles.label}>Source</span>
              <span className={styles.faint}>{source} (fixed)</span>
            </div>
          )}

          {source === "generic" && (
            <>
              <div className={styles.field}>
                <label className={styles.label} htmlFor={ids.sig}>
                  Signature header
                </label>
                <input
                  id={ids.sig}
                  className={`${styles.input} ${errors.signatureHeader ? styles.invalid : ""}`}
                  value={sigHeader}
                  onChange={(e) => setSigHeader(e.target.value)}
                  aria-invalid={Boolean(errors.signatureHeader)}
                />
                {errors.signatureHeader && (
                  <span className={styles.error}>{errors.signatureHeader}</span>
                )}
              </div>
              <div className={styles.field}>
                <label className={styles.label} htmlFor={ids.del}>
                  Delivery ID header
                </label>
                <input
                  id={ids.del}
                  className={`${styles.input} ${errors.deliveryIdHeader ? styles.invalid : ""}`}
                  value={delHeader}
                  onChange={(e) => setDelHeader(e.target.value)}
                  aria-invalid={Boolean(errors.deliveryIdHeader)}
                />
                <span className={styles.hint}>
                  Without one, duplicates are detected by body hash.
                </span>
                {errors.deliveryIdHeader && (
                  <span className={styles.error}>{errors.deliveryIdHeader}</span>
                )}
              </div>
            </>
          )}

          <fieldset className={styles.field} style={{ border: 0, padding: 0, margin: 0 }}>
            <legend className={styles.label}>Events</legend>
            <div className={styles.checks}>
              {GITHUB_EVENT_OPTIONS.map((e) => (
                <label key={e} className={styles.check}>
                  <input
                    type="checkbox"
                    checked={checked.includes(e)}
                    onChange={() => toggleEvent(e)}
                  />
                  {e}
                </label>
              ))}
            </div>
            <label className={styles.label} htmlFor={ids.other}>
              Other events
            </label>
            <input
              id={ids.other}
              className={styles.input}
              value={other}
              placeholder="deployment, deployment_status"
              onChange={(e) => setOther(e.target.value)}
            />
            <span className={styles.hint}>
              Deliveries for any other event are recorded as ignored.
            </span>
            {errors.eventAllowlist && <span className={styles.error}>{errors.eventAllowlist}</span>}
          </fieldset>

          <div className={styles.switchRow}>
            <div className={styles.field}>
              <span className={styles.label} id={ids.bot}>
                Ignore events from the fleet&apos;s bot
              </span>
              <span className={styles.hint}>
                Stops a run from triggering itself through its own PR or comment.
              </span>
            </div>
            <Toggle checked={ignoreBot} onChange={setIgnoreBot} aria-labelledby={ids.bot} />
          </div>

          {mode === "edit" && (
            <div className={styles.switchRow}>
              <div className={styles.field}>
                <span className={styles.label} id={ids.enabled}>
                  Enabled
                </span>
                <span className={styles.hint}>
                  A disabled endpoint answers 404 and records nothing.
                </span>
              </div>
              <Toggle checked={enabled} onChange={setEnabled} aria-labelledby={ids.enabled} />
            </div>
          )}

          <div className={styles.footer} style={{ padding: 0, border: 0 }}>
            <Button variant="ghost" type="button" onClick={onClose}>
              Cancel
            </Button>
            <Button variant="primary" type="submit" disabled={pending}>
              {mode === "edit"
                ? pending
                  ? "Saving…"
                  : "Save"
                : pending
                  ? "Creating…"
                  : "Create endpoint"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
