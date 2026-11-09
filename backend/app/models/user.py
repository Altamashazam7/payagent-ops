"""Commerce operator account model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel
from app.models.enums import UserRole, UserStatus
from app.models.mixins import SoftDeleteMixin

if TYPE_CHECKING:
    from app.models.vendor import Vendor


class User(SoftDeleteMixin, BaseModel):
    """Human operator account; credentials are managed outside this domain."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(
            UserRole,
            name="user_role",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda values: [member.value for member in values],
        ),
        nullable=False,
        default=UserRole.OPERATOR,
    )
    status: Mapped[UserStatus] = mapped_column(
        Enum(
            UserStatus,
            name="user_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda values: [member.value for member in values],
        ),
        nullable=False,
        default=UserStatus.INVITED,
        index=True,
    )

    vendors: Mapped[list[Vendor]] = relationship(
        back_populates="owner",
        foreign_keys="Vendor.owner_user_id",
    )
