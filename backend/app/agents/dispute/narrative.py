"""Async OpenAI-backed dispute narrative generation."""

from __future__ import annotations

from typing import Protocol

from openai import AsyncOpenAI

from app.agents.dispute.prompts import (
    DEFENSE_NARRATIVE_SYSTEM_PROMPT,
    build_defense_narrative_prompt,
)
from app.core.settings import Settings
from app.schemas.dispute_defense import DisputeEvidencePackage


class DisputeNarrativeGenerator(Protocol):
    """Generate an evidence-grounded draft narrative for human review."""

    async def generate(
        self,
        package: DisputeEvidencePackage,
    ) -> str:
        """Return a non-empty draft grounded only in the supplied package."""


class OpenAIDisputeNarrativeGenerator:
    """Generate narratives through the async OpenAI chat-completions API."""

    def __init__(self, client: AsyncOpenAI, *, model: str) -> None:
        self._client = client
        self._model = model

    @classmethod
    def from_settings(cls, settings: Settings) -> OpenAIDisputeNarrativeGenerator:
        """Create a client from validated settings; missing credentials fail closed."""
        api_key = settings.openai_api_key
        if api_key is None or not api_key.get_secret_value():
            raise ValueError("OPENAI_API_KEY is required for dispute narratives")
        return cls(
            AsyncOpenAI(api_key=api_key.get_secret_value(), max_retries=2),
            model=settings.dispute_narrative_model,
        )

    async def generate(
        self,
        package: DisputeEvidencePackage,
    ) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": DEFENSE_NARRATIVE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_defense_narrative_prompt(package),
                },
            ],
        )
        content = response.choices[0].message.content
        if content is None or not content.strip():
            raise ValueError("Narrative provider returned an empty response")
        narrative = content.strip()
        if len(narrative) > 5000:
            raise ValueError("Narrative provider exceeded the 5,000 character limit")
        return narrative

    async def aclose(self) -> None:
        """Close the owned OpenAI transport."""
        await self._client.close()
