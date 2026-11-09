"""Pydantic schema validation tests for commerce domain inputs."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.enums import AuditEntityType, PayoutStatus
from app.schemas.commerce import (
    AuditLogCreate,
    DecisionCreate,
    PayoutCreate,
    TransactionCreate,
    UserCreate,
)


def test_email_and_currency_inputs_are_normalized() -> None:
    user = UserCreate(email="  OPS@Example.com ", display_name=" Operator ")
    transaction = TransactionCreate(
        vendor_id=uuid4(),
        amount=Decimal("12.3400"),
        currency="usd",
    )

    assert user.email == "ops@example.com"
    assert user.display_name == "Operator"
    assert transaction.currency == "USD"


@pytest.mark.parametrize("amount", [Decimal(0), Decimal(-1)])
def test_transaction_schema_rejects_non_positive_amount(amount: Decimal) -> None:
    with pytest.raises(ValidationError):
        TransactionCreate(vendor_id=uuid4(), amount=amount, currency="USD")


def test_decision_schema_requires_exactly_one_subject() -> None:
    with pytest.raises(ValidationError, match="exactly one commerce record"):
        DecisionCreate(
            vendor_id=uuid4(),
            action_type="review",
            recommendation="Review this transaction",
        )

    with pytest.raises(ValidationError, match="exactly one commerce record"):
        DecisionCreate(
            vendor_id=uuid4(),
            transaction_id=uuid4(),
            payout_id=uuid4(),
            action_type="review",
            recommendation="Review this transaction",
        )


def test_payout_input_cannot_set_approval_status() -> None:
    with pytest.raises(ValidationError):
        PayoutCreate.model_validate(
            {
                "vendor_id": uuid4(),
                "requested_by_user_id": uuid4(),
                "amount": Decimal(25),
                "currency": "USD",
                "status": PayoutStatus.APPROVED,
            }
        )


def test_audit_schema_rejects_conflicting_actor_identity() -> None:
    with pytest.raises(ValidationError, match="both a user and agent"):
        AuditLogCreate(
            entity_type=AuditEntityType.TRANSACTION,
            entity_id=uuid4(),
            actor_user_id=uuid4(),
            agent_id=uuid4(),
            action="transaction.reviewed",
        )


def test_audit_schema_rejects_non_json_snapshot_values() -> None:
    with pytest.raises(ValidationError):
        AuditLogCreate.model_validate(
            {
                "entity_type": AuditEntityType.TRANSACTION,
                "entity_id": uuid4(),
                "action": "transaction.reviewed",
                "after_state": {"occurred_at": datetime.now(UTC)},
            }
        )
