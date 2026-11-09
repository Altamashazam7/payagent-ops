"""Async OpenAI narrative provider for executive aggregate analysis."""

from __future__ import annotations

from typing import Protocol

from openai import AsyncOpenAI

from app.agents.executive.prompts import (
    EXECUTIVE_COPILOT_SYSTEM_PROMPT,
    build_executive_copilot_prompt,
)
from app.core.settings import Settings
from app.schemas.analytics import (
    CopilotOverview,
    DashboardSummary,
    DashboardTrends,
)


class ExecutiveNarrativeGenerator(Protocol):
    """Generate an informational answer from tenant-level aggregates."""

    async def generate(
        self,
        question: str,
        summary: DashboardSummary,
        trends: DashboardTrends,
        overview: CopilotOverview,
    ) -> str: ...

    async def aclose(self) -> None: ...


class OpenAIExecutiveNarrativeGenerator:
    """Use the configured OpenAI model without sending row-level commerce data."""

    def __init__(self, client: AsyncOpenAI, *, model: str) -> None:
        self._client = client
        self._model = model

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
    ) -> OpenAIExecutiveNarrativeGenerator:
        api_key = settings.openai_api_key
        if api_key is None or not api_key.get_secret_value():
            raise ValueError("OPENAI_API_KEY is required for copilot questions")
        return cls(
            AsyncOpenAI(api_key=api_key.get_secret_value(), max_retries=2),
            model=settings.executive_copilot_model,
        )

    async def generate(
        self,
        question: str,
        summary: DashboardSummary,
        trends: DashboardTrends,
        overview: CopilotOverview,
    ) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": EXECUTIVE_COPILOT_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_executive_copilot_prompt(
                        question,
                        summary,
                        trends,
                        overview,
                    ),
                },
            ],
        )
        content = response.choices[0].message.content
        if content is None or not content.strip():
            raise ValueError("Executive copilot provider returned an empty response")
        answer = content.strip()
        if len(answer) > 5000:
            raise ValueError("Executive copilot provider exceeded the size limit")
        return answer

    async def aclose(self) -> None:
        await self._client.close()
