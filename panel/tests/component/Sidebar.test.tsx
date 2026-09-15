import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Sidebar } from "@/components/shell/Sidebar";

/**
 * Component tests for the sidebar's "All runs" destination (Story S-146,
 * issue #206, FR14).
 *
 * `AppShell.test.tsx` already covers the sidebar's general structure/collapse
 * behavior; this file focuses on the one regression the test-plan §5.6 calls
 * out explicitly: exactly the "All runs" item flips from a non-link
 * `DisabledNavItem` to a real `NavItem` linking to `/runs` — "Repositories",
 * "Settings", and "System health" stay disabled (their own stories are not
 * in scope here), so a future change doesn't silently enable all four at
 * once.
 */

let pathname = "/";
vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
}));

function renderSidebar() {
  return render(<Sidebar collapsed={false} onToggle={() => {}} authenticated={false} />);
}

describe("Sidebar — All runs is a live link (S-146, FR14)", () => {
  it("renders 'All runs' as a real link to /runs, not a DisabledNavItem", () => {
    pathname = "/";
    renderSidebar();
    const link = screen.getByRole("link", { name: /all runs/i });
    expect(link).toHaveAttribute("href", "/runs");
    expect(link).not.toHaveAttribute("aria-disabled");
  });

  it("marks 'All runs' active when the current route is /runs", () => {
    pathname = "/runs";
    renderSidebar();
    expect(screen.getByRole("link", { name: /all runs/i })).toHaveAttribute("aria-current", "page");
  });

  it("marks 'All runs' active on a run-detail route too (/runs/[id])", () => {
    pathname = "/runs/01J8XQ2F3K4M5N6P7Q8R9S0T1U";
    renderSidebar();
    expect(screen.getByRole("link", { name: /all runs/i })).toHaveAttribute("aria-current", "page");
  });

  it("keeps Repositories, Settings, and System health disabled (only 'All runs' flips)", () => {
    pathname = "/";
    renderSidebar();
    for (const label of ["Repositories", "Settings", "System health"]) {
      expect(screen.queryByRole("link", { name: new RegExp(label, "i") })).toBeNull();
      expect(screen.getByLabelText(new RegExp(`${label} — not available`, "i"))).toHaveAttribute(
        "aria-disabled",
        "true",
      );
    }
  });
});
