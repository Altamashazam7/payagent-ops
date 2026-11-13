"""widen user role column for executive

Revision ID: 91dc2b8a610f
Revises: 7b41d06a2e93
Create Date: 2026-11-11 06:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "91dc2b8a610f"
down_revision: str | None = "7b41d06a2e93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "role",
        existing_type=sa.String(length=8),
        type_=sa.String(length=9),
        existing_nullable=False,
    )


def downgrade() -> None:
    has_executive = op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM users WHERE role = 'executive')")
    )
    if has_executive:
        raise RuntimeError(
            "Cannot narrow users.role while executive accounts exist"
        )
    op.alter_column(
        "users",
        "role",
        existing_type=sa.String(length=9),
        type_=sa.String(length=8),
        existing_nullable=False,
    )
