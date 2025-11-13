"""Lightweight collaborator agent used for internal tool-driven deliberation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from pydantic_ai import Agent
from pydantic_ai.run import AgentRunResult
from pydantic_ai.messages import ModelMessage

from app.agents.model_factory import build_model_spec
from app.config import BotSettings


@dataclass(slots=True)
class CollaboratorAgent:
    """Encapsulates the child agent used for collaborative reasoning."""

    agent: Agent[None, str]

    @classmethod
    def build(cls, settings: BotSettings) -> CollaboratorAgent:
        model = _collaborator_model_spec(settings)
        agent = Agent(
            model=model,
            instructions=(
                "You are a focused reasoning partner. "
                "Think through the request carefully, explore alternative angles when helpful, "
                "and converge on the strongest final answer. Keep the response concise and actionable."
            ),
            name="Collaborator",
            tools=(),
        )
        return cls(agent)

    async def run(
        self,
        prompt: str,
        *,
        message_history: Sequence[ModelMessage] | None = None,
    ) -> AgentRunResult[str]:
        return await self.agent.run(prompt, message_history=message_history)


def _collaborator_model_spec(settings: BotSettings):
    collab_settings = settings.collaborator
    if collab_settings is None:
        provider = settings.llm.provider
        model_name = settings.llm.model
    else:
        provider = collab_settings.provider or settings.llm.provider
        model_name = collab_settings.model or settings.llm.model
    return build_model_spec(provider, model_name, settings.llm)


__all__ = ["CollaboratorAgent"]
