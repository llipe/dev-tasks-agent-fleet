import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { InvokeDialog } from "@/components/invoke/InvokeDialog";
import { allowConsoleError } from "@/tests/setup";

/**
 * S-113 (#126) — invoke dialog component tests (task 2.14, AC11).
 *
 * The seeded dependency-update schema renders the four expected controls purely
 * from the schema; the repository selector is hidden when
 * requires_repository=false; invalid input blocks submit (client Ajv);
 * inline vs banner error rendering; success navigation.
 */

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const DEP_UPDATE_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["fix_mode"],
  properties: {
    fix_mode: {
      type: "string",
      title: "Fix mode",
      description: "audit_only reports findings.",
      enum: ["audit_only", "llm_fix"],
      default: "audit_only",
    },
    fail_on_findings: { type: "boolean", title: "Fail if findings exist", default: true },
    max_fix_attempts: {
      type: "integer",
      title: "Max LLM agent attempts",
      minimum: 0,
      maximum: 5,
      default: 3,
    },
    base_branch: { type: "string", title: "PR base branch", default: "main" },
  },
};

function renderDialog(overrides: Partial<Parameters<typeof InvokeDialog>[0]> = {}) {
  return render(
    <InvokeDialog
      slug="dependency-update"
      agentName="Dependency Update"
      schema={DEP_UPDATE_SCHEMA}
      defaultParams={{}}
      requiresRepository
      repositories={[{ id: "repo-1", full_name: "acme/web" }]}
      {...overrides}
    />,
  );
}

beforeEach(() => {
  push.mockReset();
  vi.restoreAllMocks();
});
afterEach(cleanup);

describe("InvokeDialog — schema-driven rendering (AC11)", () => {
  it("renders the four expected controls purely from the schema", () => {
    renderDialog();
    // select for fix_mode
    expect(screen.getByLabelText(/Fix mode/i).tagName).toBe("SELECT");
    // toggle for fail_on_findings (role switch)
    expect(screen.getByRole("switch", { name: /Fail if findings/i })).toBeInTheDocument();
    // number for max_fix_attempts
    const num = screen.getByLabelText(/Max LLM agent attempts/i) as HTMLInputElement;
    expect(num.type).toBe("number");
    expect(num.min).toBe("0");
    expect(num.max).toBe("5");
    // text for base_branch
    expect((screen.getByLabelText(/PR base branch/i) as HTMLInputElement).type).toBe("text");
  });

  it("shows the agent slug and name", () => {
    renderDialog();
    expect(screen.getByText("Dependency Update")).toBeInTheDocument();
    expect(screen.getByText("dependency-update")).toBeInTheDocument();
  });

  it("renders the repository selector when requires_repository=true", () => {
    renderDialog();
    expect(screen.getByLabelText(/Repository/i)).toBeInTheDocument();
  });

  it("hides the repository selector when requires_repository=false", () => {
    renderDialog({ requiresRepository: false, repositories: [] });
    expect(screen.queryByLabelText(/Repository/i)).not.toBeInTheDocument();
  });
});

describe("InvokeDialog — submission and navigation (AC6/AC24)", () => {
  it("202 navigates to /runs/[id]", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(JSON.stringify({ run_id: "run-xyz", status: "queued" }), { status: 202 }),
      );
    renderDialog();
    fireEvent.change(screen.getByLabelText(/Repository/i), { target: { value: "repo-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/runs/run-xyz"));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body.repository_id).toBe("repo-1");
    expect(body.params.fix_mode).toBe("audit_only");
  });

  it("502 with run_id also navigates (failed_to_start visible on detail)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ run_id: "run-fail", error: { code: "INVOCATION_FAILED" } }), {
        status: 502,
      }),
    );
    renderDialog();
    fireEvent.change(screen.getByLabelText(/Repository/i), { target: { value: "repo-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/runs/run-fail"));
  });
});

describe("InvokeDialog — error rendering", () => {
  it("disables Run until a repository is selected (blocks submit)", async () => {
    renderDialog();
    // With no repository chosen, Run is disabled and submit cannot fire.
    expect((screen.getByRole("button", { name: "Run" }) as HTMLButtonElement).disabled).toBe(true);
    expect(push).not.toHaveBeenCalled();
    // After selecting a repository, Run enables.
    fireEvent.change(screen.getByLabelText(/Repository/i), { target: { value: "repo-1" } });
    expect((screen.getByRole("button", { name: "Run" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("client Ajv blocks an out-of-range value before any fetch (AC23)", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    renderDialog();
    fireEvent.change(screen.getByLabelText(/Repository/i), { target: { value: "repo-1" } });
    // max_fix_attempts max is 5; set 9 -> client Ajv must reject.
    fireEvent.change(screen.getByLabelText(/Max LLM agent attempts/i), { target: { value: "9" } });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() => expect(screen.getByText(/must be|<=|maximum/i)).toBeInTheDocument());
    expect(fetchMock).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
  });

  it("renders a banner for CREDENTIALS_UNAVAILABLE (server error)", async () => {
    allowConsoleError("testing a server error path");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ error: { code: "CREDENTIALS_UNAVAILABLE", message: "no creds" } }),
        { status: 500 },
      ),
    );
    renderDialog();
    fireEvent.change(screen.getByLabelText(/Repository/i), { target: { value: "repo-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/no creds/i);
    expect(push).not.toHaveBeenCalled();
  });

  it("renders inline per-field errors for INVALID_PARAMS from the server", async () => {
    allowConsoleError("testing an invalid-params path");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          error: {
            code: "INVALID_PARAMS",
            message: "bad",
            details: [{ instancePath: "/base_branch", message: "must be a string" }],
          },
        }),
        { status: 400 },
      ),
    );
    renderDialog();
    fireEvent.change(screen.getByLabelText(/Repository/i), { target: { value: "repo-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() => expect(screen.getByText(/must be a string/i)).toBeInTheDocument());
  });
});

describe("InvokeDialog — schema preview (AC28)", () => {
  it("toggles the raw params_schema", () => {
    renderDialog();
    expect(screen.queryByTestId("schema-preview")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Show schema/i }));
    expect(screen.getByTestId("schema-preview")).toBeInTheDocument();
  });
});
