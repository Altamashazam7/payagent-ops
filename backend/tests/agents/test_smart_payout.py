"""Smart payout scoring, persisted approval, and PayPal integration tests."""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import httpx2
import pytest
from openai import AsyncOpenAI
from pydantic import SecretStr
from sqlalchemy import select, text

from app.agents.payout.narrative import OpenAIPayoutNarrativeGenerator
from app.agents.payout.prompts import (
    PAYOUT_ANALYSIS_SYSTEM_PROMPT,
    build_payout_analysis_prompt,
)
from app.agents.payout.service import SmartPayoutService
from app.core.settings import Settings
from app.db.base import Base
from app.db.session import Database
from app.integrations.paypal import (
    PayPalClients,
    PayPalTransientError,
    create_paypal_clients,
)
from app.models.audit_log import AuditLog
from app.models.decision import Decision
from app.models.enums import (
    AuditEntityType,
    DecisionStatus,
    PayoutRecipientType,
    PayoutStatus,
    UserRole,
    UserStatus,
    VendorStatus,
)
from app.models.payout import Payout
from app.models.user import User
from app.models.vendor import Vendor
from app.schemas.commerce import PayoutCreate
from app.schemas.smart_payout import (
    PayoutDecisionApproval,
    PayoutRiskAssessment,
)


@pytest.fixture
async def payout_database() -> AsyncIterator[Database]:
    database = Database(SecretStr("sqlite+aiosqlite:///:memory:"))
    async with database.engine.begin() as connection:
        await connection.execute(text("PRAGMA foreign_keys=ON"))
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield database
    finally:
        await database.dispose()


class MockPayoutNarrative:
    async def generate(self, assessment: PayoutRiskAssessment) -> str:
        assert assessment.payout_id
        return "Review the payout eligibility findings before submission."


def build_paypal_clients(
    *,
    transient_failures: int = 0,
    always_fail: bool = False,
) -> tuple[httpx.AsyncClient, PayPalClients, list[httpx.Request]]:
    payout_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "payout-test-token",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                },
            )
        if request.url.path == "/v1/payments/payouts":
            payout_requests.append(request)
            if always_fail or len(payout_requests) <= transient_failures:
                return httpx.Response(
                    503,
                    json={"name": "INTERNAL_SERVER_ERROR", "message": "retry"},
                )
            return httpx.Response(
                201,
                json={
                    "payout_batch_id": "PAYPAL-BATCH-42",
                    "batch_status": "PENDING",
                },
            )
        raise AssertionError(f"Unexpected PayPal request path: {request.url.path}")

    settings = Settings(
        environment="test",
        database_url=SecretStr("sqlite+aiosqlite:///:memory:"),
        paypal_client_id=SecretStr("test-client"),
        paypal_client_secret=SecretStr("test-secret"),
        paypal_retry_attempts=2,
        paypal_retry_min_wait_seconds=0,
        paypal_retry_max_wait_seconds=0.1,
    )
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url=settings.paypal_api_base_url,
    )
    return (
        http_client,
        create_paypal_clients(settings, http_client=http_client),
        payout_requests,
    )


async def seed_payout(
    database: Database,
    *,
    recipient: str | None = "payee@example.com",
    recipient_type: PayoutRecipientType | None = PayoutRecipientType.EMAIL,
    amount: Decimal = Decimal("125.00"),
    vendor_status: VendorStatus = VendorStatus.ACTIVE,
    add_history: bool = False,
    duplicate: bool = False,
    existing_batch_id: str | None = None,
) -> tuple[UUID, UUID, UUID]:
    async with database.session_factory.begin() as session:
        operator = User(
            email="payout-operator@example.com",
            display_name="Payout Operator",
            role=UserRole.OPERATOR,
            status=UserStatus.ACTIVE,
        )
        session.add(operator)
        await session.flush()
        vendor = Vendor(
            owner_user_id=operator.id,
            name="Payout Vendor",
            status=vendor_status,
        )
        session.add(vendor)
        await session.flush()
        payout = Payout(
            vendor_id=vendor.id,
            requested_by_user_id=operator.id,
            amount=amount,
            currency="USD",
            reference="monthly-settlement",
            paypal_receiver=recipient,
            paypal_recipient_type=recipient_type,
            paypal_batch_id=existing_batch_id,
        )
        session.add(payout)
        await session.flush()
        if duplicate:
            session.add(
                Payout(
                    vendor_id=vendor.id,
                    requested_by_user_id=operator.id,
                    amount=amount,
                    currency="USD",
                    paypal_receiver=recipient,
                    paypal_recipient_type=recipient_type,
                )
            )
        if add_history:
            for index, past_amount in enumerate(
                (Decimal("100.00"), Decimal("110.00"), Decimal("120.00")),
                start=1,
            ):
                session.add(
                    Payout(
                        vendor_id=vendor.id,
                        requested_by_user_id=operator.id,
                        approved_by_user_id=operator.id,
                        amount=past_amount,
                        currency="USD",
                        status=PayoutStatus.PAID,
                        approved_at=datetime.now(UTC) - timedelta(days=index + 1),
                        paid_at=datetime.now(UTC) - timedelta(days=index),
                        paypal_batch_id=f"HISTORY-{index}-{uuid4().hex[:8]}",
                        paypal_receiver="history@example.com",
                        paypal_recipient_type=PayoutRecipientType.EMAIL,
                    )
                )
        return operator.id, vendor.id, payout.id


async def test_payout_review_is_recommendation_only_until_approval(
    payout_database: Database,
) -> None:
    reviewer_id, _, payout_id = await seed_payout(payout_database)
    http_client, clients, requests = build_paypal_clients()
    try:
        async with payout_database.session_factory() as session:
            service = SmartPayoutService(session, clients, MockPayoutNarrative())
            result = await service.review(payout_id)
            assert result.recommendation == "create_payout_batch"
            assert result.workflow_status == "awaiting_human_approval"
            assert requests == []

            submitted = await service.approve_and_submit(
                PayoutDecisionApproval(
                    decision_id=result.decision_id,
                    reviewer_user_id=reviewer_id,
                )
            )
            assert submitted.workflow_status == "submitted"
            assert submitted.paypal_batch_id == "PAYPAL-BATCH-42"
            assert len(requests) == 1
            assert requests[0].headers["PayPal-Request-Id"]
            payload = json.loads(requests[0].read())
            assert payload["items"][0]["receiver"] == "payee@example.com"
            assert payload["items"][0]["amount"] == {
                "currency_code": "USD",
                "value": "125.0000",
            }

            decision = await session.get(Decision, result.decision_id)
            payout = await session.get(Payout, payout_id)
            assert decision is not None
            assert decision.status is DecisionStatus.APPROVED
            assert payout is not None
            assert payout.status is PayoutStatus.PROCESSING
            assert payout.paypal_batch_id == "PAYPAL-BATCH-42"
            audit = list((await session.scalars(select(AuditLog))).all())
            assert {
                "smart_payout_assessed",
                "smart_payout_approved",
                "payout_approved",
                "payout_submission_started",
                "payout_batch_submitted",
            }.issubset({entry.action for entry in audit})
            assert all(
                isinstance(entry.entity_type, AuditEntityType) for entry in audit
            )
    finally:
        await clients.aclose()
        await http_client.aclose()


async def test_payout_client_retries_with_same_idempotency_key(
    payout_database: Database,
) -> None:
    reviewer_id, _, payout_id = await seed_payout(payout_database)
    http_client, clients, requests = build_paypal_clients(transient_failures=1)
    try:
        async with payout_database.session_factory() as session:
            service = SmartPayoutService(session, clients, MockPayoutNarrative())
            result = await service.review(payout_id)
            submitted = await service.approve_and_submit(
                PayoutDecisionApproval(
                    decision_id=result.decision_id,
                    reviewer_user_id=reviewer_id,
                )
            )
        assert submitted.workflow_status == "submitted"
        assert len(requests) == 2
        assert (
            requests[0].headers["PayPal-Request-Id"]
            == requests[1].headers["PayPal-Request-Id"]
        )
    finally:
        await clients.aclose()
        await http_client.aclose()


async def test_missing_recipient_blocks_human_approval_and_submission(
    payout_database: Database,
) -> None:
    reviewer_id, _, payout_id = await seed_payout(
        payout_database,
        recipient=None,
        recipient_type=None,
    )
    http_client, clients, requests = build_paypal_clients()
    try:
        async with payout_database.session_factory() as session:
            service = SmartPayoutService(session, clients, MockPayoutNarrative())
            result = await service.review(payout_id)
            assert result.recommendation == "manual_review"
            with pytest.raises(ValueError, match="not eligible for payout approval"):
                await service.approve_and_submit(
                    PayoutDecisionApproval(
                        decision_id=result.decision_id,
                        reviewer_user_id=reviewer_id,
                    )
                )
            assert requests == []
    finally:
        await clients.aclose()
        await http_client.aclose()


async def test_duplicate_payout_is_manual_review_only(
    payout_database: Database,
) -> None:
    _, _, payout_id = await seed_payout(payout_database, duplicate=True)
    http_client, clients, requests = build_paypal_clients()
    try:
        async with payout_database.session_factory() as session:
            result = await SmartPayoutService(
                session,
                clients,
                MockPayoutNarrative(),
            ).review(payout_id)
        assert result.recommendation == "manual_review"
        assert any(
            finding.code == "possible_duplicate"
            for finding in result.assessment.findings
        )
        assert requests == []
    finally:
        await clients.aclose()
        await http_client.aclose()


async def test_existing_paypal_batch_blocks_duplicate_submission(
    payout_database: Database,
) -> None:
    _, _, payout_id = await seed_payout(
        payout_database,
        existing_batch_id="PREEXISTING-BATCH",
    )
    http_client, clients, requests = build_paypal_clients()
    try:
        async with payout_database.session_factory() as session:
            result = await SmartPayoutService(
                session,
                clients,
                MockPayoutNarrative(),
            ).review(payout_id)
        assert result.recommendation == "manual_review"
        assert any(
            finding.code == "already_has_paypal_batch"
            for finding in result.assessment.findings
        )
        assert requests == []
    finally:
        await clients.aclose()
        await http_client.aclose()


async def test_outlier_payout_requires_manual_review(
    payout_database: Database,
) -> None:
    _, _, payout_id = await seed_payout(
        payout_database,
        amount=Decimal("1000.00"),
        add_history=True,
    )
    http_client, clients, requests = build_paypal_clients()
    try:
        async with payout_database.session_factory() as session:
            result = await SmartPayoutService(
                session,
                clients,
                MockPayoutNarrative(),
            ).review(payout_id)
        assert result.recommendation == "manual_review"
        assert result.assessment.historical_sample_count == 3
        assert any(
            finding.code == "amount_outlier" for finding in result.assessment.findings
        )
        assert requests == []
    finally:
        await clients.aclose()
        await http_client.aclose()


async def test_payout_review_rejects_stale_recipient_or_amount(
    payout_database: Database,
) -> None:
    reviewer_id, _, payout_id = await seed_payout(payout_database)
    http_client, clients, requests = build_paypal_clients()
    try:
        async with payout_database.session_factory() as session:
            service = SmartPayoutService(session, clients, MockPayoutNarrative())
            result = await service.review(payout_id)
            async with payout_database.session_factory.begin() as writer:
                payout = await writer.get(Payout, payout_id)
                assert payout is not None
                payout.amount = Decimal("250.00")
            with pytest.raises(ValueError, match="changed after assessment"):
                await service.approve_and_submit(
                    PayoutDecisionApproval(
                        decision_id=result.decision_id,
                        reviewer_user_id=reviewer_id,
                    )
                )
        assert requests == []
    finally:
        await clients.aclose()
        await http_client.aclose()


async def test_paypal_failure_is_audited_and_submission_is_one_shot(
    payout_database: Database,
) -> None:
    reviewer_id, _, payout_id = await seed_payout(payout_database)
    http_client, clients, requests = build_paypal_clients(always_fail=True)
    try:
        async with payout_database.session_factory() as session:
            service = SmartPayoutService(session, clients, MockPayoutNarrative())
            result = await service.review(payout_id)
            approval = PayoutDecisionApproval(
                decision_id=result.decision_id,
                reviewer_user_id=reviewer_id,
            )
            with pytest.raises(PayPalTransientError):
                await service.approve_and_submit(approval)
            with pytest.raises(ValueError, match="already attempted"):
                await service.approve_and_submit(approval)
            audit = list((await session.scalars(select(AuditLog))).all())
            assert any(item.action == "payout_submission_failed" for item in audit)
        assert len(requests) == 2
    finally:
        await clients.aclose()
        await http_client.aclose()


async def test_viewer_cannot_approve_payout(
    payout_database: Database,
) -> None:
    _, _, payout_id = await seed_payout(payout_database)
    async with payout_database.session_factory.begin() as session:
        viewer = User(
            email="payout-viewer@example.com",
            display_name="Payout Viewer",
            role=UserRole.VIEWER,
            status=UserStatus.ACTIVE,
        )
        session.add(viewer)
        await session.flush()
        viewer_id = viewer.id
    http_client, clients, requests = build_paypal_clients()
    try:
        async with payout_database.session_factory() as session:
            service = SmartPayoutService(session, clients, MockPayoutNarrative())
            result = await service.review(payout_id)
            with pytest.raises(ValueError, match="active admin or operator"):
                await service.approve_and_submit(
                    PayoutDecisionApproval(
                        decision_id=result.decision_id,
                        reviewer_user_id=viewer_id,
                    )
                )
            decision = await session.get(Decision, result.decision_id)
            payout = await session.get(Payout, payout_id)
            assert decision is not None
            assert decision.status is DecisionStatus.PENDING
            assert payout is not None
            assert payout.status is PayoutStatus.PENDING_APPROVAL
            assert requests == []
    finally:
        await clients.aclose()
        await http_client.aclose()


def test_payout_prompt_has_no_recipient_address() -> None:
    assessment = PayoutRiskAssessment(
        payout_id=UUID("3a91770d-2f28-447a-b464-1fc30a261303"),
        eligibility_score=Decimal("0.750"),
        historical_sample_count=0,
        findings=[],
        recommendation="create_payout_batch",
    )

    prompt = build_payout_analysis_prompt(assessment)

    assert "payee@example.com" not in prompt
    assert "recipient" not in prompt
    assert "human approval" in PAYOUT_ANALYSIS_SYSTEM_PROMPT


def test_payout_recipient_fields_are_optional_but_must_be_validated_together() -> None:
    base = {
        "vendor_id": UUID("3a91770d-2f28-447a-b464-1fc30a261303"),
        "requested_by_user_id": UUID("f48ec39c-41e7-48f1-a0ad-fdb2456fdd21"),
        "amount": Decimal("12.50"),
        "currency": "USD",
    }

    assert PayoutCreate.model_validate(base).paypal_receiver is None
    with pytest.raises(ValueError, match="provided together"):
        PayoutCreate.model_validate({**base, "paypal_receiver": "payee@example.com"})
    with pytest.raises(ValueError, match="E.164"):
        PayoutCreate.model_validate(
            {
                **base,
                "paypal_receiver": "555-0100",
                "paypal_recipient_type": PayoutRecipientType.PHONE,
            }
        )
    assert (
        PayoutCreate.model_validate(
            {
                **base,
                "paypal_receiver": "payee@example.com",
                "paypal_recipient_type": PayoutRecipientType.EMAIL,
            }
        ).paypal_receiver
        == "payee@example.com"
    )


async def test_openai_payout_narrative_uses_async_client() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        payload = json.loads(request.read())
        assert "payee@example.com" not in json.dumps(payload)
        return httpx2.Response(
            200,
            json={
                "id": "chatcmpl-payout",
                "object": "chat.completion",
                "created": 1,
                "model": "gpt-4.1-mini",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": "Review the payout findings.",
                        },
                    }
                ],
            },
        )

    assessment = PayoutRiskAssessment(
        payout_id=UUID("3a91770d-2f28-447a-b464-1fc30a261303"),
        eligibility_score=Decimal("0.750"),
        historical_sample_count=0,
        findings=[],
        recommendation="create_payout_batch",
    )
    transport = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    client = AsyncOpenAI(
        api_key="test-key",
        base_url="https://openai.example.test/v1",
        http_client=transport,
        max_retries=0,
    )
    generator = OpenAIPayoutNarrativeGenerator(client, model="gpt-4.1-mini")
    try:
        assert await generator.generate(assessment) == "Review the payout findings."
    finally:
        await generator.aclose()
