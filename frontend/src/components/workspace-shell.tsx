"use client";

import {
  Activity,
  ArrowUpRight,
  Bot,
  CircleDollarSign,
  FileText,
  LayoutDashboard,
  ShieldAlert,
  Store,
} from "lucide-react";
import { signOut } from "next-auth/react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { NotificationCenter } from "@/components/notification-center";

const navigation = [
  { href: "/dashboard", label: "Overview", icon: LayoutDashboard },
  { href: "/disputes", label: "Disputes", icon: ShieldAlert },
  { href: "/invoices", label: "Invoices", icon: FileText },
  { href: "/payouts", label: "Payouts", icon: CircleDollarSign },
  { href: "/activity", label: "Activity", icon: Activity },
  { href: "/copilot", label: "Executive copilot", icon: Bot },
];

export function WorkspaceShell({
  children,
  email,
}: {
  children: ReactNode;
  email: string;
}) {
  const pathname = usePathname();

  return (
    <div className="workspace-shell">
      <aside className="sidebar">
        <Link className="brand-lockup" href="/dashboard">
          <span className="brand-mark">
            <Store size={19} strokeWidth={2.2} />
          </span>
          <span>
            <strong>PayAgent</strong>
            <small>OPS CONSOLE</small>
          </span>
        </Link>
        <div className="sidebar-section-label">WORKSPACE</div>
        <nav aria-label="Primary navigation" className="sidebar-nav">
          {navigation.map(({ href, label, icon: Icon }) => {
            const active =
              pathname === href ||
              (href !== "/dashboard" && pathname.startsWith(`${href}/`));
            return (
              <Link
                aria-current={active ? "page" : undefined}
                className={`nav-link${active ? " active" : ""}`}
                href={href}
                key={href}
              >
                <Icon aria-hidden="true" size={17} />
                <span>{label}</span>
                {active && <span className="nav-active-dot" />}
              </Link>
            );
          })}
        </nav>
        <div className="sidebar-bottom">
          <div className="environment-badge">
            <span className="environment-dot" />
            Sandbox connected
          </div>
          <div className="sidebar-user">
            <span className="avatar">{email.charAt(0).toUpperCase()}</span>
            <span className="sidebar-user-email" title={email}>
              {email}
            </span>
            <button
              aria-label="Sign out"
              className="icon-button"
              onClick={() => void signOut({ callbackUrl: "/login" })}
              title="Sign out"
              type="button"
            >
              <ArrowUpRight aria-hidden="true" size={16} />
            </button>
          </div>
        </div>
      </aside>
      <div className="workspace-main">
        <header className="topbar">
          <div className="breadcrumb">
            <span>Commerce operations</span>
            <span aria-hidden="true" className="breadcrumb-slash">
              /
            </span>
            <span className="breadcrumb-current">
              {navigation.find((item) => item.href === pathname)?.label ??
                "Workspace"}
            </span>
          </div>
          <div className="topbar-meta">
            <NotificationCenter />
            <span className="topbar-divider" />
            <span className="topbar-date">
              {new Intl.DateTimeFormat("en", {
                weekday: "short",
                month: "short",
                day: "numeric",
              }).format(new Date())}
            </span>
          </div>
        </header>
        <main className="page-content">{children}</main>
      </div>
    </div>
  );
}
