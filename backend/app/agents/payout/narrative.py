"""Async OpenAI-backed payout risk summaries."""

from __future__ import annotations

from typing import Protocol

from openai import AsyncOpenAI

from app.agents.payout.prompts import (
    PAYOUT_ANALYSIS_SYSTEM_PROMPT,
    build_payout_analysis_prompt,
)
from app.core.settings import Settings
from app.schemas.smart_payout import PayoutRiskAssessment


class PayoutNarrativeGenerator(Protocol):
    """Generate a reviewer-facing summary without exposing recipient details."""

    async def generate(self, assessment: PayoutRiskAssessment) -> str: ...


class OpenAIPayoutNarrativeGenerator:
    """Generate a bounded payout summary through the async OpenAI client."""

    def __init__(self, client: AsyncOpenAI, *, model: str) -> None:
        self._client = client
        self._model = model

    @classmethod
    def from_settings(cls, settings: Settings) -> OpenAIPayoutNarrativeGenerator:
        api_key = settings.openai_api_key
        if api_key is None or not api_key.get_secret_value():
            raise ValueError("OPENAI_API_KEY is required for payout summaries")
        return cls(
            AsyncOpenAI(api_key=api_key.get_secret_value(), max_retries=2),
            model=settings.payout_narrative_model,
        )

    async def generate(self, assessment: PayoutRiskAssessment) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": PAYOUT_ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": build_payout_analysis_prompt(assessment)},
            ],
        )
        content = response.choices[0].message.content
        if content is None or not content.strip():
            raise ValueError("Payout narrative provider returned an empty response")
        narrative = content.strip()
        if len(narrative) > 5000:
            raise ValueError("Payout narrative provider exceeded the size limit")
        return narrative

    async def aclose(self) -> None:
        await self._client.close()
