"use client";

import { DataWorkspace } from "@/components/data-workspace";
import { disputeColumns } from "@/components/workspace-columns";
import {
  disputeRowSchema,
  disputeStatusSchema,
  type DisputeStatus,
} from "@/lib/contracts";

const statuses = disputeStatusSchema.options as readonly DisputeStatus[];

export default function DisputesPage() {
  return (
    <DataWorkspace
      title="Disputes"
      description="Triage response deadlines and review the evidence queue. Submission remains a human-approved action."
      endpoint="disputes"
      rowSchema={disputeRowSchema}
      columns={disputeColumns}
      statusOptions={statuses}
    />
  );
}
