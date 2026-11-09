"""Invoice compliance scoring, workflow, privacy, and review tests."""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import httpx2
import pytest
from openai import AsyncOpenAI
from pydantic import SecretStr
from sqlalchemy import select, text

from app.agents.invoice.narrative import OpenAIInvoiceNarrativeGenerator
from app.agents.invoice.prompts import (
    INVOICE_COMPLIANCE_SYSTEM_PROMPT,
    build_invoice_compliance_prompt,
)
from app.agents.invoice.scoring import InvoiceComplianceScorer
from app.agents.invoice.service import InvoiceComplianceService
from app.db.base import Base
from app.db.session import Database
from app.models.audit_log import AuditLog
from app.models.decision import Decision
from app.models.enums import (
    AuditEntityType,
    DecisionStatus,
    InvoiceStatus,
    UserRole,
    UserStatus,
    VendorStatus,
)
from app.models.invoice import Invoice
from app.models.user import User
from app.models.vendor import Vendor
from app.schemas.commerce import InvoiceRead, VendorRead
from app.schemas.invoice_compliance import (
    InvoiceComplianceAssessment,
    InvoiceDecisionReview,
)


@pytest.fixture
async def invoice_database() -> AsyncIterator[Database]:
    database = Database(SecretStr("sqlite+aiosqlite:///:memory:"))
    async with database.engine.begin() as connection:
        await connection.execute(text("PRAGMA foreign_keys=ON"))
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield database
    finally:
        await database.dispose()


class MockInvoiceNarrative:
    async def generate(
        self,
        invoice: InvoiceRead,
        assessment: InvoiceComplianceAssessment,
    ) -> str:
        assert invoice.id == assessment.invoice_id
        return "The invoice is ready for human review."


async def seed_invoice(
    database: Database,
    *,
    invoice_number: str = "INV-042",
    status: InvoiceStatus = InvoiceStatus.SENT,
    due_at: datetime | None = None,
    billing_email: str | None = "billing@example.com",
) -> tuple[UUID, UUID, UUID]:
    async with database.session_factory.begin() as session:
        operator = User(
            email="invoice-operator@example.com",
            display_name="Invoice Operator",
            role=UserRole.OPERATOR,
            status=UserStatus.ACTIVE,
        )
        session.add(operator)
        await session.flush()
        vendor = Vendor(
            owner_user_id=operator.id,
            name="Invoice Vendor",
            status=VendorStatus.ACTIVE,
        )
        session.add(vendor)
        await session.flush()
        invoice = Invoice(
            vendor_id=vendor.id,
            created_by_user_id=operator.id,
            invoice_number=invoice_number,
            amount=Decimal("125.00"),
            currency="USD",
            status=status,
            due_at=due_at or datetime.now(UTC) + timedelta(days=14),
            billing_email=billing_email,
        )
        session.add(invoice)
        await session.flush()
        return operator.id, vendor.id, invoice.id


async def test_invoice_review_persists_pending_decision_without_changing_invoice(
    invoice_database: Database,
) -> None:
    reviewer_id, vendor_id, invoice_id = await seed_invoice(invoice_database)
    async with invoice_database.session_factory() as session:
        service = InvoiceComplianceService(session, MockInvoiceNarrative())
        result = await service.review(invoice_id)

        assert result.recommendation == "approve_invoice"
        assert result.workflow_status == "awaiting_human_approval"
        assert result.assessment.score == Decimal("1.000")
        decision = await session.get(Decision, result.decision_id)
        invoice = await session.get(Invoice, invoice_id)
        assert decision is not None
        assert decision.status is DecisionStatus.PENDING
        assert decision.invoice_id == invoice_id
        assert invoice is not None
        assert invoice.vendor_id == vendor_id
        assert invoice.status is InvoiceStatus.SENT
        audit = list((await session.scalars(select(AuditLog))).all())
        assert any(
            entry.action == "invoice_compliance_assessed"
            and entry.entity_type is AuditEntityType.DECISION
            for entry in audit
        )

        reviewed = await service.review_decision(
            InvoiceDecisionReview(
                decision_id=result.decision_id,
                reviewer_user_id=reviewer_id,
                approve=True,
            )
        )
        assert reviewed.workflow_status == "approved"
        decision = await session.get(Decision, result.decision_id)
        assert decision is not None
        assert decision.status is DecisionStatus.APPROVED
        assert decision.reviewed_by_user_id == reviewer_id


async def test_invoice_review_detects_case_normalized_duplicate(
    invoice_database: Database,
) -> None:
    _, vendor_id, invoice_id = await seed_invoice(invoice_database)
    async with invoice_database.session_factory.begin() as session:
        session.add(
            Invoice(
                vendor_id=vendor_id,
                invoice_number="inv-042",
                amount=Decimal("200.00"),
                currency="USD",
                status=InvoiceStatus.DRAFT,
            )
        )
    async with invoice_database.session_factory() as session:
        result = await InvoiceComplianceService(
            session,
            MockInvoiceNarrative(),
        ).review(invoice_id)
        assert result.recommendation == "manual_review"
        assert len(result.assessment.duplicate_invoice_ids) == 1
        assert any(
            finding.code == "possible_duplicate"
            for finding in result.assessment.findings
        )


async def test_invoice_review_requires_human_and_rejects_viewer(
    invoice_database: Database,
) -> None:
    _, _, invoice_id = await seed_invoice(invoice_database)
    async with invoice_database.session_factory.begin() as session:
        viewer = User(
            email="invoice-viewer@example.com",
            display_name="Invoice Viewer",
            role=UserRole.VIEWER,
            status=UserStatus.ACTIVE,
        )
        session.add(viewer)
        await session.flush()
        viewer_id = viewer.id
    async with invoice_database.session_factory() as session:
        service = InvoiceComplianceService(session, MockInvoiceNarrative())
        result = await service.review(invoice_id)
        with pytest.raises(ValueError, match="active admin or operator"):
            await service.review_decision(
                InvoiceDecisionReview(
                    decision_id=result.decision_id,
                    reviewer_user_id=viewer_id,
                    approve=True,
                )
            )
        decision = await session.get(Decision, result.decision_id)
        assert decision is not None
        assert decision.status is DecisionStatus.PENDING


async def test_invoice_review_rejects_stale_assessment(
    invoice_database: Database,
) -> None:
    reviewer_id, _, invoice_id = await seed_invoice(invoice_database)
    async with invoice_database.session_factory() as session:
        service = InvoiceComplianceService(session, MockInvoiceNarrative())
        result = await service.review(invoice_id)
        async with invoice_database.session_factory.begin() as writer:
            invoice = await writer.get(Invoice, invoice_id)
            assert invoice is not None
            invoice.status = InvoiceStatus.OVERDUE
        with pytest.raises(ValueError, match="changed after assessment"):
            await service.review_decision(
                InvoiceDecisionReview(
                    decision_id=result.decision_id,
                    reviewer_user_id=reviewer_id,
                    approve=True,
                )
            )
        decision = await session.get(Decision, result.decision_id)
        assert decision is not None
        assert decision.status is DecisionStatus.PENDING


def test_invoice_scorer_flags_incomplete_sent_invoice() -> None:
    invoice = InvoiceRead(
        id=UUID("3a91770d-2f28-447a-b464-1fc30a261303"),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        vendor_id=UUID("f48ec39c-41e7-48f1-a0ad-fdb2456fdd21"),
        transaction_id=None,
        created_by_user_id=None,
        invoice_number="INV-1",
        amount=Decimal("10.00"),
        currency="USD",
        status=InvoiceStatus.SENT,
        due_at=None,
        paid_at=None,
        description=None,
        billing_email=None,
    )
    vendor = VendorRead(
        id=invoice.vendor_id,
        created_at=invoice.created_at,
        updated_at=invoice.updated_at,
        owner_user_id=UUID("131fc1f8-a323-4ac2-810d-e440ae693595"),
        name="Active",
        paypal_merchant_id=None,
        status=VendorStatus.ACTIVE,
        deleted_at=None,
        deleted_by_user_id=None,
    )

    assessment = InvoiceComplianceScorer().score(invoice, vendor, [])

    assert assessment.recommendation == "manual_review"
    assert assessment.score == Decimal("0.600")
    assert {item.code for item in assessment.findings} == {
        "missing_billing_email",
        "missing_due_date",
    }


def test_invoice_prompt_omits_invoice_number_and_billing_email() -> None:
    invoice = InvoiceRead(
        id=UUID("3a91770d-2f28-447a-b464-1fc30a261303"),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        vendor_id=UUID("f48ec39c-41e7-48f1-a0ad-fdb2456fdd21"),
        transaction_id=None,
        created_by_user_id=None,
        invoice_number="PRIVATE-INVOICE-99",
        amount=Decimal("10.00"),
        currency="USD",
        status=InvoiceStatus.SENT,
        due_at=None,
        paid_at=None,
        description=None,
        billing_email="private@example.com",
    )
    assessment = InvoiceComplianceAssessment(
        invoice_id=invoice.id,
        score=Decimal("1.000"),
        duplicate_invoice_ids=[],
        findings=[],
        recommendation="approve_invoice",
    )

    prompt = build_invoice_compliance_prompt(invoice, assessment)

    assert "private@example.com" not in prompt
    assert "PRIVATE-INVOICE-99" not in prompt
    assert "billing_email_present" in prompt
    assert "untrusted data" in INVOICE_COMPLIANCE_SYSTEM_PROMPT


async def test_openai_invoice_narrative_uses_async_client() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        payload = json.loads(request.read())
        assert "billing@example.com" not in json.dumps(payload)
        return httpx2.Response(
            200,
            json={
                "id": "chatcmpl-invoice",
                "object": "chat.completion",
                "created": 1,
                "model": "gpt-4.1-mini",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": "Review the invoice findings.",
                        },
                    }
                ],
            },
        )

    now = datetime.now(UTC)
    invoice = InvoiceRead(
        id=UUID("3a91770d-2f28-447a-b464-1fc30a261303"),
        created_at=now,
        updated_at=now,
        vendor_id=UUID("f48ec39c-41e7-48f1-a0ad-fdb2456fdd21"),
        transaction_id=None,
        created_by_user_id=None,
        invoice_number="INV-9",
        amount=Decimal("10.00"),
        currency="USD",
        status=InvoiceStatus.SENT,
        due_at=None,
        paid_at=None,
        description=None,
        billing_email="billing@example.com",
    )
    assessment = InvoiceComplianceAssessment(
        invoice_id=invoice.id,
        score=Decimal("1.000"),
        duplicate_invoice_ids=[],
        findings=[],
        recommendation="approve_invoice",
    )
    transport = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    client = AsyncOpenAI(
        api_key="test-key",
        base_url="https://openai.example.test/v1",
        http_client=transport,
        max_retries=0,
    )
    generator = OpenAIInvoiceNarrativeGenerator(client, model="gpt-4.1-mini")
    try:
        assert await generator.generate(invoice, assessment) == (
            "Review the invoice findings."
        )
    finally:
        await generator.aclose()
