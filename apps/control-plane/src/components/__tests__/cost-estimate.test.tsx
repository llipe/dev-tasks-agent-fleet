import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { CostEstimate } from "../cost-estimate";

describe("CostEstimate", () => {
  describe("complete cost (exact)", () => {
    it("renders exact dollar amount when complete=true", () => {
      render(<CostEstimate usd={1.23} complete={true} />);
      expect(screen.getByText("$1.23")).toBeInTheDocument();
    });

    it("renders $0.00 for genuinely free run (usd=0, complete=true)", () => {
      render(<CostEstimate usd={0} complete={true} />);
      expect(screen.getByText("$0.00")).toBeInTheDocument();
    });

    it("formats to two decimal places", () => {
      render(<CostEstimate usd={5} complete={true} />);
      expect(screen.getByText("$5.00")).toBeInTheDocument();
    });

    it("rounds to two decimal places", () => {
      render(<CostEstimate usd={1.999} complete={true} />);
      expect(screen.getByText("$2.00")).toBeInTheDocument();
    });
  });

  describe("partial cost (incomplete)", () => {
    it("renders with ≥ prefix when complete=false", () => {
      render(<CostEstimate usd={1.23} complete={false} />);
      expect(screen.getByText(/≥\s*\$1\.23/)).toBeInTheDocument();
    });

    it("shows a visual marker for partial cost", () => {
      const { container } = render(<CostEstimate usd={1.23} complete={false} />);
      // Partial marker should be visually distinct (e.g., has an aria-label or title)
      const element = container.firstElementChild as HTMLElement;
      expect(element.getAttribute("title") || element.textContent).toContain("≥");
    });

    it("renders $0.00 as partial when usd=0, complete=false", () => {
      // In-progress run with no cost yet should show partial
      render(<CostEstimate usd={0} complete={false} />);
      expect(screen.getByText(/≥\s*\$0\.00/)).toBeInTheDocument();
    });
  });

  describe("unknown cost", () => {
    it("renders 'unknown' when usd is undefined", () => {
      render(<CostEstimate usd={undefined} complete={false} />);
      expect(screen.getByText("unknown")).toBeInTheDocument();
    });

    it("renders 'unknown' when usd is null", () => {
      render(<CostEstimate usd={null} complete={false} />);
      expect(screen.getByText("unknown")).toBeInTheDocument();
    });

    it("never shows $0.00 for unpriced (null/undefined)", () => {
      const { container } = render(<CostEstimate usd={undefined} complete={true} />);
      expect(container.textContent).not.toContain("$0.00");
      expect(container.textContent).toContain("unknown");
    });
  });

  describe("no hardcoded values", () => {
    it("does not have inline style with hardcoded color", () => {
      const { container } = render(<CostEstimate usd={1.23} complete={true} />);
      const element = container.firstElementChild as HTMLElement;
      expect(element.getAttribute("style")).toBeNull();
    });
  });
});
