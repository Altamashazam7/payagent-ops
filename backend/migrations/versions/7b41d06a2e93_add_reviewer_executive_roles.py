"""add reviewer and executive user roles

Revision ID: 7b41d06a2e93
Revises: a61c4b8e3f20
Create Date: 2026-11-09 16:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7b41d06a2e93"
down_revision: str | None = "a61c4b8e3f20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint(op.f("ck_users_user_role"), type_="check")
        batch_op.create_check_constraint(
            op.f("ck_users_user_role"),
            "role IN ('admin', 'operator', 'reviewer', 'executive', 'viewer')",
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint(op.f("ck_users_user_role"), type_="check")
    op.execute(
        sa.text(
            "UPDATE users SET role = 'viewer' WHERE role IN ('reviewer', 'executive')"
        )
    )
    with op.batch_alter_table("users") as batch_op:
        batch_op.create_check_constraint(
            op.f("ck_users_user_role"),
            "role IN ('admin', 'operator', 'viewer')",
        )
