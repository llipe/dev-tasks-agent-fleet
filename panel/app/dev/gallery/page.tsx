/**
 * Dev-only component gallery (S-105 / issue #118, task 2.12).
 *
 * Renders every primitive variant side by side for visual comparison against
 * the prototype at `docs/prototype/`. It is NOT part of the product surface:
 * in a production build it returns 404 via `notFound()`, so it never ships to
 * users even though it lives in the App Router tree. (A route cannot be
 * physically excluded from the build without a separate app, so the standard
 * App Router pattern is a runtime guard.)
 */
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { Breadcrumb } from "@/components/Breadcrumb";
import { Button } from "@/components/Button";
import { Input } from "@/components/Input";
import { KLabel } from "@/components/KLabel";
import { LogLine } from "@/components/LogLine";
import { RunStrip } from "@/components/RunStrip";
import { StatusBar } from "@/components/StatusBar";
import { StatusDot } from "@/components/StatusDot";
import { StatusPill } from "@/components/StatusPill";
import { Tag } from "@/components/Tag";
import type { RunStatus } from "@/lib/domain/status";
import {
  formatClock,
  formatDuration,
  formatRelative,
  formatRunId,
  formatStatusLegend,
  formatStatusLegendCompact,
} from "@/lib/format";
import { ToggleDemo } from "./ToggleDemo";

export const dynamic = "force-dynamic";

const ALL_STATUSES: RunStatus[] = [
  "running",
  "queued",
  "succeeded",
  "failed",
  "timed_out",
  "failed_to_start",
  "canceled",
];

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section style={{ marginBottom: "var(--space-8)" }}>
      <KLabel>{title}</KLabel>
      <div style={{ marginTop: "var(--space-3)", display: "flex", flexWrap: "wrap", gap: "12px" }}>
        {children}
      </div>
    </section>
  );
}

export default function GalleryPage() {
  if (process.env.NODE_ENV === "production") {
    notFound();
  }

  const now = Date.now();

  return (
    <main style={{ padding: "var(--space-8)", maxWidth: "960px" }}>
      <h1 style={{ fontFamily: "var(--font-heading)", fontWeight: 500 }}>Nocturne gallery</h1>
      <p style={{ color: "var(--muted)" }}>
        Dev-only. Every S-105 primitive variant for visual comparison against{" "}
        <code>docs/prototype/</code>.
      </p>

      <Section title="Buttons">
        <Button variant="primary">Primary</Button>
        <Button variant="secondary">Secondary</Button>
        <Button variant="ghost">Ghost</Button>
        <Button variant="primary" size="sm">
          Small
        </Button>
        <Button variant="primary" size="md">
          Medium
        </Button>
        <Button variant="primary" disabled>
          Disabled
        </Button>
      </Section>

      <Section title="Tags">
        <Tag variant="accent">ACCENT</Tag>
        <Tag variant="neutral">NEUTRAL</Tag>
        <Tag variant="outline">FIXED</Tag>
        <Tag variant="outline" size="sm">
          NO VULNS
        </Tag>
      </Section>

      <Section title="Status pills">
        {ALL_STATUSES.map((s) => (
          <StatusPill key={s} status={s} />
        ))}
        <StatusPill status={"unknown_future" as RunStatus} />
      </Section>

      <Section title="Status dots">
        {ALL_STATUSES.map((s) => (
          <StatusDot key={s} status={s} />
        ))}
      </Section>

      <Section title="Inputs">
        <Input aria-label="default" placeholder="Filter agents" />
        <Input aria-label="small" inputSize="sm" placeholder="Small" />
      </Section>

      <Section title="Toggle">
        <ToggleDemo />
      </Section>

      <Section title="Breadcrumb">
        <Breadcrumb
          items={[
            { label: "Agents", href: "/agents" },
            { label: "dependency-update", href: "/agents/dependency-update" },
            { label: formatRunId("01j8xq2f9k3m") },
          ]}
        />
      </Section>

      <Section title="Status bar + run strip">
        <div style={{ width: "240px" }}>
          <StatusBar
            segments={[
              { colorVar: "var(--st-ok)", percent: 65 },
              { colorVar: "var(--st-fail)", percent: 20 },
              { colorVar: "var(--st-timeout)", percent: 15 },
            ]}
          />
          <div style={{ marginTop: "var(--space-2)", fontFamily: "var(--mono)", fontSize: "11px" }}>
            {formatStatusLegend({ ok: 65, fail: 11, timeout: 6 })} —{" "}
            {formatStatusLegendCompact({ ok: 65, fail: 11, timeout: 6 })}
          </div>
        </div>
        <div style={{ width: "240px" }}>
          <RunStrip
            runs={[
              { status: "succeeded" },
              { status: "succeeded" },
              { status: "failed" },
              { status: "timed_out" },
              { status: "running" },
            ]}
          />
        </div>
      </Section>

      <Section title="Log lines">
        <div
          style={{
            width: "100%",
            background: "var(--color-surface)",
            borderRadius: "var(--radius-md)",
          }}
        >
          <LogLine
            timestamp={formatClock(now, "UTC")}
            level="info"
            step="checkout"
            message="cloning repository"
          />
          <LogLine
            timestamp={formatClock(now, "UTC")}
            level="warn"
            step="npm_audit"
            message="3 advisories found"
          />
          <LogLine
            timestamp={formatClock(now, "UTC")}
            level="error"
            step="validate"
            message={`tests failed after ${formatDuration(184000)} (${formatRelative(now - 60000, now)})`}
          />
        </div>
      </Section>
    </main>
  );
}
