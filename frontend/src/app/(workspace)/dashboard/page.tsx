"use client";

import {
  Activity,
  CircleDollarSign,
  Clock3,
  FileWarning,
  ShieldAlert,
  Store,
  Users,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useState } from "react";
import type { ReactNode } from "react";

import { PageHeading } from "@/components/page-heading";
import { ErrorState, LoadingState } from "@/components/request-state";
import { readBackend } from "@/lib/api";
import {
  dashboardSummarySchema,
  dashboardTrendsSchema,
} from "@/lib/contracts";
import { formatCurrency } from "@/lib/format";

const chartTooltip = {
  contentStyle: {
    border: "1px solid #29394a",
    borderRadius: 8,
    background: "#111a24",
    color: "#e8eef5",
    fontSize: 11,
  },
  labelStyle: { color: "#8290a1" },
};

function MetricCard({
  label,
  value,
  caption,
  icon,
  tone,
}: {
  label: string;
  value: string;
  caption: string;
  icon: ReactNode;
  tone?: string;
}) {
  return (
    <article className="metric-card">
      <div className="metric-header">
        <span>{label}</span>
        <span className="metric-icon">{icon}</span>
      </div>
      <div className="metric-value">{value}</div>
      <div className={`metric-caption ${tone ?? ""}`}>{caption}</div>
    </article>
  );
}

export default function DashboardPage() {
  const [currency, setCurrency] = useState("");
  const summaryQuery = useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: () => readBackend("dashboard/summary", dashboardSummarySchema),
  });
  const trendsQuery = useQuery({
    queryKey: ["dashboard-trends", 30],
    queryFn: () =>
      readBackend(
        "dashboard/trends",
        dashboardTrendsSchema,
        new URLSearchParams({ days: "30" }),
      ),
  });

  if (summaryQuery.isLoading || trendsQuery.isLoading) {
    return <LoadingState label="Loading executive overview" />;
  }
  if (summaryQuery.isError || trendsQuery.isError) {
    const error = summaryQuery.error ?? trendsQuery.error;
    return (
      <ErrorState
        message={error?.message ?? "The reporting API did not return data."}
        onRetry={() => {
          void summaryQuery.refetch();
          void trendsQuery.refetch();
        }}
      />
    );
  }
  if (!summaryQuery.data || !trendsQuery.data) {
    return (
      <ErrorState
        message="The reporting API returned an incomplete dashboard snapshot."
        onRetry={() => {
          void summaryQuery.refetch();
          void trendsQuery.refetch();
        }}
      />
    );
  }

  const summary = summaryQuery.data;
  const trends = trendsQuery.data;
  const selectedRevenue =
    summary.revenue.find((item) => item.currency === currency) ??
    summary.revenue[0];
  const selectedCurrency = selectedRevenue?.currency ?? "";
  const revenueRows = trends.revenue
    .filter((point) => point.currency === selectedCurrency)
    .map((point) => ({
      ...point,
      chartVolume: Number(point.gross_volume),
      label: new Intl.DateTimeFormat("en", {
        month: "short",
        day: "numeric",
      }).format(new Date(`${point.day}T00:00:00`)),
    }));
  const disputeRows = trends.disputes.map((point) => ({
    ...point,
    label: new Intl.DateTimeFormat("en", {
      month: "short",
      day: "numeric",
    }).format(new Date(`${point.day}T00:00:00`)),
  }));
  const periodLabel = "LAST 30 DAYS";

  return (
    <>
      <PageHeading
        eyebrow="EXECUTIVE OVERVIEW · 01"
        title="Commerce at a glance"
        description="A live operating picture of revenue, exposure, and agent work across your tenant."
        actions={
          <span className="period-pill">
            <span className="period-dot" />
            {periodLabel}
          </span>
        }
      />
      <section aria-label="Key performance indicators" className="metrics-grid">
        <MetricCard
          label="Gross captured volume"
          value={
            selectedRevenue
              ? formatCurrency(
                  selectedRevenue.gross_volume,
                  selectedRevenue.currency,
                )
              : "--"
          }
          caption={
            selectedRevenue
              ? `${selectedRevenue.currency} · before refunds`
              : "No captured transactions in this period"
          }
          icon={<CircleDollarSign aria-hidden="true" size={16} />}
          tone={
            selectedRevenue?.change_percent !== null &&
            selectedRevenue?.change_percent !== undefined
              ? Number(selectedRevenue.change_percent) >= 0
                ? "positive-change"
                : "negative-change"
              : ""
          }
        />
        <MetricCard
          label="Open disputes"
          value={String(summary.disputes.open_count)}
          caption={`${summary.disputes.due_soon_count} due within 7 days`}
          icon={<ShieldAlert aria-hidden="true" size={16} />}
          tone={
            summary.disputes.overdue_count > 0 ? "negative-change" : undefined
          }
        />
        <MetricCard
          label="Overdue invoices"
          value={String(summary.invoices.overdue_count)}
          caption={`${summary.invoices.outstanding_count} outstanding`}
          icon={<FileWarning aria-hidden="true" size={16} />}
        />
        <MetricCard
          label="Payouts awaiting review"
          value={String(summary.payouts.pending_approval_count)}
          caption={`${summary.payouts.in_flight_count} in flight`}
          icon={<Clock3 aria-hidden="true" size={16} />}
        />
      </section>

      <section className="dashboard-panels">
        <article className="panel">
          <div className="panel-heading">
            <div>
              <h2>Revenue trajectory</h2>
              <p>Daily captured volume, grouped by currency</p>
            </div>
            <label className="visually-hidden" htmlFor="revenue-currency">
              Revenue chart currency
            </label>
            {summary.revenue.length ? (
              <select
                className="select-field chart-currency-select"
                id="revenue-currency"
                onChange={(event) => setCurrency(event.currentTarget.value)}
                value={selectedCurrency}
              >
                {summary.revenue.map((item) => (
                  <option key={item.currency} value={item.currency}>
                    {item.currency}
                  </option>
                ))}
              </select>
            ) : null}
          </div>
          {revenueRows.length ? (
            <div className="chart-wrap">
              <ResponsiveContainer height="100%" width="100%">
                <AreaChart data={revenueRows} margin={{ left: -18, right: 8 }}>
                  <defs>
                    <linearGradient id="revenueFill" x1="0" x2="0" y1="0" y2="1">
                      <stop offset="0%" stopColor="#58e0b0" stopOpacity={0.28} />
                      <stop offset="95%" stopColor="#58e0b0" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid
                    stroke="#1b2732"
                    strokeDasharray="3 5"
                    vertical={false}
                  />
                  <XAxis
                    axisLine={false}
                    dataKey="label"
                    tick={{ fill: "#718092", fontSize: 10 }}
                    tickLine={false}
                    tickMargin={10}
                  />
                  <YAxis
                    axisLine={false}
                    tick={{ fill: "#718092", fontSize: 10 }}
                    tickLine={false}
                    tickFormatter={(value: number) =>
                      new Intl.NumberFormat("en", {
                        notation: "compact",
                        maximumFractionDigits: 1,
                      }).format(value)
                    }
                  />
                  <Tooltip
                    {...chartTooltip}
                    formatter={(value) => [
                      formatCurrency(String(value ?? "0"), selectedCurrency),
                      "Captured",
                    ]}
                  />
                  <Area
                    dataKey="chartVolume"
                    stroke="#58e0b0"
                    strokeWidth={2}
                    fill="url(#revenueFill)"
                    type="monotone"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="chart-empty">
              Captured revenue trends will appear when transactions are synced.
            </div>
          )}
        </article>
        <article className="panel">
          <div className="panel-heading">
            <div>
              <h2>Dispute intake</h2>
              <p>New cases opened per day</p>
            </div>
            <span className="panel-meta">30D</span>
          </div>
          {disputeRows.length ? (
            <div className="chart-wrap">
              <ResponsiveContainer height="100%" width="100%">
                <BarChart data={disputeRows} margin={{ left: -25, right: 2 }}>
                  <CartesianGrid
                    stroke="#1b2732"
                    strokeDasharray="3 5"
                    vertical={false}
                  />
                  <XAxis
                    axisLine={false}
                    dataKey="label"
                    tick={{ fill: "#718092", fontSize: 9 }}
                    tickLine={false}
                    tickMargin={10}
                  />
                  <YAxis
                    allowDecimals={false}
                    axisLine={false}
                    tick={{ fill: "#718092", fontSize: 10 }}
                    tickLine={false}
                  />
                  <Tooltip {...chartTooltip} />
                  <Bar
                    dataKey="opened_count"
                    fill="#6ba6ff"
                    maxBarSize={16}
                    radius={[4, 4, 0, 0]}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="chart-empty">No dispute intake in this period.</div>
          )}
        </article>
      </section>

      <section className="dashboard-lower">
        <article className="panel">
          <div className="panel-heading">
            <div>
              <h2>Dispute exposure</h2>
              <p>Response work and outcomes</p>
            </div>
            <ShieldAlert aria-hidden="true" color="#e3b65e" size={17} />
          </div>
          <div className="health-list">
            <HealthRow
              label="Past response due"
              value={summary.disputes.overdue_count}
              max={Math.max(summary.disputes.open_count, 1)}
              tone="danger"
            />
            <HealthRow
              label="Due in 7 days"
              value={summary.disputes.due_soon_count}
              max={Math.max(summary.disputes.open_count, 1)}
            />
            <div className="health-row">
              <span>Win rate</span>
              <span className="health-value">
                {summary.disputes.win_rate === null
                  ? "Not enough data"
                  : `${summary.disputes.win_rate}%`}
              </span>
            </div>
          </div>
        </article>
        <article className="panel">
          <div className="panel-heading">
            <div>
              <h2>Vendor network</h2>
              <p>Current onboarding and operating status</p>
            </div>
            <Store aria-hidden="true" color="#82b7bf" size={17} />
          </div>
          <div className="health-list">
            <HealthRow
              label="Active"
              value={summary.vendors.active}
              max={Math.max(summary.vendors.total, 1)}
            />
            <HealthRow
              label="Pending onboarding"
              value={summary.vendors.pending}
              max={Math.max(summary.vendors.total, 1)}
              tone="warning"
            />
            <HealthRow
              label="Suspended"
              value={summary.vendors.suspended}
              max={Math.max(summary.vendors.total, 1)}
              tone="danger"
            />
          </div>
        </article>
        <article className="panel">
          <div className="panel-heading">
            <div>
              <h2>Agent operations</h2>
              <p>Recommendations never execute financial actions</p>
            </div>
            <Activity aria-hidden="true" color="#69cdaa" size={17} />
          </div>
          <div className="health-list">
            <div className="health-row">
              <span>Active agents</span>
              <span className="health-value">{summary.agents.active}</span>
            </div>
            <div className="health-row">
              <span>Pending decisions</span>
              <span className="health-value">
                {summary.risk.pending_decisions}
              </span>
            </div>
            <div className="health-row">
              <span>Manual review</span>
              <span className="health-value">
                {summary.risk.manual_review_decisions}
              </span>
            </div>
            <div className="agent-footnote">
              <Users aria-hidden="true" size={13} />
              A human reviewer remains the final approver.
            </div>
          </div>
        </article>
      </section>
    </>
  );
}

function HealthRow({
  label,
  value,
  max,
  tone = "success",
}: {
  label: string;
  value: number;
  max: number;
  tone?: "success" | "warning" | "danger";
}) {
  const percentage = Math.min((value / max) * 100, 100);
  return (
    <div>
      <div className="health-row">
        <span>{label}</span>
        <span className={`health-value ${tone}-text`}>{value}</span>
      </div>
      <div className="health-track" aria-hidden="true">
        <div
          className={`health-fill ${tone}`}
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
}
