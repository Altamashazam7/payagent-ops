"use client";

import { DataWorkspace } from "@/components/data-workspace";
import { invoiceColumns } from "@/components/workspace-columns";
import {
  invoiceRowSchema,
  invoiceStatusSchema,
  type InvoiceStatus,
} from "@/lib/contracts";

const statuses = invoiceStatusSchema.options as readonly InvoiceStatus[];

export default function InvoicesPage() {
  return (
    <DataWorkspace
      title="Invoices"
      description="Monitor invoice compliance and overdue receivables without exposing billing contact details."
      endpoint="invoices"
      rowSchema={invoiceRowSchema}
      columns={invoiceColumns}
      statusOptions={statuses}
    />
  );
}
