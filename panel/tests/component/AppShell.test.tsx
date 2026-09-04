import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "@/components/shell/AppShell";
import { SIDEBAR_STORAGE_KEY } from "@/lib/ui/sidebar-state";

import { renderHydrated } from "../helpers/hydrate";

// next/navigation is a client-hook boundary; the shell reads usePathname.
let pathname = "/";
vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
}));

// This jsdom setup runs without a backing localStorage ("--localstorage-file
// not provided"), so `window.localStorage` is undefined. Install an in-memory
// Storage for these tests; individual tests may override its methods to
// simulate private-mode failures.
function installMemoryStorage(): void {
  const map = new Map<string, string>();
  const storage: Storage = {
    get length() {
      return map.size;
    },
    clear: () => map.clear(),
    key: (i: number) => Array.from(map.keys())[i] ?? null,
    getItem: (k: string) => (map.has(k) ? (map.get(k) as string) : null),
    setItem: (k: string, v: string) => void map.set(k, String(v)),
    removeItem: (k: string) => void map.delete(k),
  };
  Object.defineProperty(window, "localStorage", {
    value: storage,
    configurable: true,
    writable: true,
  });
}

beforeEach(() => {
  pathname = "/";
  installMemoryStorage();
});

afterEach(() => {
  installMemoryStorage();
});

function child() {
  return <p>page content</p>;
}

describe("AppShell — structure and a11y (AC1, AC3, AC5)", () => {
  it("renders a labeled primary nav, a top bar, and the content", () => {
    render(<AppShell>{child()}</AppShell>);
    expect(screen.getByRole("navigation", { name: /primary/i })).toBeInTheDocument();
    expect(screen.getByText("page content")).toBeInTheDocument();
  });

  it("marks Agents as the only enabled destination; the four deferred are disabled", () => {
    render(<AppShell>{child()}</AppShell>);
    // Agents is a real link.
    expect(screen.getByRole("link", { name: /agents/i })).toHaveAttribute("href", "/");
    // The four deferred destinations are NOT links.
    for (const label of ["All runs", "Repositories", "Settings", "System health"]) {
      expect(screen.queryByRole("link", { name: new RegExp(label, "i") })).toBeNull();
      const disabled = screen.getByLabelText(new RegExp(`${label} — not available`, "i"));
      expect(disabled).toHaveAttribute("aria-disabled", "true");
    }
  });

  it("derives the active nav item from the current route", () => {
    pathname = "/agents/dependency-update";
    render(<AppShell>{child()}</AppShell>);
    expect(screen.getByRole("link", { name: /agents/i })).toHaveAttribute("aria-current", "page");
  });
});

describe("AppShell — collapse behavior (AC2)", () => {
  it("toggles collapsed state on the collapse button", async () => {
    render(<AppShell>{child()}</AppShell>);
    const nav = screen.getByRole("navigation", { name: /primary/i });
    expect(nav).toHaveAttribute("data-collapsed", "false");

    fireEvent.click(screen.getByRole("button", { name: /collapse sidebar/i }));
    expect(nav).toHaveAttribute("data-collapsed", "true");

    fireEvent.click(screen.getByRole("button", { name: /expand sidebar/i }));
    expect(nav).toHaveAttribute("data-collapsed", "false");
  });

  it("persists the collapsed state to localStorage", async () => {
    render(<AppShell>{child()}</AppShell>);
    fireEvent.click(screen.getByRole("button", { name: /collapse sidebar/i }));
    expect(window.localStorage.getItem(SIDEBAR_STORAGE_KEY)).toBe("collapsed");
  });

  it("restores collapsed state from a seeded localStorage after mount", async () => {
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, "collapsed");
    render(<AppShell>{child()}</AppShell>);
    // The mount effect reconciles to collapsed.
    expect(await screen.findByRole("button", { name: /expand sidebar/i })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: /primary/i })).toHaveAttribute(
      "data-collapsed",
      "true",
    );
  });

  it("toggles with Cmd/Ctrl+\\ but not while typing in an input", async () => {
    render(
      <AppShell>
        <input aria-label="probe" />
      </AppShell>,
    );
    const nav = screen.getByRole("navigation", { name: /primary/i });

    // Ctrl+\ from the document toggles (jsdom navigator is non-mac → Ctrl branch).
    fireEvent.keyDown(window, { key: "\\", ctrlKey: true });
    expect(nav).toHaveAttribute("data-collapsed", "true");

    // A keydown whose target is an input must be ignored (typing guard).
    const input = screen.getByLabelText("probe");
    fireEvent.keyDown(input, { key: "\\", ctrlKey: true });
    expect(nav).toHaveAttribute("data-collapsed", "true");
  });

  it("survives a rapid double toggle with a consistent final state", async () => {
    render(<AppShell>{child()}</AppShell>);
    const nav = screen.getByRole("navigation", { name: /primary/i });
    const btn = () => screen.getByRole("button", { name: /(collapse|expand) sidebar/i });
    fireEvent.click(btn());
    fireEvent.click(btn());
    expect(nav).toHaveAttribute("data-collapsed", "false");
    expect(window.localStorage.getItem(SIDEBAR_STORAGE_KEY)).toBe("expanded");
  });
});

describe("AppShell — storage failure modes (AC2 edge cases)", () => {
  it("defaults to expanded and does not crash when localStorage.getItem throws", () => {
    window.localStorage.getItem = () => {
      throw new DOMException("denied", "SecurityError");
    };
    render(<AppShell>{child()}</AppShell>);
    expect(screen.getByRole("navigation", { name: /primary/i })).toHaveAttribute(
      "data-collapsed",
      "false",
    );
  });

  it("defaults to expanded on a corrupt stored value", async () => {
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, "kanban");
    render(<AppShell>{child()}</AppShell>);
    expect(await screen.findByRole("button", { name: /collapse sidebar/i })).toBeInTheDocument();
  });
});

describe("AppShell — hydration contract (test-plan G3 / EC-7)", () => {
  it("hydrates cleanly when storage says collapsed, then reconciles to collapsed", async () => {
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, "collapsed");
    const { container, recoverable, cleanup } = await renderHydrated(
      <AppShell>{child()}</AppShell>,
    );

    // No hydration mismatch: server rendered the expanded default, client
    // hydrated the same default, THEN the mount effect reconciled to collapsed.
    expect(recoverable).toEqual([]);

    const nav = within(container).getByRole("navigation", { name: /primary/i });
    expect(nav).toHaveAttribute("data-collapsed", "true");
    cleanup();
  });

  it("hydrates cleanly with default (empty) storage", async () => {
    const { container, recoverable, cleanup } = await renderHydrated(
      <AppShell>{child()}</AppShell>,
    );
    expect(recoverable).toEqual([]);
    expect(within(container).getByRole("navigation", { name: /primary/i })).toHaveAttribute(
      "data-collapsed",
      "false",
    );
    cleanup();
  });
});
