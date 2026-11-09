"""Payment dispute model."""

from __future__ import annotations

from datetime import UTC, datetime
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
from app.models.enums import DisputeStatus
from app.models.mixins import MonetaryFieldsMixin

if TYPE_CHECKING:
    from app.models.decision import Decision
    from app.models.transaction import Transaction
    from app.models.vendor import Vendor


class Dispute(MonetaryFieldsMixin, BaseModel):
    """Dispute with vendor scope constrained to its originating transaction."""

    __tablename__ = "disputes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["vendor_id", "transaction_id"],
            ["transactions.vendor_id", "transactions.id"],
            name="fk_disputes_vendor_transaction",
            ondelete="RESTRICT",
        ),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="currency_iso_code",
        ),
        UniqueConstraint("vendor_id", "id", name="uq_disputes_vendor_id_id"),
        UniqueConstraint(
            "vendor_id",
            "external_dispute_id",
            name="uq_disputes_vendor_external_id",
        ),
        CheckConstraint(
            "status NOT IN ('won', 'lost', 'closed') OR resolved_at IS NOT NULL",
            name="resolved_status_requires_timestamp",
        ),
        Index(
            "ix_disputes_vendor_status_due",
            "vendor_id",
            "status",
            "response_due_at",
        ),
    )

    vendor_id: Mapped[UUID] = mapped_column(
        ForeignKey("vendors.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    transaction_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    external_dispute_id: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[DisputeStatus] = mapped_column(
        Enum(
            DisputeStatus,
            name="dispute_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda values: [member.value for member in values],
        ),
        nullable=False,
        default=DisputeStatus.NEEDS_RESPONSE,
        index=True,
    )
    response_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    evidence_reference: Mapped[str | None] = mapped_column(String(512), nullable=True)

    vendor: Mapped[Vendor] = relationship(back_populates="disputes")
    transaction: Mapped[Transaction] = relationship(
        back_populates="disputes",
        viewonly=True,
    )
    decisions: Mapped[list[Decision]] = relationship(
        back_populates="dispute",
        viewonly=True,
    )
