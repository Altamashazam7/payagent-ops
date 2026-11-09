"""Async OpenAI-backed invoice compliance summaries."""

from __future__ import annotations

from typing import Protocol

from openai import AsyncOpenAI

from app.agents.invoice.prompts import (
    INVOICE_COMPLIANCE_SYSTEM_PROMPT,
    build_invoice_compliance_prompt,
)
from app.core.settings import Settings
from app.schemas.commerce import InvoiceRead
from app.schemas.invoice_compliance import InvoiceComplianceAssessment


class InvoiceNarrativeGenerator(Protocol):
    """Generate a reviewer-facing summary from validated invoice findings."""

    async def generate(
        self,
        invoice: InvoiceRead,
        assessment: InvoiceComplianceAssessment,
    ) -> str: ...


class OpenAIInvoiceNarrativeGenerator:
    """Generate a bounded invoice summary through the async OpenAI client."""

    def __init__(self, client: AsyncOpenAI, *, model: str) -> None:
        self._client = client
        self._model = model

    @classmethod
    def from_settings(cls, settings: Settings) -> OpenAIInvoiceNarrativeGenerator:
        api_key = settings.openai_api_key
        if api_key is None or not api_key.get_secret_value():
            raise ValueError("OPENAI_API_KEY is required for invoice summaries")
        return cls(
            AsyncOpenAI(api_key=api_key.get_secret_value(), max_retries=2),
            model=settings.invoice_compliance_model,
        )

    async def generate(
        self,
        invoice: InvoiceRead,
        assessment: InvoiceComplianceAssessment,
    ) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": INVOICE_COMPLIANCE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_invoice_compliance_prompt(invoice, assessment),
                },
            ],
        )
        content = response.choices[0].message.content
        if content is None or not content.strip():
            raise ValueError("Invoice narrative provider returned an empty response")
        narrative = content.strip()
        if len(narrative) > 5000:
            raise ValueError("Invoice narrative provider exceeded the size limit")
        return narrative

    async def aclose(self) -> None:
        await self._client.close()
