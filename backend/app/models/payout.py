"""Vendor payout model with human-approval audit fields."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel
from app.models.enums import PayoutStatus
from app.models.mixins import MonetaryFieldsMixin

if TYPE_CHECKING:
    from app.models.decision import Decision
    from app.models.user import User
    from app.models.vendor import Vendor


class Payout(MonetaryFieldsMixin, BaseModel):
    """Payout request; approval and settlement require recorded human attribution."""

    __tablename__ = "payouts"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="currency_iso_code",
        ),
        CheckConstraint(
            "status NOT IN ('approved', 'processing', 'paid') "
            "OR (approved_by_user_id IS NOT NULL AND approved_at IS NOT NULL)",
            name="financial_status_requires_human_approval",
        ),
        CheckConstraint(
            "status != 'paid' OR paid_at IS NOT NULL", name="paid_at_required"
        ),
        UniqueConstraint("vendor_id", "id", name="uq_payouts_vendor_id_id"),
        Index(
            "ix_payouts_vendor_status_created",
            "vendor_id",
            "status",
            "created_at",
        ),
    )

    vendor_id: Mapped[UUID] = mapped_column(
        ForeignKey("vendors.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    requested_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    approved_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    paypal_batch_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        unique=True,
    )
    status: Mapped[PayoutStatus] = mapped_column(
        Enum(
            PayoutStatus,
            name="payout_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda values: [member.value for member in values],
        ),
        nullable=False,
        default=PayoutStatus.PENDING_APPROVAL,
        index=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    reference: Mapped[str | None] = mapped_column(String(256), nullable=True)

    vendor: Mapped[Vendor] = relationship(back_populates="payouts")
    requested_by: Mapped[User] = relationship(foreign_keys=[requested_by_user_id])
    approved_by: Mapped[User | None] = relationship(foreign_keys=[approved_by_user_id])
    decisions: Mapped[list[Decision]] = relationship(
        back_populates="payout",
        viewonly=True,
    )
