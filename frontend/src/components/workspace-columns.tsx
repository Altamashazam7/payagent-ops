import type { ColDef, ICellRendererParams } from "ag-grid-community";

import { StatusBadge } from "@/components/status-badge";
import {
  currencyColumn,
  dateColumn,
} from "@/components/data-grid";
import type {
  ActivityRow,
  DisputeRow,
  InvoiceRow,
  PayoutRow,
} from "@/lib/contracts";

function statusRenderer<T>(
  params: ICellRendererParams<T, string>,
): React.ReactNode {
  return typeof params.value === "string" ? (
    <StatusBadge value={params.value} />
  ) : null;
}

export const disputeColumns: ColDef<DisputeRow>[] = [
  { field: "external_dispute_id", headerName: "Dispute ID", minWidth: 155 },
  { field: "vendor_name", headerName: "Vendor" },
  { field: "reason", headerName: "Reason", minWidth: 190 },
  {
    field: "status",
    headerName: "Status",
    cellRenderer: statusRenderer<DisputeRow>,
  },
  currencyColumn<DisputeRow>("Amount"),
  dateColumn<DisputeRow>("response_due_at", "Response due"),
  dateColumn<DisputeRow>("opened_at", "Opened"),
];

export const invoiceColumns: ColDef<InvoiceRow>[] = [
  { field: "invoice_number", headerName: "Invoice", minWidth: 145 },
  { field: "vendor_name", headerName: "Vendor" },
  {
    field: "status",
    headerName: "Status",
    cellRenderer: statusRenderer<InvoiceRow>,
  },
  currencyColumn<InvoiceRow>("Amount"),
  dateColumn<InvoiceRow>("due_at", "Due date"),
  dateColumn<InvoiceRow>("created_at", "Created"),
];

export const payoutColumns: ColDef<PayoutRow>[] = [
  { field: "vendor_name", headerName: "Vendor" },
  {
    field: "status",
    headerName: "Status",
    cellRenderer: statusRenderer<PayoutRow>,
  },
  currencyColumn<PayoutRow>("Amount"),
  { field: "reference", headerName: "Reference", minWidth: 160 },
  dateColumn<PayoutRow>("approved_at", "Approved"),
  dateColumn<PayoutRow>("created_at", "Requested"),
];

export const activityColumns: ColDef<ActivityRow>[] = [
  dateColumn<ActivityRow>("created_at", "When"),
  { field: "actor_type", headerName: "Actor type" },
  { field: "actor_name", headerName: "Actor" },
  { field: "action", headerName: "Action", minWidth: 180 },
  { field: "entity_type", headerName: "Record type" },
  { field: "entity_id", headerName: "Record ID", minWidth: 230 },
];
