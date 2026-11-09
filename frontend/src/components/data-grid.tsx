"use client";

import type { ColDef } from "ag-grid-community";
import { themeQuartz } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import { useRef, useState, type CSSProperties } from "react";

import "@/lib/ag-grid";
import { formatCurrency, formatDate } from "@/lib/format";
import type { AmountRow } from "@/lib/grid-types";

const gridStyle: CSSProperties = {
  width: "100%",
  height: "min(66vh, 680px)",
  minHeight: 420,
};

export function DataGrid<T extends AmountRow>({
  rows,
  columns,
  fileName,
}: {
  rows: T[];
  columns: ColDef<T>[];
  fileName: string;
}) {
  const gridRef = useRef<AgGridReact<T>>(null);
  const [selectedCount, setSelectedCount] = useState(0);
  const defaultColDef: ColDef<T> = {
    flex: 1,
    minWidth: 130,
    sortable: true,
    resizable: true,
    filter: "agSetColumnFilter",
  };

  return (
    <section className="grid-shell" aria-label={`${fileName} data workspace`}>
      <div className="grid-toolbar">
        <div className="grid-record-count">
          <span className="record-indicator" />
          {rows.length} rows loaded
        </div>
        <div className="grid-actions">
          <span aria-live="polite" className="selection-count">
            {selectedCount ? `${selectedCount} selected` : "Select rows to export"}
          </span>
          <button
            className="button button-secondary button-small"
            disabled={selectedCount === 0}
            onClick={() =>
              gridRef.current?.api.exportDataAsCsv({
                fileName,
                onlySelected: true,
              })
            }
            type="button"
          >
            Export selected
          </button>
        </div>
      </div>
      <div className="ag-theme-quartz payagent-grid" style={gridStyle}>
        <AgGridReact<T>
          ref={gridRef}
          rowData={rows}
          columnDefs={columns}
          defaultColDef={defaultColDef}
          rowSelection={{
            mode: "multiRow",
            checkboxes: true,
            headerCheckbox: true,
            enableClickSelection: false,
          }}
          onSelectionChanged={() =>
            setSelectedCount(gridRef.current?.api.getSelectedRows().length ?? 0)
          }
          getRowId={({ data }) => data.id}
          animateRows
          enableCellTextSelection
          theme={themeQuartz}
        />
      </div>
      <div className="grid-footer">
        <span>Financial actions are intentionally unavailable in this workspace.</span>
        <span>Auto-refreshes every 60 seconds</span>
      </div>
    </section>
  );
}

export function currencyColumn<
  T extends AmountRow & { amount: string; currency: string },
>(headerName: string): ColDef<T> {
  return {
    headerName,
    valueGetter: ({ data }) => data?.amount,
    valueFormatter: ({ value, data }) => {
      if (typeof value !== "string" || !data) {
        return "";
      }
      return formatCurrency(value, data.currency);
    },
  };
}

export function dateColumn<T extends AmountRow>(
  field: keyof T & string,
  headerName: string,
): ColDef<T> {
  return {
    valueGetter: ({ data }) => (data ? data[field] : null),
    headerName,
    valueFormatter: ({ value }) =>
      typeof value === "string" ? formatDate(value) : "",
  };
}
