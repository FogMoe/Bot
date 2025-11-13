"""Lightweight agent dedicated to summarizing archived conversations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.config import BotSettings


def _format_user_content(content: str | Sequence[str]) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(str(part) for part in content)


def format_history_for_summary(messages: Sequence[ModelMessage]) -> str:
    """Flatten model messages into a human-readable transcript for summarization."""

    lines: list[str] = []
    for message in messages:
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, SystemPromptPart):
                    continue
                if isinstance(part, UserPromptPart):
                    lines.append(f"USER: {_format_user_content(part.content)}")
                elif isinstance(part, ToolReturnPart):
                    lines.append(f"TOOL[{part.tool_name}]: {part.content}")
        elif isinstance(message, ModelResponse):
            text_chunks = [part.content for part in message.parts if isinstance(part, TextPart)]
            if text_chunks:
                lines.append(f"ASSISTANT: {'\n'.join(text_chunks)}")
    return "\n\n".join(lines)


@dataclass(slots=True)
class SummaryAgent:
    """Encapsulates the ZAI-based summarization agent."""

    agent: Agent[None, str]

    @classmethod
    def build(cls, settings: BotSettings) -> SummaryAgent:
        zai_settings = settings.zai
        if not zai_settings or not zai_settings.base_url or not zai_settings.api_key:
            raise ValueError("ZAI settings must be configured to enable conversation summarization.")

        provider = OpenAIProvider(
            base_url=str(zai_settings.base_url),
            api_key=zai_settings.api_key.get_secret_value(),
        )
        model_name = (
            zai_settings.summary_model
            or zai_settings.default_model
            or settings.llm.model
        )
        agent = Agent[
            None,
            str,
        ](
            model=OpenAIChatModel(model_name, provider=provider),
            instructions=(
                "You're a meticulous conversation summarizer. "
                "Given the full transcript of a chat between a user and an assistant, "
                "produce a concise summary (bullet points are OK) that captures key questions, "
                "answers, and next steps. Keep the output under roughly 2,000 tokens."
            ),
            model_settings={"max_tokens": 2000},
        )
        return cls(agent)

    async def summarize(self, transcript: str) -> str:
        result = await self.agent.run(transcript)
        return result.output.strip()

    async def summarize_history(self, messages: Sequence[ModelMessage]) -> str:
        transcript = format_history_for_summary(messages)
        return await self.summarize(transcript)


__all__ = [
    "SummaryAgent",
    "format_history_for_summary",
]
