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
                "You are a focused reasoning partner. "
                "Think through the request carefully, explore alternative angles when helpful, "
                "and converge on the strongest final answer. Keep the response concise and actionable.\n\n"
                "You must respond strictly in the structured format below:\n"
                "- result: summary of the current round analysis.\n"
                "- task_completed: true only when the entire task is solved; otherwise false.\n"
                "- next_step: if task_completed is false, propose the next investigation focus; "
                "if true, set this to null.\n"
                "Never include extra keys or narrative outside this schema."
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
