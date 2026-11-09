import { z } from "zod";

const decimal = z.union([z.string(), z.number()]).transform(String);

const currency = z.string().regex(/^[A-Z]{3}$/);
const timestamp = z.string().datetime({ offset: true });
const uuid = z.string().uuid();

export const amountByCurrencySchema = z.object({
  currency,
  amount: decimal,
  count: z.number().int().nonnegative(),
});

export const dashboardSummarySchema = z.object({
  generated_at: timestamp,
  period_start: timestamp,
  period_end: timestamp,
  revenue: z.array(
    z.object({
      currency,
      gross_volume: decimal,
      previous_gross_volume: decimal,
      transaction_count: z.number().int().nonnegative(),
      average_ticket: decimal,
      change_percent: decimal.nullable(),
    }),
  ),
  disputes: z.object({
    open_count: z.number().int().nonnegative(),
    due_soon_count: z.number().int().nonnegative(),
    overdue_count: z.number().int().nonnegative(),
    open_exposure: z.array(amountByCurrencySchema),
    win_rate: decimal.nullable(),
    opened_last_30_days: z.number().int().nonnegative(),
    opened_previous_30_days: z.number().int().nonnegative(),
  }),
  invoices: z.object({
    outstanding_count: z.number().int().nonnegative(),
    overdue_count: z.number().int().nonnegative(),
    outstanding_amount: z.array(amountByCurrencySchema),
    overdue_amount: z.array(amountByCurrencySchema),
  }),
  payouts: z.object({
    pending_approval_count: z.number().int().nonnegative(),
    pending_approval_amount: z.array(amountByCurrencySchema),
    in_flight_count: z.number().int().nonnegative(),
    failed_count: z.number().int().nonnegative(),
  }),
  risk: z.object({
    overdue_disputes: z.number().int().nonnegative(),
    pending_decisions: z.number().int().nonnegative(),
    manual_review_decisions: z.number().int().nonnegative(),
    overdue_invoices: z.number().int().nonnegative(),
    failed_payouts: z.number().int().nonnegative(),
  }),
  vendors: z.object({
    total: z.number().int().nonnegative(),
    active: z.number().int().nonnegative(),
    pending: z.number().int().nonnegative(),
    suspended: z.number().int().nonnegative(),
    closed: z.number().int().nonnegative(),
  }),
  agents: z.object({
    total: z.number().int().nonnegative(),
    active: z.number().int().nonnegative(),
    paused: z.number().int().nonnegative(),
    pending_decisions: z.number().int().nonnegative(),
  }),
});

export const dashboardTrendsSchema = z.object({
  days: z.number().int().min(7).max(90),
  revenue: z.array(
    z.object({
      day: z.string().date(),
      currency,
      gross_volume: decimal,
      transaction_count: z.number().int().nonnegative(),
    }),
  ),
  disputes: z.array(
    z.object({
      day: z.string().date(),
      opened_count: z.number().int().nonnegative(),
    }),
  ),
});

export const disputeStatusSchema = z.enum([
  "needs_response",
  "under_review",
  "won",
  "lost",
  "closed",
]);
export const invoiceStatusSchema = z.enum([
  "draft",
  "sent",
  "paid",
  "overdue",
  "cancelled",
]);
export const payoutStatusSchema = z.enum([
  "pending_approval",
  "approved",
  "processing",
  "paid",
  "failed",
  "cancelled",
]);

export const disputeRowSchema = z.object({
  id: uuid,
  vendor_id: uuid,
  vendor_name: z.string(),
  transaction_id: uuid,
  external_dispute_id: z.string(),
  reason: z.string(),
  status: disputeStatusSchema,
  amount: decimal,
  currency,
  response_due_at: timestamp.nullable(),
  opened_at: timestamp,
  created_at: timestamp,
  updated_at: timestamp,
});

export const invoiceRowSchema = z.object({
  id: uuid,
  vendor_id: uuid,
  vendor_name: z.string(),
  invoice_number: z.string(),
  status: invoiceStatusSchema,
  amount: decimal,
  currency,
  due_at: timestamp.nullable(),
  created_at: timestamp,
  updated_at: timestamp,
});

export const payoutRowSchema = z.object({
  id: uuid,
  vendor_id: uuid,
  vendor_name: z.string(),
  status: payoutStatusSchema,
  amount: decimal,
  currency,
  reference: z.string().nullable(),
  approved_at: timestamp.nullable(),
  created_at: timestamp,
  updated_at: timestamp,
});

export const activityRowSchema = z.object({
  id: uuid,
  vendor_id: uuid,
  entity_type: z.enum([
    "user",
    "vendor",
    "transaction",
    "dispute",
    "invoice",
    "payout",
    "agent",
    "decision",
  ]),
  entity_id: uuid,
  action: z.string(),
  actor_type: z.enum(["user", "agent", "system"]),
  actor_name: z.string().nullable(),
  created_at: timestamp,
});

export const insightSchema = z.object({
  category: z.enum([
    "revenue_leakage",
    "dispute_trends",
    "vendor_performance",
    "cost_insights",
    "recommendation",
  ]),
  severity: z.enum(["critical", "warning", "info"]),
  title: z.string(),
  summary: z.string(),
  recommendation: z.string(),
  evidence: z.array(z.string()),
});

export const copilotOverviewSchema = z.object({
  generated_at: timestamp,
  insights: z.array(insightSchema),
});

export const copilotAnswerSchema = z.object({
  answer: z.string(),
  generated_at: timestamp,
  sources: z.array(z.string()),
});

export const copilotQuestionSchema = z.object({
  question: z.string().trim().min(3).max(1000),
});

export function pageSchema<T extends z.ZodType>(itemSchema: T) {
  return z.object({
    items: z.array(itemSchema),
    total: z.number().int().nonnegative(),
    limit: z.number().int().min(1).max(100),
    offset: z.number().int().nonnegative(),
  });
}

export type DashboardSummary = z.infer<typeof dashboardSummarySchema>;
export type DashboardTrends = z.infer<typeof dashboardTrendsSchema>;
export type DisputeRow = z.infer<typeof disputeRowSchema>;
export type InvoiceRow = z.infer<typeof invoiceRowSchema>;
export type PayoutRow = z.infer<typeof payoutRowSchema>;
export type ActivityRow = z.infer<typeof activityRowSchema>;
export type ExecutiveInsight = z.infer<typeof insightSchema>;
export type CopilotAnswer = z.infer<typeof copilotAnswerSchema>;
export type DisputeStatus = z.infer<typeof disputeStatusSchema>;
export type InvoiceStatus = z.infer<typeof invoiceStatusSchema>;
export type PayoutStatus = z.infer<typeof payoutStatusSchema>;
