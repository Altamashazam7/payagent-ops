"""Payment transaction model."""

from __future__ import annotations

from datetime import UTC, datetime
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
from app.models.enums import TransactionStatus
from app.models.mixins import MonetaryFieldsMixin

if TYPE_CHECKING:
    from app.models.decision import Decision
    from app.models.dispute import Dispute
    from app.models.invoice import Invoice
    from app.models.vendor import Vendor


class Transaction(MonetaryFieldsMixin, BaseModel):
    """Provider-reported transaction; amounts are stored without float rounding."""

    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="currency_iso_code",
        ),
        UniqueConstraint(
            "vendor_id",
            "id",
            name="uq_transactions_vendor_id_id",
        ),
        UniqueConstraint(
            "vendor_id",
            "paypal_transaction_id",
            name="uq_transactions_vendor_paypal_id",
        ),
        Index("ix_transactions_vendor_created_at", "vendor_id", "created_at"),
        Index(
            "ix_transactions_vendor_status_created", "vendor_id", "status", "created_at"
        ),
    )

    vendor_id: Mapped[UUID] = mapped_column(
        ForeignKey("vendors.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    paypal_transaction_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    paypal_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    paypal_capture_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[TransactionStatus] = mapped_column(
        Enum(
            TransactionStatus,
            name="transaction_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda values: [member.value for member in values],
        ),
        nullable=False,
        default=TransactionStatus.PENDING,
        index=True,
    )
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )

    vendor: Mapped[Vendor] = relationship(back_populates="transactions")
    disputes: Mapped[list[Dispute]] = relationship(
        back_populates="transaction",
        viewonly=True,
    )
    invoice: Mapped[Invoice | None] = relationship(
        back_populates="transaction",
        viewonly=True,
    )
    decisions: Mapped[list[Decision]] = relationship(
        back_populates="transaction",
        viewonly=True,
    )
