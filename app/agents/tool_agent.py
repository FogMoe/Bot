"""Dedicated agent responsible for executing low-level tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Sequence

import httpx
from pydantic_ai import Agent, RunContext, Tool
from pydantic_ai.run import AgentRunResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.model_factory import build_model_spec
from app.agents.tool_types import SubAgentToolResult, ToolErrorPayload
from app.config import BotSettings, ExternalToolSettings


@dataclass(slots=True)
class ToolAgentDependencies:
    user_id: int
    session: AsyncSession
    http_client: httpx.AsyncClient
    tool_settings: ExternalToolSettings
    tool_call_limit: int = 0
    tool_call_count: int = 0


class ToolAgentCallLimitExceeded(RuntimeError):
    """Raised when the tool agent exceeds its configured tool budget."""


_TOOL_AGENT_INSTRUCTIONS = """\
# Role
You are a ToolAgent.

# Rules
1. You may only interact with tools and must never produce natural-language dialogue.
2. The provided command is plain text with no structured parameters. Parse it and determine the best available tool.
3. Construct tool parameters yourself. Never ask for clarification or emit explanations.
4. You may call multiple tools.
5. Output must be valid JSON with the exact shape:
   {
     "status": "SUCCESS" | "BUSINESS_ERROR" | "TOOL_FAILURE",
     "payload": {...} | null,
     "error": {"error_code": "...", "message": "..."} | null
   }
6. If no available tool can complete the task, return BUSINESS_ERROR with error_code="NO_AVAILABLE_TOOL".
7. If the tools encounter an internal failure, return TOOL_FAILURE with a descriptive error_code.
8. Do not invent tools, and do not reference the user or command in the output.
9. When status is SUCCESS, payload must include the invoked tool name, inputs, and outputs.
   - For multiple tools, include array of invocations with execution order.

# Parameter Construction
- Extract structured parameters from plain text commands.
- Apply reasonable defaults when optional parameters are missing.
- Validate required parameters before execution.
- For ambiguous inputs, favor the most common interpretation.

# Guidelines
1. google_search (real-time info)
   - Call this tool when you need to search the internet for the latest information.
2. fetch_market_snapshot (quotes)
   - Call this tool to retrieve up-to-date stock, index, or crypto quotes (up to 5 results per request).
   - The fetch_market_snapshot tool is a great tool when before providing financial advice.
3. execute_python_code (python execution)
   - Call this tool when you or the user needs to run Python code for complex tasks, like calculations, data processing, or testing.
   - All results need to be printed using `print()`, otherwise they will not appear in the output.
4. fetch_url (open link)
   - Call this tool to fetch and read webpage content in real-time.
5. agent_docs_lookup (internal docs)
   - Call this tool to list or read internal documentation stored when answering FOGMOE bot or business-specific questions.
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
        )

        @agent.instructions
        def _tool_budget_instruction(ctx: RunContext[ToolAgentDependencies]) -> str:
            if not ctx or not ctx.deps:
                return ""
            limit = ctx.deps.tool_call_limit
            if limit <= 0:
                return ""
            if ctx.deps.tool_call_count >= limit:
                raise ToolAgentCallLimitExceeded("Tool call limit exceeded for this run")
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
