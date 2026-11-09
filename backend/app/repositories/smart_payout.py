"""Persistence queries used by smart payout analysis and approval."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.audit_log import AuditLog
from app.models.decision import Decision
from app.models.enums import AgentStatus, AuditEntityType
from app.models.payout import Payout
from app.models.user import User
from app.models.vendor import Vendor

PAYOUT_AGENT_NAME = "Smart Payout Agent"
PAYOUT_AGENT_TYPE = "smart_payout"
PAYOUT_SUBMISSION_ATTEMPT_ACTION = "payout_submission_started"
PAYOUT_HISTORY_DAYS = 90
MAX_PAYOUT_HISTORY = 500


class SmartPayoutRepository:
    """Keep tenant-scoped payout queries out of workflows and scoring logic."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_context(
        self,
        payout_id: UUID,
        *,
        lock: bool = False,
    ) -> tuple[Payout, Vendor, User] | None:
        statement = select(Payout).where(Payout.id == payout_id)
        if lock:
            statement = statement.with_for_update()
        result = await self._session.scalars(statement)
        payout = result.one_or_none()
        if payout is None:
            return None
        vendor = await self._session.get(Vendor, payout.vendor_id)
        requester = await self._session.get(User, payout.requested_by_user_id)
        if vendor is None or requester is None:
            raise LookupError("Payout vendor or requester record is missing")
        if payout.vendor_id != vendor.id:
            raise ValueError("Payout vendor boundary could not be verified")
        return payout, vendor, requester

    async def list_recent_for_vendor(self, vendor_id: UUID) -> list[Payout]:
        cutoff = datetime.now(UTC) - timedelta(days=PAYOUT_HISTORY_DAYS)
        statement = (
            select(Payout)
            .where(Payout.vendor_id == vendor_id, Payout.created_at >= cutoff)
            .order_by(Payout.created_at.desc())
            .limit(MAX_PAYOUT_HISTORY + 1)
        )
        result = await self._session.scalars(statement)
        return list(result.all())

    async def get_or_create_agent(self, vendor_id: UUID) -> Agent:
        result = await self._session.execute(
            select(Vendor.id).where(Vendor.id == vendor_id).with_for_update()
        )
        if result.scalar_one_or_none() is None:
            raise LookupError("Payout vendor no longer exists")
        agent_result = await self._session.scalars(
            select(Agent).where(
                Agent.vendor_id == vendor_id,
                Agent.name == PAYOUT_AGENT_NAME,
                Agent.deleted_at.is_(None),
            )
        )
        agent = agent_result.one_or_none()
        if agent is not None:
            if agent.status is not AgentStatus.ACTIVE:
                raise ValueError("Smart payout agent is not active")
            return agent
        agent = Agent(
            vendor_id=vendor_id,
            name=PAYOUT_AGENT_NAME,
            agent_type=PAYOUT_AGENT_TYPE,
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
                action="smart_payout_agent_registered",
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
                AuditLog.action == "smart_payout_assessed",
            )
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
        result = await self._session.scalars(statement)
        return result.one_or_none()

    async def get_approval_artifact(self, payout_id: UUID) -> AuditLog | None:
        statement = (
            select(AuditLog)
            .where(
                AuditLog.entity_type == AuditEntityType.PAYOUT,
                AuditLog.entity_id == payout_id,
                AuditLog.action == "payout_approved",
            )
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
        result = await self._session.scalars(statement)
        return result.one_or_none()

    async def has_submission_attempt(self, payout_id: UUID) -> bool:
        result = await self._session.scalars(
            select(AuditLog.id)
            .where(
                AuditLog.entity_type == AuditEntityType.PAYOUT,
                AuditLog.entity_id == payout_id,
                AuditLog.action == PAYOUT_SUBMISSION_ATTEMPT_ACTION,
            )
            .limit(1)
        )
        return result.one_or_none() is not None

    def add(self, entity: Agent | AuditLog | Decision | Payout) -> None:
        self._session.add(entity)
