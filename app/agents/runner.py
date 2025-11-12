"""High-level orchestrator around Pydantic AI agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import httpx
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.azure import AzureProvider

from app.agents.history import build_message_history
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
        instructions="""\
# Role
You are **FOGMOE**, a friendly AI assistant inside Telegram chats.

# Guidelines
- Reference relevant user memories when helpful.
- If you need external information, call tools transparently.
- Avoid sharing internal errors; ask the user to retry politely.
- Responses are sent line-by-line in Telegram. Each non-code line becomes a separate message.

# Style
- Use Markdown; wrap code with triple backticks.
- Mention which tools were used (e.g., `_Used: web_search_`).
""",
        name="FOGMOE",
        tools=list(registry.iter_tools()),
    )

    @agent.system_prompt
    async def system_prompt(ctx: RunContext[AgentDependencies]) -> str:
        memories = await ctx.deps.memory_service.fetch_relevant_memories(
            ctx.deps.user_id, limit=5
        )
        memory_lines = "\n".join(f"- {m.content}" for m in memories) or "None"
        return f"""\
## Conversation Context
- Platform: Telegram chat
- To prevent line breaks, wrap your text in triple backticks (```). Every non-code line will be sent as a separate message.
- Always mention tools relied upon (e.g., `_Used: web_search_`).

## Known user memories
{memory_lines}
"""

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
        if not messages:
            raise ValueError("messages list must contain at least one user turn")

        prior_messages = build_message_history(messages[:-1])
        latest_message = messages[-1]

        async with httpx.AsyncClient(timeout=30) as client:
            deps = AgentDependencies(
                user_id=user_id,
                conversation_id=conversation_id,
                http_client=client,
                memory_service=memory_service,
                recent_messages=messages,
            )
            result = await self.agent.run(
                latest_message.content,
                deps=deps,
                message_history=prior_messages,
            )
            return result.output
