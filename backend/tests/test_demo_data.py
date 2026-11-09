"""Safety checks for the deterministic demo-data generator."""

from datetime import UTC, datetime

from app.demo_data.generator import DEMO_OWNER_ID, build_demo_dataset
from app.models.enums import DecisionStatus, PayoutStatus, UserRole, VendorStatus


def test_demo_dataset_is_deterministic_and_contains_only_pending_actions() -> None:
    now = datetime(2026, 11, 9, tzinfo=UTC)
    first = build_demo_dataset(now=now)
    second = build_demo_dataset(now=now)

    assert first.users[0].id == DEMO_OWNER_ID
    assert first.users[0].email.endswith(".invalid")
    assert first.users[0].role is UserRole.ADMIN
    assert [vendor.id for vendor in first.vendors] == [
        vendor.id for vendor in second.vendors
    ]
    assert len(first.transactions) == 80
    assert len(first.disputes) == 8
    assert len(first.invoices) == 12
    assert len(first.payouts) == 8
    assert len(first.decisions) == 8
    assert all(vendor.status is VendorStatus.ACTIVE for vendor in first.vendors)
    assert all(
        payout.status is PayoutStatus.PENDING_APPROVAL
        and payout.approved_by_user_id is None
        and payout.paid_at is None
        and payout.paypal_batch_id is None
        for payout in first.payouts
    )
    assert all(
        decision.status is DecisionStatus.PENDING for decision in first.decisions
    )
    assert all(audit.after_state == {"synthetic": True} for audit in first.audit_logs)


def test_demo_generator_rejects_naive_clock() -> None:
    try:
        build_demo_dataset(now=datetime(2026, 11, 9))
    except ValueError as exc:
        assert "timezone" in str(exc)
    else:
        raise AssertionError("naive timestamps must be rejected")
