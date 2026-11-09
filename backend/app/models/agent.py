"""AI or automation agent registration model."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel
from app.models.enums import AgentStatus
from app.models.mixins import SoftDeleteMixin

if TYPE_CHECKING:
    from app.models.decision import Decision
    from app.models.vendor import Vendor


class Agent(SoftDeleteMixin, BaseModel):
    """Registered agent identity; no credentials or financial authority are stored."""

    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("vendor_id", "name", name="uq_agents_vendor_name"),
        Index("ix_agents_vendor_status", "vendor_id", "status"),
    )

    vendor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("vendors.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    agent_type: Mapped[str] = mapped_column(String(80), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[AgentStatus] = mapped_column(
        Enum(
            AgentStatus,
            name="agent_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda values: [member.value for member in values],
        ),
        nullable=False,
        default=AgentStatus.DRAFT,
        index=True,
    )

    vendor: Mapped[Vendor | None] = relationship(back_populates="agents")
    decisions: Mapped[list[Decision]] = relationship(back_populates="agent")
