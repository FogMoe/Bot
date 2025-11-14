"""Lightweight collaborator agent used for internal tool-driven deliberation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.run import AgentRunResult
from pydantic_ai.messages import ModelMessage

from app.agents.model_factory import build_model_spec
from app.config import BotSettings


class CollaboratorTurnOutput(BaseModel):
    result: str = Field(..., description="Conclusions after analysis or recommendations for the current round")
    task_completed: bool = Field(
        ..., description="True when the task is fully resolved; otherwise false"
    )
    next_step: str | None = Field(
        default=None,
        description="If continuing, describe the focus of the next round; otherwise null",
    )


@dataclass(slots=True)
class CollaboratorAgent:
    """Encapsulates the child agent used for collaborative reasoning."""

    agent: Agent[None, CollaboratorTurnOutput]

    @classmethod
    def build(cls, settings: BotSettings) -> CollaboratorAgent:
        model = _collaborator_model_spec(settings)
        agent = Agent(
            model=model,
            output_type=CollaboratorTurnOutput,
            instructions=(
                "You are a multi-step reasoning collaborator. "
                "Your goal is to help progressively analyze the user's topic. "
                "Each round should contribute meaningful reasoning or decomposition. "
                "Do not jump to the final conclusion until the task is truly completed.\n\n"

                "Produce output that fits the required tool schema:\n"
                "- result: the key insights from this round only.\n"
                "- task_completed: true only if the full objective is achieved.\n"
                "- next_step: a concise direction for the next round; null if the task is completed.\n\n"

                "Focus on clarity, correctness, and incremental progress."
            ),
            name="Collaborator",
            tools=(),
            model_settings={"openai_reasoning_effort": "low"},
        )
        return cls(agent)

    async def run(
        self,
        prompt: str,
        *,
        message_history: Sequence[ModelMessage] | None = None,
    ) -> AgentRunResult[CollaboratorTurnOutput]:
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


__all__ = ["CollaboratorAgent", "CollaboratorTurnOutput"]
