"use client";

import { Search } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useDeferredValue, useState } from "react";
import type { z } from "zod";

import { DataGrid } from "@/components/data-grid";
import { PageHeading } from "@/components/page-heading";
import { ErrorState, LoadingState } from "@/components/request-state";
import { readBackend, type BackendEndpoint } from "@/lib/api";
import { pageSchema } from "@/lib/contracts";
import type { AmountRow } from "@/lib/grid-types";

const PAGE_SIZE = 100;

export function DataWorkspace<T extends AmountRow>({
  title,
  description,
  endpoint,
  rowSchema,
  columns,
  statusOptions,
  searchable = true,
}: {
  title: string;
  description: string;
  endpoint: Extract<BackendEndpoint, "disputes" | "invoices" | "payouts" | "activity">;
  rowSchema: z.ZodType<T>;
  columns: import("ag-grid-community").ColDef<T>[];
  statusOptions?: readonly string[];
  searchable?: boolean;
}) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const deferredSearch = useDeferredValue(search.trim());
  const query = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String(offset),
  });
  if (status) {
    query.set("status", status);
  }
  if (searchable && deferredSearch) {
    query.set("search", deferredSearch);
  }
  const resultSchema = pageSchema(rowSchema);
  const result = useQuery({
    queryKey: ["workspace", endpoint, offset, status, deferredSearch],
    queryFn: () => readBackend(endpoint, resultSchema, query),
  });

  return (
    <>
      <PageHeading
        eyebrow="OPERATIONS WORKSPACE"
        title={title}
        description={description}
      />
      <div className="grid-filterbar">
        {searchable ? (
          <label className="search-control">
            <Search aria-hidden="true" size={15} />
            <span className="visually-hidden">
              Search {title.toLowerCase()}
            </span>
            <input
              className="field search-field"
              onChange={(event) => {
                setSearch(event.currentTarget.value);
                setOffset(0);
              }}
              placeholder={`Search ${title.toLowerCase()}...`}
              value={search}
            />
          </label>
        ) : null}
        {statusOptions ? (
          <select
            aria-label={`Filter ${title.toLowerCase()} by status`}
            className="select-field"
            onChange={(event) => {
              setStatus(event.currentTarget.value);
              setOffset(0);
            }}
            value={status}
          >
            <option value="">All statuses</option>
            {statusOptions.map((option) => (
              <option key={option} value={option}>
                {option.replaceAll("_", " ")}
              </option>
            ))}
          </select>
        ) : null}
      </div>
      {result.isLoading ? (
        <LoadingState label={`Loading ${title.toLowerCase()}`} />
      ) : result.isError ? (
        <ErrorState
          message={result.error.message}
          onRetry={() => void result.refetch()}
        />
      ) : result.data?.items.length ? (
        <>
          <DataGrid
            columns={columns}
            fileName={`payagent-${endpoint}.csv`}
            rows={result.data.items}
          />
          <div className="workspace-pagination">
            <span>
              Showing {offset + 1}-
              {Math.min(offset + PAGE_SIZE, result.data.total)} of{" "}
              {result.data.total}
            </span>
            <div className="grid-actions">
              <button
                className="button button-secondary button-small"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(offset - PAGE_SIZE, 0))}
                type="button"
              >
                Previous
              </button>
              <button
                className="button button-secondary button-small"
                disabled={offset + PAGE_SIZE >= result.data.total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
                type="button"
              >
                Next
              </button>
            </div>
          </div>
        </>
      ) : (
        <div className="state-card">
          <div>
            <strong>No {title.toLowerCase()} found</strong>
            <p>
              {search || status
                ? "Try broadening the search or clearing the status filter."
                : "Records will appear here as commerce activity is synced."}
            </p>
          </div>
        </div>
      )}
    </>
  );
}
