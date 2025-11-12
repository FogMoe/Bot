"""Tool registry and reusable templates for pydantic-ai."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Iterable, Protocol

from pydantic import BaseModel, Field
from pydantic_ai import RunContext, Tool

from app.services.search import SearchService


class ToolHandler(Protocol):
    async def __call__(self, ctx: RunContext, data: BaseModel) -> object: ...


@dataclass(slots=True)
class ToolTemplate:
    """Declarative metadata for registering a tool with the agent."""

    handler: ToolHandler
    name: str
    description: str
    takes_ctx: bool = True

    def build(self) -> Tool:
        return Tool(
            self.handler,
            name=self.name,
            description=self.description,
            takes_ctx=self.takes_ctx,
        )


class SearchToolInput(BaseModel):
    query: str = Field(..., description="Natural language keywords or phrase to search for")


class SearchToolOutput(BaseModel):
    results: list[str]


async def search_tool(ctx: RunContext, data: SearchToolInput) -> SearchToolOutput:
    """Adapter that delegates to SearchService."""

    service = SearchService(ctx.deps.http_client)
    results = await service.search(data.query)
    return SearchToolOutput(results=list(results))


DEFAULT_TOOLS: tuple[ToolTemplate, ...] = (
    ToolTemplate(
        handler=search_tool,
        name="web_search",
        description="Perform a lightweight web-style search and return short snippets.",
    ),
)


class ToolRegistry:
    def __init__(self, presets: Iterable[ToolTemplate] | None = None) -> None:
        self._templates: list[ToolTemplate] = list(presets or DEFAULT_TOOLS)

    def register(self, template: ToolTemplate) -> None:
        self._templates.append(template)

    def iter_tools(self) -> Iterable[Tool]:
        return tuple(template.build() for template in self._templates)


__all__ = ["ToolRegistry", "ToolTemplate", "SearchToolInput", "SearchToolOutput"]
