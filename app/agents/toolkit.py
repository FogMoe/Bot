"""Tools wired into the Pydantic AI agent."""

from __future__ import annotations

from typing import Callable, Iterable

from pydantic import BaseModel
from pydantic_ai import RunContext

class SearchToolInput(BaseModel):
    query: str


class SearchToolOutput(BaseModel):
    results: list[str]


async def search_tool(ctx: RunContext, data: SearchToolInput) -> SearchToolOutput:
    """Placeholder search tool that can be replaced later."""

    query = data.query.strip()
    if not query:
        return SearchToolOutput(results=[])
    # Dummy implementation until real search provider is wired in.
    return SearchToolOutput(
        results=[f"Search result placeholder for: {query}"]
    )


ToolCallable = Callable[[RunContext, BaseModel], object]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: list[Callable] = [search_tool]

    def register(self, tool_callable: Callable) -> None:
        self._tools.append(tool_callable)

    def iter_tools(self) -> Iterable[Callable]:
        return tuple(self._tools)
