import { getServerSession } from "next-auth";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { QueryProvider } from "@/components/query-provider";
import { WorkspaceShell } from "@/components/workspace-shell";
import { authOptions } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function WorkspaceLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  const session = await getServerSession(authOptions);
  if (!session?.user?.email) {
    redirect("/login");
  }

  return (
    <QueryProvider>
      <WorkspaceShell email={session.user.email}>{children}</WorkspaceShell>
    </QueryProvider>
  );
}
