import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { InvokeDialog } from "@/components/invoke/InvokeDialog";

/**
 * S-113 (#126) — AC7 proof (task 2.15): a SECOND synthetic agent with a
 * DIFFERENT params_schema renders a correct form with ZERO code change. This is
 * the criterion that proves FR16 — a new agent is a database row, not a deploy.
 *
 * Also covers the AC4 unsupported-type path and the empty-schema edge.
 */

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

afterEach(cleanup);

// A completely different agent: no repository, a string, a bounded number, a
// boolean, an enum, an UNSUPPORTED array, and a nested object (unsupported).
const SYNTHETIC_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["target_url"],
  properties: {
    target_url: { type: "string", title: "Target URL", description: "The URL to scan." },
    depth: { type: "integer", title: "Crawl depth", minimum: 1, maximum: 10, default: 3 },
    follow_redirects: { type: "boolean", title: "Follow redirects", default: true },
    mode: { type: "string", title: "Scan mode", enum: ["fast", "deep"], default: "fast" },
    headers: { type: "array", title: "Extra headers", items: { type: "string" } },
    auth: { type: "object", title: "Auth config", properties: { token: { type: "string" } } },
  },
};

describe("AC7 — a synthetic agent renders correctly with zero code change", () => {
  it("renders every supported control kind from a different schema", () => {
    render(
      <InvokeDialog
        slug="url-scanner"
        agentName="URL Scanner"
        schema={SYNTHETIC_SCHEMA}
        defaultParams={{}}
        requiresRepository={false}
        repositories={[]}
      />,
    );

    // string -> text
    expect((screen.getByLabelText(/Target URL/i) as HTMLInputElement).type).toBe("text");
    // bounded integer -> number with bounds
    const depth = screen.getByLabelText(/Crawl depth/i) as HTMLInputElement;
    expect(depth.type).toBe("number");
    expect(depth.min).toBe("1");
    expect(depth.max).toBe("10");
    // boolean -> toggle
    expect(screen.getByRole("switch", { name: /Follow redirects/i })).toBeInTheDocument();
    // enum -> select
    expect(screen.getByLabelText(/Scan mode/i).tagName).toBe("SELECT");
    // no repository selector (requires_repository=false)
    expect(screen.queryByLabelText(/^Repository/i)).not.toBeInTheDocument();
  });

  it("unsupported types (array, nested object) render disabled with a note, never vanish (AC4)", () => {
    render(
      <InvokeDialog
        slug="url-scanner"
        agentName="URL Scanner"
        schema={SYNTHETIC_SCHEMA}
        defaultParams={{}}
        requiresRepository={false}
        repositories={[]}
      />,
    );
    // Both unsupported fields still show their labels.
    expect(screen.getByText(/Extra headers/i)).toBeInTheDocument();
    expect(screen.getByText(/Auth config/i)).toBeInTheDocument();
    // Their controls are disabled and there are explanatory notes.
    const notes = screen.getAllByRole("note");
    expect(notes.length).toBeGreaterThanOrEqual(2);
    const disabledInputs = screen
      .getAllByRole("textbox")
      .filter((el) => (el as HTMLInputElement).disabled);
    expect(disabledInputs.length).toBeGreaterThanOrEqual(2);
  });
});

describe("edge — empty {} schema", () => {
  it("renders no fields and a 'no parameters' message; Run is enabled", () => {
    render(
      <InvokeDialog
        slug="noop-agent"
        agentName="No-op Agent"
        schema={{}}
        defaultParams={{}}
        requiresRepository={false}
        repositories={[]}
      />,
    );
    expect(screen.getByText(/takes no parameters/i)).toBeInTheDocument();
    expect((screen.getByRole("button", { name: "Run" }) as HTMLButtonElement).disabled).toBe(false);
  });
});

describe("edge — zero enabled repositories blocks submit", () => {
  it("shows the empty-repository note and disables Run", () => {
    render(
      <InvokeDialog
        slug="dependency-update"
        agentName="Dependency Update"
        schema={{ type: "object", properties: { fix_mode: { type: "string", enum: ["a"] } } }}
        defaultParams={{}}
        requiresRepository
        repositories={[]}
      />,
    );
    expect(screen.getByRole("note").textContent).toMatch(/no enabled repositories/i);
    expect((screen.getByRole("button", { name: "Run" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
