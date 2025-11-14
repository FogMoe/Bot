"""Lightweight agent dedicated to turning media into textual descriptions."""

from __future__ import annotations

from typing import Sequence

from pydantic_ai import Agent
from pydantic_ai.messages import BinaryImage, UserContent

from app.agents.model_factory import build_model_spec
from app.config import BotSettings, get_settings

MAX_DESCRIPTION_CHARS = 1000


class MediaCaptionAgent:
    """Wrap a small agent that converts media into plain English descriptions."""

    def __init__(self, settings: BotSettings | None = None) -> None:
        self.settings = settings or get_settings()
        provider, model_name = self._resolve_model()
        model_spec = build_model_spec(provider, model_name, self.settings.llm)
        self.agent = Agent(
            model=model_spec,
            name="MediaCaptioner",
            instructions=(
                "You describe Telegram media for a text-only assistant. "
                "Always respond in English, prefer concise paragraphs, "
                "include visible text, and never exceed 1000 characters."
            ),
        )

    async def describe(self, *, prompt_context: str, image: BinaryImage) -> str:
        """Return a bounded, plain-text description for the provided image."""

        user_prompt: list[UserContent] = [prompt_context, image]
        result = await self.agent.run(user_prompt)
        text = result.output.strip()
        if len(text) > MAX_DESCRIPTION_CHARS:
            trimmed = text[:MAX_DESCRIPTION_CHARS].rstrip()
            text = f"{trimmed}..."
        return text

    def _resolve_model(self) -> tuple[str, str]:
        vision = self.settings.vision
        provider = (vision.provider if vision and vision.provider else self.settings.llm.provider)
        model_name = (vision.model if vision and vision.model else self.settings.llm.model)
        return provider, model_name


__all__ = ["MediaCaptionAgent"]
