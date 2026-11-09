"""Reusable commerce model columns."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column


class SoftDeleteMixin:
    """Track logical deletion without erasing retained commerce records."""

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        index=True,
    )
    deleted_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    def mark_deleted(self, actor_user_id: UUID | None = None) -> None:
        """Mark this entity deleted once and record the responsible operator."""
        if self.deleted_at is None:
            self.deleted_at = datetime.now(UTC)
            self.deleted_by_user_id = actor_user_id


class MonetaryFieldsMixin:
    """Shared exact-precision amount and ISO currency fields."""

    amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
