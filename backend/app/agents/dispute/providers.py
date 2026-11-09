"""Evidence-provider contracts for shipping and customer communications."""

import logging
from collections.abc import Sequence
from typing import Protocol

from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.schemas.commerce import DisputeRead, TransactionRead, VendorRead
from app.schemas.dispute_defense import (
    CommunicationEvidenceRecord,
    ShippingEvidenceRecord,
)

logger = logging.getLogger("payagent_ops")


class TransientEvidenceProviderError(Exception):
    """Evidence source reports a temporary failure that is safe to retry."""


class DisputeEvidenceProvider(Protocol):
    """Read-only source of vendor shipping and redacted communication evidence."""

    async def get_shipping_evidence(
        self,
        vendor: VendorRead,
        transaction: TransactionRead,
    ) -> Sequence[ShippingEvidenceRecord]:
        """Return source-referenced shipping facts, or an empty sequence."""

    async def get_communication_history(
        self,
        vendor: VendorRead,
        dispute: DisputeRead,
    ) -> Sequence[CommunicationEvidenceRecord]:
        """Return redacted communication metadata, or an empty sequence."""


def _log_provider_retry(state: RetryCallState) -> None:
    logger.warning(
        "Transient dispute evidence source failure; retrying",
        extra={
            "event": "dispute_evidence_provider_retry",
            "dependency": "evidence_provider",
            "attempt": state.attempt_number,
        },
    )


class RetryingDisputeEvidenceProvider:
    """Retry only explicitly transient, read-only evidence-provider failures."""

    def __init__(self, provider: DisputeEvidenceProvider) -> None:
        self._provider = provider

    @retry(
        retry=retry_if_exception_type(TransientEvidenceProviderError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.1, min=0.1, max=1),
        before_sleep=_log_provider_retry,
        reraise=True,
    )
    async def get_shipping_evidence(
        self,
        vendor: VendorRead,
        transaction: TransactionRead,
    ) -> Sequence[ShippingEvidenceRecord]:
        return await self._provider.get_shipping_evidence(vendor, transaction)

    @retry(
        retry=retry_if_exception_type(TransientEvidenceProviderError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.1, min=0.1, max=1),
        before_sleep=_log_provider_retry,
        reraise=True,
    )
    async def get_communication_history(
        self,
        vendor: VendorRead,
        dispute: DisputeRead,
    ) -> Sequence[CommunicationEvidenceRecord]:
        return await self._provider.get_communication_history(vendor, dispute)
