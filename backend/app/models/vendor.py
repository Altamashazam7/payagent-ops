"""Merchant account that owns commerce records."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel
from app.models.enums import VendorStatus
from app.models.mixins import SoftDeleteMixin

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.decision import Decision
    from app.models.dispute import Dispute
    from app.models.invoice import Invoice
    from app.models.payout import Payout
    from app.models.transaction import Transaction
    from app.models.user import User


class Vendor(SoftDeleteMixin, BaseModel):
    """Vendor account and tenant boundary for payment operations."""

    __tablename__ = "vendors"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "name", name="uq_vendors_owner_name"),
    )

    owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    paypal_merchant_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        unique=True,
    )
    status: Mapped[VendorStatus] = mapped_column(
        Enum(
            VendorStatus,
            name="vendor_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda values: [member.value for member in values],
        ),
        nullable=False,
        default=VendorStatus.PENDING,
        index=True,
    )

    owner: Mapped[User] = relationship(
        back_populates="vendors",
        foreign_keys=[owner_user_id],
    )
    transactions: Mapped[list[Transaction]] = relationship(back_populates="vendor")
    disputes: Mapped[list[Dispute]] = relationship(back_populates="vendor")
    invoices: Mapped[list[Invoice]] = relationship(back_populates="vendor")
    payouts: Mapped[list[Payout]] = relationship(back_populates="vendor")
    agents: Mapped[list[Agent]] = relationship(back_populates="vendor")
    decisions: Mapped[list[Decision]] = relationship(back_populates="vendor")
