"""Persistence queries used by invoice compliance analysis and review."""

from uuid import UUID

from sqlalchemy import false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.agent import Agent
from app.models.audit_log import AuditLog
from app.models.decision import Decision
from app.models.enums import AgentStatus, AuditEntityType
from app.models.invoice import Invoice
from app.models.user import User
from app.models.vendor import Vendor

INVOICE_AGENT_NAME = "Invoice Compliance Agent"
INVOICE_AGENT_TYPE = "invoice_compliance"
MAX_DUPLICATE_CANDIDATES = 100


class InvoiceComplianceRepository:
    """Keep SQL details out of invoice-agent workflow and scoring logic."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_context(
        self,
        invoice_id: UUID,
        *,
        lock: bool = False,
    ) -> tuple[Invoice, Vendor] | None:
        statement = select(Invoice).where(Invoice.id == invoice_id)
        if lock:
            statement = statement.with_for_update()
        result = await self._session.scalars(statement)
        invoice = result.one_or_none()
        if invoice is None:
            return None
        vendor = await self._session.get(Vendor, invoice.vendor_id)
        if vendor is None:
            raise LookupError("Invoice vendor record is missing")
        return invoice, vendor

    async def list_duplicate_candidates(self, invoice: Invoice) -> list[Invoice]:
        normalized_number = " ".join(invoice.invoice_number.casefold().split())
        duplicate_number = func.lower(func.trim(Invoice.invoice_number)) == (
            normalized_number
        )
        matching_fingerprint: ColumnElement[bool] = false()
        if invoice.billing_email is not None and invoice.due_at is not None:
            matching_fingerprint = (
                (Invoice.amount == invoice.amount)
                & (Invoice.currency == invoice.currency)
                & (Invoice.due_at == invoice.due_at)
                & (
                    func.lower(func.trim(Invoice.billing_email))
                    == invoice.billing_email.strip().casefold()
                )
            )
        statement = (
            select(Invoice)
            .where(
                Invoice.vendor_id == invoice.vendor_id,
                Invoice.id != invoice.id,
                or_(duplicate_number, matching_fingerprint),
            )
            .order_by(Invoice.created_at.desc())
            .limit(MAX_DUPLICATE_CANDIDATES + 1)
        )
        result = await self._session.scalars(statement)
        candidates = list(result.all())
        if len(candidates) > MAX_DUPLICATE_CANDIDATES:
            raise RuntimeError(
                "Invoice duplicate search exceeded its safe candidate limit"
            )
        return candidates

    async def get_or_create_agent(self, vendor_id: UUID) -> Agent:
        await self._lock_vendor(vendor_id)
        result = await self._session.scalars(
            select(Agent).where(
                Agent.vendor_id == vendor_id,
                Agent.name == INVOICE_AGENT_NAME,
                Agent.deleted_at.is_(None),
            )
        )
        agent = result.one_or_none()
        if agent is not None:
            if agent.status is not AgentStatus.ACTIVE:
                raise ValueError("Invoice compliance agent is not active")
            return agent
        agent = Agent(
            vendor_id=vendor_id,
            name=INVOICE_AGENT_NAME,
            agent_type=INVOICE_AGENT_TYPE,
            status=AgentStatus.ACTIVE,
        )
        self._session.add(agent)
        await self._session.flush()
        self.add(
            AuditLog(
                entity_type=AuditEntityType.AGENT,
                entity_id=agent.id,
                vendor_id=vendor_id,
                agent_id=agent.id,
                action="invoice_compliance_agent_registered",
                after_state={"status": AgentStatus.ACTIVE.value},
            )
        )
        return agent

    async def get_decision(
        self,
        decision_id: UUID,
        *,
        lock: bool = False,
    ) -> Decision | None:
        statement = select(Decision).where(Decision.id == decision_id)
        if lock:
            statement = statement.with_for_update()
        result = await self._session.scalars(statement)
        return result.one_or_none()

    async def get_user(self, user_id: UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_prepared_artifact(self, decision_id: UUID) -> AuditLog | None:
        statement = (
            select(AuditLog)
            .where(
                AuditLog.entity_type == AuditEntityType.DECISION,
                AuditLog.entity_id == decision_id,
                AuditLog.action == "invoice_compliance_assessed",
            )
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
        result = await self._session.scalars(statement)
        return result.one_or_none()

    async def _lock_vendor(self, vendor_id: UUID) -> None:
        result = await self._session.execute(
            select(Vendor.id).where(Vendor.id == vendor_id).with_for_update()
        )
        if result.scalar_one_or_none() is None:
            raise LookupError("Invoice vendor no longer exists")

    def add(self, entity: Agent | AuditLog | Decision) -> None:
        self._session.add(entity)
