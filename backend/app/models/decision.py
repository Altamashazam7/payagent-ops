"""Human-reviewable agent decision model."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel
from app.models.enums import DecisionStatus

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.dispute import Dispute
    from app.models.invoice import Invoice
    from app.models.payout import Payout
    from app.models.transaction import Transaction
    from app.models.vendor import Vendor


class Decision(BaseModel):
    """Agent recommendation linked to exactly one vendor-scoped subject."""

    __tablename__ = "decisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["vendor_id", "transaction_id"],
            ["transactions.vendor_id", "transactions.id"],
            name="fk_decisions_vendor_transaction",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["vendor_id", "dispute_id"],
            ["disputes.vendor_id", "disputes.id"],
            name="fk_decisions_vendor_dispute",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["vendor_id", "invoice_id"],
            ["invoices.vendor_id", "invoices.id"],
            name="fk_decisions_vendor_invoice",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["vendor_id", "payout_id"],
            ["payouts.vendor_id", "payouts.id"],
            name="fk_decisions_vendor_payout",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(CASE WHEN transaction_id IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN dispute_id IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN invoice_id IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN payout_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="exactly_one_subject",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_in_range",
        ),
        CheckConstraint(
            "(status IN ('approved', 'rejected') AND "
            "reviewed_by_user_id IS NOT NULL AND reviewed_at IS NOT NULL) OR "
            "(status NOT IN ('approved', 'rejected') AND "
            "reviewed_by_user_id IS NULL AND reviewed_at IS NULL)",
            name="review_status_requires_human",
        ),
        Index(
            "ix_decisions_vendor_status_created",
            "vendor_id",
            "status",
            "created_at",
        ),
        Index("ix_decisions_agent_created", "agent_id", "created_at"),
    )

    vendor_id: Mapped[UUID] = mapped_column(
        ForeignKey("vendors.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    transaction_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    dispute_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    invoice_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    payout_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    action_type: Mapped[str] = mapped_column(String(100), nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    status: Mapped[DecisionStatus] = mapped_column(
        Enum(
            DecisionStatus,
            name="decision_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda values: [member.value for member in values],
        ),
        nullable=False,
        default=DecisionStatus.PENDING,
        index=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    vendor: Mapped[Vendor] = relationship(back_populates="decisions")
    agent: Mapped[Agent | None] = relationship(back_populates="decisions")
    transaction: Mapped[Transaction | None] = relationship(
        back_populates="decisions",
        viewonly=True,
    )
    dispute: Mapped[Dispute | None] = relationship(
        back_populates="decisions",
        viewonly=True,
    )
    invoice: Mapped[Invoice | None] = relationship(
        back_populates="decisions",
        viewonly=True,
    )
    payout: Mapped[Payout | None] = relationship(
        back_populates="decisions",
        viewonly=True,
    )
