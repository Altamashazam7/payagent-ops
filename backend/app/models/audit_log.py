"""Append-oriented audit log model."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, Enum, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.types import JSONValue
from app.db.base import BaseModel
from app.models.enums import AuditEntityType

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.user import User
    from app.models.vendor import Vendor


class AuditLog(BaseModel):
    """Audit record with a polymorphic subject and explicit actor references."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint(
            "actor_user_id IS NULL OR agent_id IS NULL",
            name="at_most_one_actor",
        ),
        Index("ix_audit_logs_entity_created", "entity_type", "entity_id", "created_at"),
        Index("ix_audit_logs_vendor_created", "vendor_id", "created_at"),
        Index("ix_audit_logs_actor_created", "actor_user_id", "created_at"),
        Index(
            "uq_audit_logs_entity_action_request",
            "entity_type",
            "entity_id",
            "action",
            "request_id",
            unique=True,
        ),
    )

    entity_type: Mapped[AuditEntityType] = mapped_column(
        Enum(
            AuditEntityType,
            name="audit_entity_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda values: [member.value for member in values],
        ),
        nullable=False,
    )
    entity_id: Mapped[UUID] = mapped_column(nullable=False)
    vendor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("vendors.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    agent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    before_state: Mapped[dict[str, JSONValue] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    after_state: Mapped[dict[str, JSONValue] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    vendor: Mapped[Vendor | None] = relationship()
    actor_user: Mapped[User | None] = relationship()
    agent: Mapped[Agent | None] = relationship()
