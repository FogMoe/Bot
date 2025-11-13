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
from app.services.user_insights import UserInsightService, MAX_IMPRESSION_LENGTH


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


class UpdateImpressionInput(BaseModel):
    impression: str = Field(
        ...,
        min_length=1,
        max_length=MAX_IMPRESSION_LENGTH,
        description="New impression text, complete and self-contained description (max 500 characters)",
    )


class UpdateImpressionOutput(BaseModel):
    user_id: int
    impression: str
    message: str


class FetchPermanentSummariesInput(BaseModel):
    start: int | None = Field(
        default=None,
        ge=1,
        description="Start position (inclusive)",
    )
    end: int | None = Field(
        default=None,
        ge=1,
        description="End position (inclusive)",
    )


class PermanentSummary(BaseModel):
    record_id: int
    created_at: str | None
    summary: str


class FetchPermanentSummariesOutput(BaseModel):
    user_id: int
    total: int
    range_start: int
    range_end: int
    records: list[PermanentSummary]


T = TypeVar("T")


def _search_service(ctx: RunContext) -> SearchService:
    return SearchService(ctx.deps.http_client, ctx.deps.tool_settings)


def _web_service(ctx: RunContext) -> WebContentService:
    return WebContentService(ctx.deps.http_client, ctx.deps.tool_settings)


def _code_execution_service(ctx: RunContext) -> CodeExecutionService:
    return CodeExecutionService(ctx.deps.http_client, ctx.deps.tool_settings)


def _insight_service(ctx: RunContext) -> UserInsightService:
    return UserInsightService(ctx.deps.session)


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


async def update_impression_tool(
    ctx: RunContext, data: UpdateImpressionInput
) -> UpdateImpressionOutput:
    service = _insight_service(ctx)
    record = await service.upsert_impression(ctx.deps.user_id, data.impression)
    return UpdateImpressionOutput(
        user_id=ctx.deps.user_id,
        impression=record.impression,
        message="Impression record updated successfully",
    )


async def fetch_permanent_summaries_tool(
    ctx: RunContext, data: FetchPermanentSummariesInput
) -> FetchPermanentSummariesOutput:
    service = _insight_service(ctx)
    start = data.start or 1
    end = data.end or (start + 9)
    payload = await service.fetch_permanent_summaries(ctx.deps.user_id, start=start, end=end)
    return FetchPermanentSummariesOutput(
        user_id=payload["user_id"],
        total=payload["total"],
        range_start=payload["range_start"],
        range_end=payload["range_end"],
        records=[PermanentSummary(**record) for record in payload["records"]],
    )


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
    ToolTemplate(
        handler=update_impression_tool,
        name="update_impression",
        description="Update permanent impression of the user",
    ),
    ToolTemplate(
        handler=fetch_permanent_summaries_tool,
        name="fetch_permanent_summaries",
        description="Fetch user's historical conversation summaries (newest on top, max 10 results per request)",
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
    "UpdateImpressionInput",
    "UpdateImpressionOutput",
    "FetchPermanentSummariesInput",
    "FetchPermanentSummariesOutput",
    "PermanentSummary",
]
