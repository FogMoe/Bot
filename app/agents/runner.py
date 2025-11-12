"""High-level orchestrator around Pydantic AI agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import httpx
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.azure import AzureProvider

from app.agents.toolkit import ToolRegistry
from app.config import BotSettings, get_settings
from app.domain.models import MessageModel
from app.services.memory import MemoryService


@dataclass
class AgentDependencies:
    user_id: int
    conversation_id: int
    http_client: httpx.AsyncClient
    memory_service: MemoryService
    recent_messages: Sequence[MessageModel]


def _model_spec(settings: BotSettings) -> str | OpenAIChatModel:
    provider = settings.llm.provider.lower()
    if provider in {"azure", "azure_openai"} or provider.startswith("azure"):
        if not settings.llm.base_url or not settings.llm.api_version or not settings.llm.api_key:
            raise ValueError(
                "Azure OpenAI requires BOT_LLM__BASE_URL, BOT_LLM__API_VERSION, and BOT_LLM__API_KEY."
            )
        azure_provider = AzureProvider(
            azure_endpoint=str(settings.llm.base_url),
            api_version=settings.llm.api_version,
            api_key=settings.llm.api_key.get_secret_value(),
        )
        return OpenAIChatModel(settings.llm.model, provider=azure_provider)

    provider_map = {
        "openai": "openai",
        "anthropic": "anthropic",
        "custom": "openai",
    }
    prefix = provider_map.get(provider, "openai")
    return f"{prefix}:{settings.llm.model}"


def build_agent(
    settings: BotSettings, tool_registry: ToolRegistry | None = None
) -> Agent[AgentDependencies, str]:
    registry = tool_registry or ToolRegistry()
    model_spec = _model_spec(settings)
    agent = Agent(
        model=model_spec,
        deps_type=AgentDependencies,
        instructions="You are a helpful assistant that references memories when relevant.",
        name="FOGMOE",
        tools=list(registry.iter_tools()),
    )

    @agent.system_prompt
    async def system_prompt(ctx: RunContext[AgentDependencies]) -> str:
        memories = await ctx.deps.memory_service.fetch_relevant_memories(
            ctx.deps.user_id, limit=5
        )
        memory_lines = "\n".join(f"- {m.content}" for m in memories) or "None"
        history_lines = "\n".join(
            f"{message.role}: {message.content}" for message in ctx.deps.recent_messages
        )
        return (
            "You are chatting in Telegram. "
            "If AI output contains newline characters, respond with numbered paragraphs "
            "unless text is wrapped in triple backticks.\n"
            f"Known user memories:\n{memory_lines}\n\n"
            f"Recent conversation:\n{history_lines}"
        )

    return agent


class AgentOrchestrator:
    def __init__(
        self, settings: BotSettings | None = None, tool_registry: ToolRegistry | None = None
    ) -> None:
        self.settings = settings or get_settings()
        self.agent = build_agent(self.settings, tool_registry=tool_registry)

    async def run(
        self,
        *,
        user_id: int,
        conversation_id: int,
        messages: Sequence[MessageModel],
        memory_service: MemoryService,
    ) -> str:
        async with httpx.AsyncClient(timeout=30) as client:
            deps = AgentDependencies(
                user_id=user_id,
                conversation_id=conversation_id,
                http_client=client,
                memory_service=memory_service,
                recent_messages=messages,
            )
            result = await self.agent.run(
                messages[-1].content if messages else "",
                deps=deps,
            )
            return result.output
