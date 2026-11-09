"use client";

import { DataWorkspace } from "@/components/data-workspace";
import { payoutColumns } from "@/components/workspace-columns";
import {
  payoutRowSchema,
  payoutStatusSchema,
  type PayoutStatus,
} from "@/lib/contracts";

const statuses = payoutStatusSchema.options as readonly PayoutStatus[];

export default function PayoutsPage() {
  return (
    <DataWorkspace
      title="Payouts"
      description="Track payout recommendations and approval status. No approve or execute action is available here."
      endpoint="payouts"
      rowSchema={payoutRowSchema}
      columns={payoutColumns}
      statusOptions={statuses}
    />
  );
}
