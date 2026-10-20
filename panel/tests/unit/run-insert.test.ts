import { describe, expect, it } from "vitest";
import { buildRunInsert, RunSnapshotError } from "@/lib/domain/run-insert";

// Layer 1 — S-150 (#262): buildRunInsert trigger descriptor.
//
// The builder is parameterized over a TriggerDescriptor so scheduled runs
// record trigger_type='schedule' / triggered_by='schedule:<id>' while manual
// runs stay byte-identical to the pre-S-150 shape (SD-X1 / FR7). The timeout
// snapshot discipline (RunSnapshotError on a non-finite value) is unchanged.

const agent = {
  id: "11111111-1111-1111-1111-111111111111",
  version: "0.1.0",
  max_runtime_seconds: 3600,
  grace_seconds: 120,
  start_timeout_seconds: 300,
};

const common = {
  runId: "22222222-2222-2222-2222-222222222222",
  agent,
  repositoryId: "33333333-3333-3333-3333-333333333333",
  installationId: "44444444-4444-4444-4444-444444444444",
  params: { fix_mode: "audit_only" },
};

describe("buildRunInsert — trigger descriptor", () => {
  it("manual descriptor produces the prior manual/panel shape (byte-identical)", () => {
    const row = buildRunInsert({
      ...common,
      trigger: { triggerType: "manual", triggeredBy: "panel" },
    });
    expect(row).toEqual({
      id: common.runId,
      agent_id: agent.id,
      agent_version: agent.version,
      repository_id: common.repositoryId,
      installation_id: common.installationId,
      trigger_type: "manual",
      triggered_by: "panel",
      params: common.params,
      status: "queued",
      max_runtime_seconds: 3600,
      grace_seconds: 120,
      start_timeout_seconds: 300,
    });
  });

  it("schedule descriptor produces schedule / schedule:<id>", () => {
    const row = buildRunInsert({
      ...common,
      trigger: { triggerType: "schedule", triggeredBy: "schedule:abc-123" },
    });
    expect(row.trigger_type).toBe("schedule");
    expect(row.triggered_by).toBe("schedule:abc-123");
    // everything else is identical to the manual row
    expect(row.max_runtime_seconds).toBe(3600);
    expect(row.grace_seconds).toBe(120);
    expect(row.start_timeout_seconds).toBe(300);
    expect(row.status).toBe("queued");
  });

  // S-172 (#317, D-W5): webhook-fired runs.
  it("webhook descriptor produces webhook / webhook:<endpoint>:<rule>", () => {
    const row = buildRunInsert({
      ...common,
      trigger: { triggerType: "webhook", triggeredBy: "webhook:ep-1:rule-1" },
    });
    expect(row.trigger_type).toBe("webhook");
    expect(row.triggered_by).toBe("webhook:ep-1:rule-1");
    expect(row.status).toBe("queued");
    expect(row.max_runtime_seconds).toBe(3600);
  });

  it("rejects a mismatched trigger type/identity at the type level", () => {
    const bad = () =>
      buildRunInsert({
        ...common,
        // @ts-expect-error — a webhook identity can't carry the schedule type.
        trigger: { triggerType: "schedule", triggeredBy: "webhook:ep-1:rule-1" },
      });
    expect(bad).not.toThrow();
  });

  it("still copies all three timeout snapshots explicitly (OQ3 unchanged)", () => {
    const row = buildRunInsert({
      ...common,
      agent: { ...agent, grace_seconds: 150, start_timeout_seconds: 450 },
      trigger: { triggerType: "schedule", triggeredBy: "schedule:x" },
    });
    expect(row.grace_seconds).toBe(150);
    expect(row.start_timeout_seconds).toBe(450);
  });

  it("still throws RunSnapshotError on a non-finite timeout (never a silent default)", () => {
    expect(() =>
      buildRunInsert({
        ...common,
        agent: { ...agent, max_runtime_seconds: Number.NaN },
        trigger: { triggerType: "manual", triggeredBy: "panel" },
      }),
    ).toThrow(RunSnapshotError);
  });

  it("accepts a null repository/installation (no-repository agent) under either trigger", () => {
    const row = buildRunInsert({
      runId: common.runId,
      agent,
      repositoryId: null,
      installationId: null,
      params: {},
      trigger: { triggerType: "schedule", triggeredBy: "schedule:y" },
    });
    expect(row.repository_id).toBeNull();
    expect(row.installation_id).toBeNull();
    expect(row.trigger_type).toBe("schedule");
  });
});
