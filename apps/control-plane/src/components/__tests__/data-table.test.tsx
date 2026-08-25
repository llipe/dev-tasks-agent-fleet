import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DataTable } from "../data-table";
import { legacyCreateColumnHelper } from "@tanstack/react-table/legacy";

interface TestRow {
  id: string;
  name: string;
  count: number;
}

const columnHelper = legacyCreateColumnHelper<TestRow>();

const columns = [
  columnHelper.accessor("name", {
    header: "Name",
    cell: (info) => info.getValue(),
  }),
  columnHelper.accessor("count", {
    header: "Count",
    cell: (info) => info.getValue(),
    meta: { numeric: true },
  }),
];

const testData: TestRow[] = [
  { id: "1", name: "Alpha", count: 10 },
  { id: "2", name: "Beta", count: 5 },
  { id: "3", name: "Gamma", count: 20 },
];

describe("DataTable", () => {
  describe("rendering states", () => {
    it("renders loading state with skeleton rows", () => {
      render(<DataTable columns={columns} data={[]} state="loading" />);
      expect(screen.getByRole("table")).toBeInTheDocument();
      // Skeleton rows should be visible
      expect(screen.getByLabelText("Loading data")).toBeInTheDocument();
    });

    it("renders empty state with message", () => {
      render(<DataTable columns={columns} data={[]} state="empty" emptyMessage="No items found" />);
      expect(screen.getByText("No items found")).toBeInTheDocument();
    });

    it("renders error state with message", () => {
      render(
        <DataTable columns={columns} data={[]} state="error" errorMessage="Failed to load data" />,
      );
      expect(screen.getByText("Failed to load data")).toBeInTheDocument();
    });

    it("renders timed-out state with message", () => {
      render(
        <DataTable
          columns={columns}
          data={[]}
          state="timeout"
          timeoutMessage="Request timed out"
        />,
      );
      expect(screen.getByText("Request timed out")).toBeInTheDocument();
    });

    it("renders data rows when state is ready", () => {
      render(<DataTable columns={columns} data={testData} state="ready" />);
      expect(screen.getByText("Alpha")).toBeInTheDocument();
      expect(screen.getByText("Beta")).toBeInTheDocument();
      expect(screen.getByText("Gamma")).toBeInTheDocument();
    });
  });

  describe("table semantics", () => {
    it("uses real <table> element", () => {
      render(<DataTable columns={columns} data={testData} state="ready" />);
      expect(screen.getByRole("table")).toBeInTheDocument();
    });

    it("uses <thead> and <tbody>", () => {
      const { container } = render(<DataTable columns={columns} data={testData} state="ready" />);
      expect(container.querySelector("thead")).toBeInTheDocument();
      expect(container.querySelector("tbody")).toBeInTheDocument();
    });

    it("uses <th> for header cells", () => {
      render(<DataTable columns={columns} data={testData} state="ready" />);
      expect(screen.getByRole("columnheader", { name: /name/i })).toBeInTheDocument();
      expect(screen.getByRole("columnheader", { name: /count/i })).toBeInTheDocument();
    });
  });

  describe("row click", () => {
    it("fires onRowClick when a row is clicked", async () => {
      const onRowClick = vi.fn();
      render(<DataTable columns={columns} data={testData} state="ready" onRowClick={onRowClick} />);
      const row = screen.getByText("Alpha").closest("tr");
      expect(row).not.toBeNull();
      await userEvent.click(row as HTMLElement);
      expect(onRowClick).toHaveBeenCalledWith(testData[0]);
    });

    it("fires onRowClick with correct row data", async () => {
      const onRowClick = vi.fn();
      render(<DataTable columns={columns} data={testData} state="ready" onRowClick={onRowClick} />);
      const row = screen.getByText("Beta").closest("tr");
      expect(row).not.toBeNull();
      await userEvent.click(row as HTMLElement);
      expect(onRowClick).toHaveBeenCalledWith(testData[1]);
    });
  });

  describe("sorting", () => {
    it("sorts column ascending on first header click", async () => {
      render(<DataTable columns={columns} data={testData} state="ready" />);
      const nameHeader = screen.getByRole("columnheader", { name: /name/i });
      await userEvent.click(nameHeader);
      const rows = screen.getAllByRole("row");
      // header row + 3 data rows
      // After ascending sort by name: Alpha, Beta, Gamma
      const cells = rows.slice(1).map((r) => r.querySelector("td")?.textContent);
      expect(cells).toEqual(["Alpha", "Beta", "Gamma"]);
    });

    it("sorts column descending on second header click", async () => {
      render(<DataTable columns={columns} data={testData} state="ready" />);
      const nameHeader = screen.getByRole("columnheader", { name: /name/i });
      await userEvent.click(nameHeader);
      await userEvent.click(nameHeader);
      const rows = screen.getAllByRole("row");
      const cells = rows.slice(1).map((r) => r.querySelector("td")?.textContent);
      expect(cells).toEqual(["Gamma", "Beta", "Alpha"]);
    });

    it("sets aria-sort on sorted column header", async () => {
      render(<DataTable columns={columns} data={testData} state="ready" />);
      const nameHeader = screen.getByRole("columnheader", { name: /name/i });
      await userEvent.click(nameHeader);
      expect(nameHeader.getAttribute("aria-sort")).toBe("ascending");
    });
  });

  describe("keyboard navigation", () => {
    it("navigates between rows with arrow keys", () => {
      const onRowClick = vi.fn();
      render(<DataTable columns={columns} data={testData} state="ready" onRowClick={onRowClick} />);
      const tbody = screen.getByRole("table").querySelector("tbody");
      expect(tbody).not.toBeNull();
      const firstRow = tbody?.querySelector("tr");
      expect(firstRow).not.toBeNull();
      (firstRow as HTMLElement).focus();

      fireEvent.keyDown(firstRow as HTMLElement, { key: "ArrowDown" });
      const secondRow = tbody?.querySelectorAll("tr")[1];
      expect(document.activeElement).toBe(secondRow);
    });

    it("activates row with Enter key", () => {
      const onRowClick = vi.fn();
      render(<DataTable columns={columns} data={testData} state="ready" onRowClick={onRowClick} />);
      const tbody = screen.getByRole("table").querySelector("tbody");
      const firstRow = tbody?.querySelector("tr");
      expect(firstRow).not.toBeNull();
      (firstRow as HTMLElement).focus();
      fireEvent.keyDown(firstRow as HTMLElement, { key: "Enter" });
      expect(onRowClick).toHaveBeenCalledWith(testData[0]);
    });

    it("activates row with Space key", () => {
      const onRowClick = vi.fn();
      render(<DataTable columns={columns} data={testData} state="ready" onRowClick={onRowClick} />);
      const tbody = screen.getByRole("table").querySelector("tbody");
      const firstRow = tbody?.querySelector("tr");
      expect(firstRow).not.toBeNull();
      (firstRow as HTMLElement).focus();
      fireEvent.keyDown(firstRow as HTMLElement, { key: " " });
      expect(onRowClick).toHaveBeenCalledWith(testData[0]);
    });
  });

  describe("numeric columns", () => {
    it("applies tabular-nums and right alignment to numeric columns", () => {
      render(<DataTable columns={columns} data={testData} state="ready" />);
      // Find the count cells (second column)
      const rows = screen.getAllByRole("row").slice(1);
      const countCells = rows.map((r) => r.querySelectorAll("td")[1]);
      for (const cell of countCells) {
        expect(cell?.className).toContain("tabular-nums");
        expect(cell?.className).toContain("text-right");
      }
    });
  });

  describe("no hardcoded values", () => {
    it("does not have inline styles with hardcoded colors", () => {
      const { container } = render(<DataTable columns={columns} data={testData} state="ready" />);
      const allElements = container.querySelectorAll("*");
      for (const el of allElements) {
        const style = el.getAttribute("style");
        if (style) {
          expect(style).not.toMatch(/#[0-9a-fA-F]{3,8}/);
          expect(style).not.toMatch(/rgb\(/);
        }
      }
    });
  });
});
