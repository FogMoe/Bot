"""Tool registry and reusable templates for pydantic-ai."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Iterable, Protocol, TypeVar

from pydantic import BaseModel, Field
from pydantic_ai import RunContext, Tool
from app.services.external_tools import (
    CodeExecutionService,
    SearchService,
    ToolServiceError,
    WebContentService,
)


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


class GoogleSearchInput(BaseModel):
    query: str = Field(
        ...,
        description=(
            "Search query string. Can be keywords, phrases, or complete questions"
        ),
    )


class GoogleSearchOutput(BaseModel):
    search_metadata: dict[str, Any]
    search_parameters: dict[str, Any]
    organic_results: list[dict[str, Any]]


class FetchUrlInput(BaseModel):
    url: str = Field(..., description="Fully qualified URL to retrieve")


class FetchUrlOutput(BaseModel):
    url: str
    status_code: int
    content_type: str | None
    content: str


class ExecutePythonCodeInput(BaseModel):
    source_code: str = Field(..., description="Python source code snippet to execute")
    stdin: str | None = Field(
        default=None,
        description="Optional standard input for the program",
    )


class ExecutePythonCodeOutput(BaseModel):
    token: str | None
    status_id: int | None
    status_description: str | None
    stdout: str
    stderr: str
    compile_output: str
    message: str | None
    time: str | None
    memory: int | None


T = TypeVar("T")


def _search_service(ctx: RunContext) -> SearchService:
    return SearchService(ctx.deps.http_client, ctx.deps.tool_settings)


def _web_service(ctx: RunContext) -> WebContentService:
    return WebContentService(ctx.deps.http_client, ctx.deps.tool_settings)


def _code_execution_service(ctx: RunContext) -> CodeExecutionService:
    return CodeExecutionService(ctx.deps.http_client, ctx.deps.tool_settings)


async def _run_with_service_errors(awaitable: Awaitable[T]) -> T:
    try:
        return await awaitable
    except ToolServiceError as exc:
        raise RuntimeError(str(exc)) from exc


async def google_search_tool(ctx: RunContext, data: GoogleSearchInput) -> GoogleSearchOutput:
    service = _search_service(ctx)
    payload = await _run_with_service_errors(service.google_search(data.query))
    return GoogleSearchOutput(**payload)


async def fetch_url_tool(ctx: RunContext, data: FetchUrlInput) -> FetchUrlOutput:
    service = _web_service(ctx)
    payload = await _run_with_service_errors(service.fetch(data.url))
    return FetchUrlOutput(**payload)


async def execute_python_code_tool(
    ctx: RunContext, data: ExecutePythonCodeInput
) -> ExecutePythonCodeOutput:
    service = _code_execution_service(ctx)
    payload = await _run_with_service_errors(
        service.execute(data.source_code, stdin=data.stdin)
    )
    return ExecutePythonCodeOutput(**payload)


DEFAULT_TOOLS: tuple[ToolTemplate, ...] = (
    ToolTemplate(
        handler=google_search_tool,
        name="google_search",
        description="Use Google search engine to obtain the latest information and answers",
    ),
    ToolTemplate(
        handler=fetch_url_tool,
        name="fetch_url",
        description="Fetch and render webpage content for up-to-date browsing",
    ),
    ToolTemplate(
        handler=execute_python_code_tool,
        name="execute_python_code",
        description="Run Python code remotely and return its output",
    ),
)


class ToolRegistry:
    def __init__(self, presets: Iterable[ToolTemplate] | None = None) -> None:
        self._templates: list[ToolTemplate] = list(presets or DEFAULT_TOOLS)

    def register(self, template: ToolTemplate) -> None:
        self._templates.append(template)

    def iter_tools(self) -> Iterable[Tool]:
        return tuple(template.build() for template in self._templates)


__all__ = [
    "ToolRegistry",
    "ToolTemplate",
    "GoogleSearchInput",
    "GoogleSearchOutput",
    "FetchUrlInput",
    "FetchUrlOutput",
    "ExecutePythonCodeInput",
    "ExecutePythonCodeOutput",
]
