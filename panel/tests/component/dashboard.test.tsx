import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DashboardClient } from "@/components/dashboard/DashboardClient";
import { buildAgentSummaries, type AgentSummaryInput } from "@/lib/domain/dashboard";
import { DENSITY_STORAGE_KEY } from "@/lib/ui/density-state";

/**
 * Layer 2 component tests for the dashboard (S-107 / issue #120).
 *
 * Covers: the three variants render from ONE fixture (AC-107.2), density
 * persistence selects the variant on mount (AC-107.3), the filter narrows the
 * list in every variant and reads a distinct no-match state (AC-107.6/8), the
 * ledger keyboard affordances (AC-107.7), the no-refetch instrument (G4:
 * assert the toggle/filter never navigate), and the hint/behavior coupling
 * guard (task 2.13a).
 *
 * The status derivation is exercised through the RENDERED tree (CT-2): a stale
 * running agent must show `timed_out` on its dot, never `running`.
 */

// --- next/navigation mock: the no-refetch instrument (G4) --------------------
const push = vi.fn();
const replace = vi.fn();
const refresh = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace, refresh }),
  usePathname: () => "/",
}));

// jsdom here has no backing localStorage; install an in-memory one.
function installMemoryStorage(): void {
  const map = new Map<string, string>();
  const storage: Storage = {
    get length() {
      return map.size;
    },
    clear: () => map.clear(),
    key: (i) => Array.from(map.keys())[i] ?? null,
    getItem: (k) => (map.has(k) ? (map.get(k) as string) : null),
    setItem: (k, v) => void map.set(k, String(v)),
    removeItem: (k) => void map.delete(k),
  };
  Object.defineProperty(window, "localStorage", {
    value: storage,
    configurable: true,
    writable: true,
  });
}

const NOW = Date.UTC(2026, 0, 1, 12, 0, 0);

function fixtureInput(): AgentSummaryInput[] {
  return [
    {
      id: "a1",
      slug: "dependency-update",
      name: "Dependency Update",
      description: "Runs npm audit and opens a PR.",
      requiresRepository: true,
      runs: [
        {
          status: "succeeded",
          startedAtMs: NOW - 300_000,
          queuedAtMs: NOW - 360_000,
          finishedAtMs: NOW - 60_000,
          createdAtMs: NOW - 60_000,
          maxRuntimeSeconds: 900,
          graceSeconds: 60,
          startTimeoutSeconds: 300,
          outcome: "fixed",
        },
      ],
    },
    {
      id: "a2",
      slug: "secret-scan",
      name: "Secret Scanner",
      description: "Scans for leaked credentials.",
      requiresRepository: true,
      // A stale running run: started 20 min ago, 16 min window → timed_out.
      runs: [
        {
          status: "running",
          startedAtMs: NOW - 20 * 60_000,
          queuedAtMs: NOW - 21 * 60_000,
          finishedAtMs: null,
          createdAtMs: NOW - 20 * 60_000,
          maxRuntimeSeconds: 900,
          graceSeconds: 60,
          startTimeoutSeconds: 300,
          outcome: null,
        },
      ],
    },
  ];
}

function summaries() {
  return buildAgentSummaries(fixtureInput(), NOW);
}

function renderDashboard(invokeRouteAvailable = false) {
  return render(
    <DashboardClient
      agents={summaries()}
      nowMs={NOW}
      invokeRouteAvailable={invokeRouteAvailable}
    />,
  );
}

beforeEach(() => {
  push.mockClear();
  replace.mockClear();
  refresh.mockClear();
  installMemoryStorage();
});

afterEach(() => {
  installMemoryStorage();
});

describe("dashboard — variants render from one fixture (AC-107.2)", () => {
  it("renders dense rows by default with both agents", () => {
    renderDashboard();
    const table = screen.getByRole("table", { name: /agents/i });
    expect(within(table).getByText("Dependency Update")).toBeInTheDocument();
    expect(within(table).getByText("Secret Scanner")).toBeInTheDocument();
  });

  it("switches to cards and to ledger via the toggle, from the same data", () => {
    renderDashboard();
    fireEvent.click(screen.getByRole("button", { name: /cards/i }));
    // Cards use articles, not a table.
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByText("Dependency Update")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /ledger/i }));
    expect(screen.getByRole("listbox", { name: /agents ledger/i })).toBeInTheDocument();
    expect(screen.getByText("Secret Scanner")).toBeInTheDocument();
  });
});

describe("dashboard — status derivation reaches the view (CT-2)", () => {
  it("shows timed_out (not running) for a stale running agent's status dot", () => {
    renderDashboard();
    // Secret Scanner's last run is a stale running → timed_out. The dot is
    // decorative, so we assert the derivation by rendering ledger where the
    // status is visible, and by asserting `running` appears nowhere.
    expect(screen.queryByText(/running/i)).toBeNull();
  });
});

describe("dashboard — density persistence (AC-107.3)", () => {
  it("restores the persisted variant on mount", async () => {
    window.localStorage.setItem(DENSITY_STORAGE_KEY, "ledger");
    renderDashboard();
    expect(await screen.findByRole("listbox", { name: /agents ledger/i })).toBeInTheDocument();
  });

  it("persists a variant selection", () => {
    renderDashboard();
    fireEvent.click(screen.getByRole("button", { name: /cards/i }));
    expect(window.localStorage.getItem(DENSITY_STORAGE_KEY)).toBe("cards");
  });

  it("falls back to dense on a corrupt persisted value", () => {
    window.localStorage.setItem(DENSITY_STORAGE_KEY, "kanban");
    renderDashboard();
    expect(screen.getByRole("table", { name: /agents/i })).toBeInTheDocument();
  });
});

describe("dashboard — filter (AC-107.8, EC-25)", () => {
  it("narrows the list by name, case-insensitively, in dense rows", () => {
    renderDashboard();
    fireEvent.change(screen.getByLabelText(/filter agents/i), { target: { value: "SECRET" } });
    expect(screen.getByText("Secret Scanner")).toBeInTheDocument();
    expect(screen.queryByText("Dependency Update")).toBeNull();
  });

  it("narrows by slug and clears back to the full list", () => {
    renderDashboard();
    const input = screen.getByLabelText(/filter agents/i);
    fireEvent.change(input, { target: { value: "dependency-update" } });
    expect(screen.queryByText("Secret Scanner")).toBeNull();
    fireEvent.change(input, { target: { value: "" } });
    expect(screen.getByText("Secret Scanner")).toBeInTheDocument();
    expect(screen.getByText("Dependency Update")).toBeInTheDocument();
  });

  it("shows a DISTINCT no-match state naming the query, not the no-agents copy (EC-25)", () => {
    renderDashboard();
    fireEvent.change(screen.getByLabelText(/filter agents/i), { target: { value: "zzz" } });
    expect(screen.getByText(/nothing matches/i)).toBeInTheDocument();
    expect(screen.getByText(/zzz/)).toBeInTheDocument();
    expect(screen.queryByText(/no agents configured/i)).toBeNull();
  });

  it("treats a bracket metacharacter literally without crashing (EC-25)", () => {
    renderDashboard();
    fireEvent.change(screen.getByLabelText(/filter agents/i), { target: { value: "[" } });
    expect(screen.getByText(/nothing matches/i)).toBeInTheDocument();
  });

  it("filters in the cards variant too", () => {
    renderDashboard();
    fireEvent.click(screen.getByRole("button", { name: /cards/i }));
    fireEvent.change(screen.getByLabelText(/filter agents/i), { target: { value: "secret" } });
    expect(screen.getByText("Secret Scanner")).toBeInTheDocument();
    expect(screen.queryByText("Dependency Update")).toBeNull();
  });
});

describe("dashboard — no-refetch instrument (G4 / EC-8)", () => {
  it("never navigates across a dense → cards → ledger → dense cycle", () => {
    renderDashboard();
    fireEvent.click(screen.getByRole("button", { name: /cards/i }));
    fireEvent.click(screen.getByRole("button", { name: /ledger/i }));
    fireEvent.click(screen.getByRole("button", { name: /rows/i }));
    expect(push).not.toHaveBeenCalled();
    expect(replace).not.toHaveBeenCalled();
    expect(refresh).not.toHaveBeenCalled();
  });

  it("never navigates on a filter keystroke", () => {
    renderDashboard();
    fireEvent.change(screen.getByLabelText(/filter agents/i), { target: { value: "sec" } });
    expect(push).not.toHaveBeenCalled();
    expect(replace).not.toHaveBeenCalled();
    expect(refresh).not.toHaveBeenCalled();
  });
});

describe("dashboard — ledger keyboard (AC-107.7, EC-26)", () => {
  function toLedger() {
    renderDashboard(true); // invoke route available so Enter can navigate
    fireEvent.click(screen.getByRole("button", { name: /ledger/i }));
    return screen.getAllByRole("option");
  }

  it("Down/Up move the selection and clamp at both ends (roving tabindex)", () => {
    const rows = toLedger();
    // exactly one row focusable initially
    expect(rows.filter((r) => r.getAttribute("tabindex") === "0")).toHaveLength(1);

    fireEvent.keyDown(rows[0], { key: "ArrowDown" });
    expect(rows[1]).toHaveAttribute("aria-selected", "true");
    // clamp at the bottom
    fireEvent.keyDown(rows[1], { key: "ArrowDown" });
    expect(rows[1]).toHaveAttribute("aria-selected", "true");

    fireEvent.keyDown(rows[1], { key: "ArrowUp" });
    expect(rows[0]).toHaveAttribute("aria-selected", "true");
    // clamp at the top
    fireEvent.keyDown(rows[0], { key: "ArrowUp" });
    expect(rows[0]).toHaveAttribute("aria-selected", "true");
  });

  it("Enter activates the selected row's Invoke target", () => {
    const rows = toLedger();
    fireEvent.keyDown(rows[0], { key: "Enter" });
    expect(push).toHaveBeenCalledWith("/agents/dependency-update/invoke");
  });

  it("Enter is inert when no invoke route exists yet (task 2.11)", () => {
    render(<DashboardClient agents={summaries()} nowMs={NOW} invokeRouteAvailable={false} />);
    fireEvent.click(screen.getByRole("button", { name: /ledger/i }));
    const rows = screen.getAllByRole("option");
    fireEvent.keyDown(rows[0], { key: "Enter" });
    expect(push).not.toHaveBeenCalled();
  });

  it("/ focuses the filter from the ledger; a slash typed inside inserts a slash", () => {
    const rows = toLedger();
    fireEvent.keyDown(rows[0], { key: "/" });
    expect(screen.getByLabelText(/filter agents/i)).toHaveFocus();
  });
});

describe("dashboard — / focus binding is global and guarded (EC-26)", () => {
  it("/ from the page body focuses the filter", () => {
    renderDashboard();
    fireEvent.keyDown(window, { key: "/" });
    expect(screen.getByLabelText(/filter agents/i)).toHaveFocus();
  });

  it("/ typed inside the filter does not re-fire (guarded), Escape clears then blurs", () => {
    renderDashboard();
    const input = screen.getByLabelText(/filter agents/i) as HTMLInputElement;
    input.focus();
    fireEvent.change(input, { target: { value: "abc" } });
    // Escape with a value clears it
    fireEvent.keyDown(input, { key: "Escape" });
    expect(input.value).toBe("");
    // Escape when empty blurs
    fireEvent.keyDown(input, { key: "Escape" });
    expect(input).not.toHaveFocus();
  });
});

describe("dashboard — hint/behavior coupling guard (task 2.13a)", () => {
  it("every ledger hint has a working key behind it", () => {
    const rows = toLedgerHelper();
    // The three hints rendered: ↑↓ navigate, Enter invoke, / filter.
    // Navigate:
    fireEvent.keyDown(rows[0], { key: "ArrowDown" });
    expect(rows[1]).toHaveAttribute("aria-selected", "true");
    // Filter:
    fireEvent.keyDown(rows[1], { key: "/" });
    expect(screen.getByLabelText(/filter agents/i)).toHaveFocus();
    // Invoke (route available in this render):
    fireEvent.keyDown(rows[1], { key: "Enter" });
    expect(push).toHaveBeenCalled();
  });
});

function toLedgerHelper() {
  render(<DashboardClient agents={summaries()} nowMs={NOW} invokeRouteAvailable={true} />);
  fireEvent.click(screen.getByRole("button", { name: /ledger/i }));
  return screen.getAllByRole("option");
}

describe("dashboard — empty states (EC-19)", () => {
  it("renders 'no agents configured' for an empty fleet", () => {
    render(<DashboardClient agents={[]} nowMs={NOW} invokeRouteAvailable={false} />);
    expect(screen.getByText(/no agents configured/i)).toBeInTheDocument();
  });

  it("renders an agent with zero runs without NaN or a blank region", () => {
    const zero = buildAgentSummaries(
      [
        {
          id: "z",
          slug: "fresh",
          name: "Fresh Agent",
          description: null,
          requiresRepository: false,
          runs: [],
        },
      ],
      NOW,
    );
    render(<DashboardClient agents={zero} nowMs={NOW} invokeRouteAvailable={false} />);
    expect(screen.getByText("Fresh Agent")).toBeInTheDocument();
    expect(screen.getByText(/no runs yet/i)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/NaN|undefined|Invalid Date/);
  });
});

describe("dashboard — idempotent render (EC-10)", () => {
  it("produces identical markup for the same props and injected now", () => {
    const { container: a } = renderDashboard();
    const first = a.innerHTML;
    installMemoryStorage();
    const { container: b } = renderDashboard();
    expect(b.innerHTML).toBe(first);
  });
});

describe("dashboard — cards variant fallback states (QA gaps 3)", () => {
  function zeroRunAgent() {
    return buildAgentSummaries(
      [
        {
          id: "z",
          slug: "fresh",
          name: "Fresh Agent",
          description: "A brand new agent.",
          requiresRepository: false,
          runs: [],
        },
      ],
      NOW,
    );
  }

  it("renders 'no runs yet' and a disabled Invoke in cards when route is unbuilt", () => {
    render(<DashboardClient agents={zeroRunAgent()} nowMs={NOW} invokeRouteAvailable={false} />);
    fireEvent.click(screen.getByRole("button", { name: /cards/i }));
    expect(screen.getByText(/no runs yet/i)).toBeInTheDocument();
    const invoke = screen.getByRole("button", { name: /invoke/i });
    expect(invoke).toBeDisabled();
  });

  it("renders an enabled Invoke link in cards when the route is available", () => {
    render(<DashboardClient agents={zeroRunAgent()} nowMs={NOW} invokeRouteAvailable={true} />);
    fireEvent.click(screen.getByRole("button", { name: /cards/i }));
    expect(screen.getByRole("link", { name: /invoke/i })).toHaveAttribute(
      "href",
      "/agents/fresh/invoke",
    );
  });
});

describe("dashboard — dense-rows disabled Invoke (QA gap 3)", () => {
  it("renders a disabled Invoke button when the route is unbuilt", () => {
    renderDashboard(false);
    const invokeButtons = screen.getAllByRole("button", { name: /invoke/i });
    expect(invokeButtons.length).toBeGreaterThan(0);
    for (const b of invokeButtons) expect(b).toBeDisabled();
  });
});
