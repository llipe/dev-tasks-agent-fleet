"use client";

import { useRef, useCallback, useState } from "react";
import { flexRender } from "@tanstack/react-table";
import {
  useLegacyTable,
  getCoreRowModel,
  getSortedRowModel,
  legacyCreateColumnHelper,
} from "@tanstack/react-table/legacy";
import { cn } from "@/lib/utils/cn";

export { legacyCreateColumnHelper as createColumnHelper };

/** Sorting state: array of { id, desc } */
type SortingEntry = { id: string; desc: boolean };
type SortingState = SortingEntry[];

export type DataTableState = "ready" | "loading" | "empty" | "error" | "timeout";

export interface DataTableProps<TData> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  columns: readonly any[];
  data: TData[];
  state: DataTableState;
  onRowClick?: (row: TData) => void;
  emptyMessage?: string;
  errorMessage?: string;
  timeoutMessage?: string;
  className?: string;
}

/**
 * DataTable built on TanStack Table with real <table> semantics.
 * Features: sorting, row click, keyboard navigation (arrow/Enter/Space),
 * four states (loading, empty, error, timeout), numeric column alignment.
 */
export function DataTable<TData extends object>({
  columns,
  data,
  state,
  onRowClick,
  emptyMessage = "No data available",
  errorMessage = "An error occurred",
  timeoutMessage = "Request timed out",
  className,
}: DataTableProps<TData>) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const tbodyRef = useRef<HTMLTableSectionElement>(null);

  const table = useLegacyTable({
    data,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    columns: columns as any,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTableRowElement>, rowData: TData) => {
      const target = e.currentTarget;
      const tbody = tbodyRef.current;
      if (!tbody) return;

      const rows = Array.from(tbody.querySelectorAll("tr"));
      const currentIndex = rows.indexOf(target);

      switch (e.key) {
        case "ArrowDown": {
          e.preventDefault();
          const next = rows[currentIndex + 1];
          if (next) next.focus();
          break;
        }
        case "ArrowUp": {
          e.preventDefault();
          const prev = rows[currentIndex - 1];
          if (prev) prev.focus();
          break;
        }
        case "Enter":
        case " ": {
          e.preventDefault();
          onRowClick?.(rowData);
          break;
        }
      }
    },
    [onRowClick],
  );

  const getSortDirection = (columnId: string): "ascending" | "descending" | "none" => {
    const sortEntry = sorting.find((s) => s.id === columnId);
    if (!sortEntry) return "none";
    return sortEntry.desc ? "descending" : "ascending";
  };

  return (
    <div className={cn("overflow-auto", className)}>
      <table className="w-full border-collapse text-sm">
        <thead>
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id}>
              {headerGroup.headers.map((header) => {
                const isNumeric =
                  (header.column.columnDef.meta as { numeric?: boolean })?.numeric ?? false;
                const sortDir = getSortDirection(header.column.id);

                return (
                  <th
                    key={header.id}
                    className={cn(
                      "border-b border-surface-border px-3 py-2 font-medium text-text-secondary",
                      isNumeric ? "text-right" : "text-left",
                      header.column.getCanSort() && "cursor-pointer select-none",
                    )}
                    aria-sort={sortDir}
                    onClick={header.column.getToggleSortingHandler()}
                  >
                    {header.isPlaceholder
                      ? null
                      : flexRender(header.column.columnDef.header, header.getContext())}
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody ref={tbodyRef}>
          {state === "loading" && <LoadingSkeleton columnCount={columns.length} />}
          {state === "empty" && <StateRow columnCount={columns.length} message={emptyMessage} />}
          {state === "error" && <StateRow columnCount={columns.length} message={errorMessage} />}
          {state === "timeout" && (
            <StateRow columnCount={columns.length} message={timeoutMessage} />
          )}
          {state === "ready" &&
            table.getRowModel().rows.map((row) => (
              <tr
                key={row.id}
                className={cn(
                  "border-b border-surface-border transition-colors hover:bg-surface-hover",
                  onRowClick && "cursor-pointer",
                )}
                tabIndex={0}
                onClick={() => onRowClick?.(row.original as TData)}
                onKeyDown={(e) => handleKeyDown(e, row.original as TData)}
              >
                {row.getVisibleCells().map((cell) => {
                  const isNumeric =
                    (cell.column.columnDef.meta as { numeric?: boolean })?.numeric ?? false;

                  return (
                    <td
                      key={cell.id}
                      className={cn(
                        "px-3 py-2 text-text-primary",
                        isNumeric && "tabular-nums text-right",
                      )}
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  );
                })}
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  );
}

function LoadingSkeleton({ columnCount }: { columnCount: number }) {
  return (
    <>
      {Array.from({ length: 5 }).map((_, rowIdx) => (
        <tr key={rowIdx} aria-label={rowIdx === 0 ? "Loading data" : undefined}>
          {Array.from({ length: columnCount }).map((_, colIdx) => (
            <td key={colIdx} className="px-3 py-2">
              <div className="h-4 animate-pulse rounded-sm bg-surface-hover" />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}

function StateRow({ columnCount, message }: { columnCount: number; message: string }) {
  return (
    <tr>
      <td colSpan={columnCount} className="px-3 py-8 text-center text-text-muted">
        {message}
      </td>
    </tr>
  );
}
