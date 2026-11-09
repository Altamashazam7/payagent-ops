"""Vendor invoice model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel
from app.models.enums import InvoiceStatus
from app.models.mixins import MonetaryFieldsMixin

if TYPE_CHECKING:
    from app.models.decision import Decision
    from app.models.transaction import Transaction
    from app.models.vendor import Vendor


class Invoice(MonetaryFieldsMixin, BaseModel):
    """Invoice retained for reconciliation and revenue-leakage analysis."""

    __tablename__ = "invoices"
    __table_args__ = (
        ForeignKeyConstraint(
            ["vendor_id", "transaction_id"],
            ["transactions.vendor_id", "transactions.id"],
            name="fk_invoices_vendor_transaction",
            ondelete="RESTRICT",
        ),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="currency_iso_code",
        ),
        CheckConstraint(
            "status != 'paid' OR paid_at IS NOT NULL",
            name="paid_status_requires_timestamp",
        ),
        UniqueConstraint(
            "vendor_id",
            "invoice_number",
            name="uq_invoices_vendor_invoice_number",
        ),
        UniqueConstraint("vendor_id", "id", name="uq_invoices_vendor_id_id"),
        UniqueConstraint("transaction_id", name="uq_invoices_transaction_id"),
        Index("ix_invoices_vendor_status_due", "vendor_id", "status", "due_at"),
    )

    vendor_id: Mapped[UUID] = mapped_column(
        ForeignKey("vendors.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    transaction_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    invoice_number: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[InvoiceStatus] = mapped_column(
        Enum(
            InvoiceStatus,
            name="invoice_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda values: [member.value for member in values],
        ),
        nullable=False,
        default=InvoiceStatus.DRAFT,
        index=True,
    )
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    billing_email: Mapped[str | None] = mapped_column(String(320), nullable=True)

    vendor: Mapped[Vendor] = relationship(back_populates="invoices")
    transaction: Mapped[Transaction | None] = relationship(
        back_populates="invoice",
        viewonly=True,
    )
    decisions: Mapped[list[Decision]] = relationship(
        back_populates="invoice",
        viewonly=True,
    )
