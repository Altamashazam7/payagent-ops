"""add optional PayPal payout recipient data

Revision ID: a61c4b8e3f20
Revises: c720bbcf5821
Create Date: 2026-11-09 16:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a61c4b8e3f20"
down_revision: str | None = "c720bbcf5821"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("payouts") as batch_op:
        batch_op.add_column(sa.Column("paypal_receiver", sa.String(length=127)))
        batch_op.add_column(sa.Column("paypal_recipient_type", sa.String(length=16)))
        batch_op.create_check_constraint(
            "ck_payouts_payout_recipient_type",
            "paypal_recipient_type IS NULL OR paypal_recipient_type IN "
            "('EMAIL', 'PHONE', 'PAYPAL_ID')",
        )
        batch_op.create_check_constraint(
            "ck_payouts_paypal_receiver_pair",
            "(paypal_receiver IS NULL AND paypal_recipient_type IS NULL) OR "
            "(paypal_receiver IS NOT NULL AND paypal_recipient_type IS NOT NULL)",
        )
    op.create_index(
        "ix_invoices_vendor_invoice_number_normalized",
        "invoices",
        ["vendor_id", sa.text("lower(trim(invoice_number))")],
        unique=False,
    )
    op.create_index(
        "ix_invoices_vendor_compliance_fingerprint",
        "invoices",
        [
            "vendor_id",
            "amount",
            "currency",
            "due_at",
            sa.text("lower(trim(billing_email))"),
        ],
        unique=False,
    )
    op.create_index(
        "ix_payouts_vendor_created",
        "payouts",
        ["vendor_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_payouts_vendor_created", table_name="payouts")
    op.drop_index(
        "ix_invoices_vendor_compliance_fingerprint",
        table_name="invoices",
    )
    op.drop_index(
        "ix_invoices_vendor_invoice_number_normalized",
        table_name="invoices",
    )
    with op.batch_alter_table("payouts") as batch_op:
        batch_op.drop_constraint("ck_payouts_paypal_receiver_pair", type_="check")
        batch_op.drop_constraint("ck_payouts_payout_recipient_type", type_="check")
        batch_op.drop_column("paypal_recipient_type")
        batch_op.drop_column("paypal_receiver")
