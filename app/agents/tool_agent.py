"""Dedicated agent responsible for executing low-level tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Sequence

import httpx
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext, Tool
from pydantic_ai.run import AgentRunResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.model_factory import build_model_spec
from app.config import BotSettings, ExternalToolSettings


class SubAgentToolResult(BaseModel):
    status: Literal["SUCCESS", "BUSINESS_ERROR"] = Field(
        ..., description="Indicates whether the requested task succeeded at the business level"
    )
    result: Any | None = Field(
        default=None,
        description="Raw machine-friendly payload returned by the tool, if available",
    )
    error_code: str | None = Field(
        default=None,
        description="Stable machine-readable error identifier for BUSINESS_ERROR results",
    )
    message: str | None = Field(
        default=None,
        description="Short diagnostic string for BUSINESS_ERROR results",
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Additional metadata such as tool name, inputs, or tracing identifiers",
    )


@dataclass(slots=True)
class ToolAgentDependencies:
    user_id: int
    session: AsyncSession
    http_client: httpx.AsyncClient
    tool_settings: ExternalToolSettings
    tool_call_limit: int = 0
    tool_call_count: int = 0


_TOOL_AGENT_INSTRUCTIONS = """
You are a ToolAgent.

Rules:
1. You may only interact with tools and must never produce natural-language dialogue.
2. The provided command is plain text with no structured parameters. Parse it and determine the best available tool.
3. Construct tool parameters yourself. Never ask for clarification or emit explanations.
4. You may call multiple tools but the run has a strict maximum tool budget provided separately.
5. Output must be valid JSON with the exact shape:
   {
     "status": "SUCCESS" | "BUSINESS_ERROR",
     "result": {...} | null,
     "error_code": "..." | null,
     "message": "..." | null,
     "metadata": {...} | null
   }
6. If no available tool can complete the task, return BUSINESS_ERROR with error_code="NO_AVAILABLE_TOOL".
7. Do not invent tools, and do not reference the user or command in the output.
8. metadata must include at least "tool_name" and "tool_input" describing the tool invocation that produced the result.
""".strip()


def _resolve_tool_agent_model(settings: BotSettings) -> str:
    tool_agent_settings = settings.tool_agent
    if tool_agent_settings and tool_agent_settings.provider and tool_agent_settings.model:
        provider = tool_agent_settings.provider
        model_name = tool_agent_settings.model
    else:
        provider = settings.llm.provider
        model_name = settings.llm.model
    return build_model_spec(provider, model_name, settings.llm)


@dataclass(slots=True)
class ToolAgent:
    agent: Agent[ToolAgentDependencies, SubAgentToolResult]

    @classmethod
    def build(cls, settings: BotSettings, tools: Sequence[Tool]) -> ToolAgent:
        model_spec = _resolve_tool_agent_model(settings)
        agent = Agent(
            model=model_spec,
            deps_type=ToolAgentDependencies,
            output_type=SubAgentToolResult,
            instructions=_TOOL_AGENT_INSTRUCTIONS,
            name="ToolAgent",
            tools=tuple(tools),
            model_settings={"openai_reasoning_effort": "low"},
        )

        @agent.instructions
        def _tool_budget_instruction(ctx: RunContext[ToolAgentDependencies]) -> str:
            if not ctx or not ctx.deps:
                return ""
            limit = ctx.deps.tool_call_limit
            if limit <= 0:
                return ""
            return f"Maximum tool calls allowed during this run: {limit}."

        return cls(agent)

    async def run(
        self,
        command: str,
        *,
        deps: ToolAgentDependencies,
    ) -> AgentRunResult[SubAgentToolResult]:
        prompt = f"Command:\n{command.strip()}" if command else "Command:\n"
        deps.tool_call_count = 0
        return await self.agent.run(prompt, deps=deps, message_history=())


__all__ = ["ToolAgent", "ToolAgentDependencies", "SubAgentToolResult"]
