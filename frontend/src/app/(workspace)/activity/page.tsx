"use client";

import { DataWorkspace } from "@/components/data-workspace";
import { activityColumns } from "@/components/workspace-columns";
import { activityRowSchema } from "@/lib/contracts";

export default function ActivityPage() {
  return (
    <DataWorkspace
      title="Activity"
      description="Review a sanitized audit trail of human and agent activity across your tenant."
      endpoint="activity"
      rowSchema={activityRowSchema}
      columns={activityColumns}
      searchable={false}
    />
  );
}
