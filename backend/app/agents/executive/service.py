"""Executive commerce insights and question-answering orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.executive.narrative import (
    ExecutiveNarrativeGenerator,
    OpenAIExecutiveNarrativeGenerator,
)
from app.core.settings import Settings
from app.schemas.analytics import (
    CopilotAnswer,
    CopilotOverview,
    CopilotQuestion,
    DashboardSummary,
    ExecutiveInsight,
)
from app.services.analytics import AnalyticsService


class ExecutiveCopilotService:
    """Compute explainable findings and ask the model only about aggregates."""

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        narrative_generator: ExecutiveNarrativeGenerator | None = None,
    ) -> None:
        self._analytics = AnalyticsService(session, tenant_id)
        self._narrative_generator = narrative_generator

    @classmethod
    def from_settings(
        cls,
        session: AsyncSession,
        tenant_id: UUID,
        settings: Settings,
    ) -> ExecutiveCopilotService:
        return cls(
            session,
            tenant_id,
            OpenAIExecutiveNarrativeGenerator.from_settings(settings),
        )

    async def overview(self) -> CopilotOverview:
        summary = await self._analytics.dashboard_summary()
        return CopilotOverview(
            generated_at=datetime.now(UTC),
            insights=self._insights(summary),
        )

    async def answer(self, request: CopilotQuestion) -> CopilotAnswer:
        generator = self._narrative_generator
        if generator is None:
            raise ValueError("An executive narrative generator is required")
        summary = await self._analytics.dashboard_summary()
        trends = await self._analytics.dashboard_trends(days=30)
        overview = CopilotOverview(
            generated_at=datetime.now(UTC),
            insights=self._insights(summary),
        )
        answer = await generator.generate(
            request.question,
            summary,
            trends,
            overview,
        )
        if not answer.strip() or len(answer) > 5000:
            raise ValueError("Executive copilot provider returned invalid content")
        return CopilotAnswer(
            answer=answer.strip(),
            generated_at=datetime.now(UTC),
            sources=[
                "dashboard_summary",
                "revenue_trends",
                "dispute_trends",
                "rule_based_insights",
            ],
        )

    async def aclose(self) -> None:
        """Close the optional external provider client after a request."""
        if self._narrative_generator is not None:
            await self._narrative_generator.aclose()

    @staticmethod
    def _insights(summary: DashboardSummary) -> list[ExecutiveInsight]:
        insights: list[ExecutiveInsight] = []
        if summary.invoices.overdue_count:
            for bucket in summary.invoices.overdue_amount:
                if bucket.amount <= 0:
                    continue
                insights.append(
                    ExecutiveInsight(
                        category="revenue_leakage",
                        severity="warning",
                        title=f"Overdue receivables in {bucket.currency}",
                        summary=(
                            f"{bucket.count} invoice(s) are overdue; "
                            f"total outstanding balance is {bucket.amount} "
                            f"{bucket.currency}."
                        ),
                        recommendation=(
                            "Review the overdue invoice queue and reconcile "
                            "unpaid balances with the responsible account owners."
                        ),
                        evidence=[
                            f"overdue_invoice_count={bucket.count}",
                            f"outstanding_{bucket.currency}={bucket.amount}",
                        ],
                    )
                )
        if summary.disputes.due_soon_count or summary.disputes.overdue_count:
            insights.append(
                ExecutiveInsight(
                    category="dispute_trends",
                    severity=(
                        "critical" if summary.disputes.overdue_count else "warning"
                    ),
                    title="Dispute response deadlines need attention",
                    summary=(
                        f"{summary.disputes.overdue_count} open dispute(s) are past "
                        f"due and {summary.disputes.due_soon_count} are due within "
                        "seven days."
                    ),
                    recommendation=(
                        "Prioritize a human review of overdue and near-deadline "
                        "disputes; the copilot does not submit evidence."
                    ),
                    evidence=[
                        f"overdue_disputes={summary.disputes.overdue_count}",
                        f"due_soon_disputes={summary.disputes.due_soon_count}",
                    ],
                )
            )
        if (
            summary.disputes.opened_last_30_days
            > summary.disputes.opened_previous_30_days
        ):
            insights.append(
                ExecutiveInsight(
                    category="dispute_trends",
                    severity="warning",
                    title="New disputes increased",
                    summary=(
                        f"{summary.disputes.opened_last_30_days} disputes opened in "
                        "the last 30 days versus "
                        f"{summary.disputes.opened_previous_30_days} in the prior "
                        "30 days."
                    ),
                    recommendation=(
                        "Review recent dispute reasons and fulfillment evidence "
                        "with the operations team."
                    ),
                    evidence=[
                        f"current_30d={summary.disputes.opened_last_30_days}",
                        f"previous_30d={summary.disputes.opened_previous_30_days}",
                    ],
                )
            )
        if summary.vendors.suspended or summary.vendors.pending:
            insights.append(
                ExecutiveInsight(
                    category="vendor_performance",
                    severity="warning",
                    title="Some vendors are not active",
                    summary=(
                        f"{summary.vendors.pending} vendor(s) are pending and "
                        f"{summary.vendors.suspended} are suspended."
                    ),
                    recommendation=(
                        "Review vendor onboarding and suspension queues before "
                        "planning further payouts."
                    ),
                    evidence=[
                        f"pending_vendors={summary.vendors.pending}",
                        f"suspended_vendors={summary.vendors.suspended}",
                    ],
                )
            )
        if summary.risk.manual_review_decisions:
            insights.append(
                ExecutiveInsight(
                    category="recommendation",
                    severity="warning",
                    title="Agent findings require manual review",
                    summary=(
                        f"{summary.risk.manual_review_decisions} pending agent "
                        "decision(s) are marked for manual review."
                    ),
                    recommendation=(
                        "Review the pending decisions in the relevant command "
                        "center; recommendations do not authorize actions."
                    ),
                    evidence=[
                        f"manual_review_decisions={summary.risk.manual_review_decisions}"
                    ],
                )
            )
        insights.append(
            ExecutiveInsight(
                category="cost_insights",
                severity="info",
                title="Processor fee data is not available",
                summary=(
                    "The current commerce schema does not record PayPal processing "
                    "fees or settlement costs, so cost savings cannot be quantified."
                ),
                recommendation=(
                    "Ingest transaction fee and settlement details before using "
                    "cost comparisons for financial decisions."
                ),
                evidence=["fee_data_available=false"],
            )
        )
        if not insights[:-1]:
            insights.insert(
                0,
                ExecutiveInsight(
                    category="recommendation",
                    severity="info",
                    title="No high-priority findings",
                    summary="The current tenant snapshot has no overdue or elevated-risk findings.",
                    recommendation=(
                        "Continue monitoring the live work queues and review "
                        "new agent recommendations."
                    ),
                    evidence=[
                        f"open_disputes={summary.disputes.open_count}",
                        f"overdue_invoices={summary.invoices.overdue_count}",
                    ],
                ),
            )
        return insights
