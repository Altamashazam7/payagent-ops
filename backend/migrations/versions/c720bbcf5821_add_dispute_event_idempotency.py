"""add dispute webhook event idempotency

Revision ID: c720bbcf5821
Revises: b5535b020fdd
Create Date: 2026-11-09 16:20:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c720bbcf5821"
down_revision: str | None = "b5535b020fdd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_audit_logs_entity_action_request",
        "audit_logs",
        ["entity_type", "entity_id", "action", "request_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_audit_logs_entity_action_request",
        table_name="audit_logs",
    )
