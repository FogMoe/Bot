"""Tool registry and reusable templates for pydantic-ai."""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Any, Awaitable, Iterable, Protocol, Sequence, TypeVar, Callable

from pydantic import BaseModel, Field
from pydantic_ai import RunContext, Tool
from pydantic_ai.messages import ModelMessage
from app.agents.collaborator import CollaboratorAgent, CollaboratorTurnOutput
from app.agents.tool_agent import SubAgentToolResult, ToolAgent, ToolAgentDependencies
from app.services.external_tools import (
    CodeExecutionService,
    MarketDataService,
    SearchService,
    ToolServiceError,
    WebContentService,
)
from app.services.user_insights import UserInsightService, MAX_IMPRESSION_LENGTH
from app.agents.tool_logging import (
    extract_ctx,
    extract_tool_arguments,
    log_tool_event,
    serialize_tool_payload,
    should_log_tool_call,
)
from app.logging import logger
from app.utils.datetime import utc_now


AGENT_DOCS_DIR = Path(__file__).resolve().parents[2] / "docs" / "agent"


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
        original_handler = self.handler

        @wraps(original_handler)
        async def _logged_handler(*args: Any, **kwargs: Any) -> object:
            ctx = extract_ctx(args, kwargs, self.takes_ctx)
            should_log = should_log_tool_call(ctx)
            tool_input = extract_tool_arguments(args, kwargs, self.takes_ctx)
            _enforce_tool_budget(ctx)
            if should_log:
                log_tool_event(
                    self.name,
                    "request",
                    serialize_tool_payload(tool_input),
                )
            await _maybe_notify_user(ctx, tool_input)
            try:
                result = await original_handler(*args, **kwargs)
            except Exception as exc:
                _log_tool_error(should_log, self.name, exc)
                return _wrap_tool_error(ctx, exc)
            if should_log:
                log_tool_event(self.name, "response", serialize_tool_payload(result))
            return result

        _logged_handler.__signature__ = inspect.signature(original_handler)

        return Tool(
            _logged_handler,
            name=self.name,
            description=self.description,
            takes_ctx=self.takes_ctx,
        )


class ToolInputBase(BaseModel):
    """Base class for tool inputs."""


class SilentToolInput(BaseModel):
    """Tools inheriting from this base won't trigger user notifications."""


class GoogleSearchInput(ToolInputBase):
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


class FetchUrlInput(ToolInputBase):
    url: str = Field(..., description="Fully qualified URL to retrieve")


class FetchUrlOutput(BaseModel):
    url: str
    status_code: int
    content_type: str | None
    content: str


class InstrumentSnapshot(BaseModel):
    symbol: str
    name: str
    current_price: str
    price_change: str | None = None
    percent_change: str | None = None
    open_price: str | None = None
    high_price: str | None = None
    low_price: str | None = None
    previous_close_price: str | None = None
    data_provider_timestamp: int | None = None
    collection_timestamp: int | None = None
    matched_tokens: list[str] = Field(default_factory=list)


class FetchMarketSnapshotInput(ToolInputBase):
    query: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="One or more comma/space separated keywords or symbols",
    )
    max_results: int | None = Field(
        default=5,
        ge=1,
        le=5,
        description="Maximum number of snapshot entries to return",
    )


class FetchMarketSnapshotOutput(BaseModel):
    as_of: str
    total_matches: int
    truncated: bool
    unmatched_tokens: list[str]
    items: list[InstrumentSnapshot] = Field(default_factory=list)
    error_message: str | None = None


class ExecutePythonCodeInput(ToolInputBase):
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


class UpdateImpressionInput(SilentToolInput):
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


class FetchPermanentSummariesInput(SilentToolInput):
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


class CollaborativeReasoningInput(ToolInputBase):
    topic: str = Field(
        ...,
        min_length=1,
        description="Describe what the primary agent intends to discuss with collaborators, including key background, issues, and constraints",
    )
    session_id: str | None = Field(
        default=None,
        description="Optional session identifier; if provided, will attempt to continue the corresponding collaboration thread",
    )
    reset_session: bool = Field(
        default=False,
        description="If True, will forcefully clear the history of the specified session_id and start over",
    )
    max_rounds: int = Field(
        default=3,
        ge=1,
        le=5,
        description="Maximum number of internal collaborator iterations for this call",
    )


class CollaborativeReasoningOutput(BaseModel):
    result: str = Field(..., description="Summary of the collaborator's current analysis")
    task_completed: bool = Field(
        ..., description="True when the collaborator believes the task is fully resolved"
    )
    next_step: str | None = Field(
        default=None, description="If continuing, describe the focus of the next round; otherwise null"
    )
    session_id: str = Field(..., description="Session identifier for continued collaboration")


class AgentDocsInput(SilentToolInput):
    document_name: str | None = Field(
        default=None,
        description="Exact Markdown filename to read (omit to only list available documents)",
    )


class AgentDocsOutput(BaseModel):
    documents: list[str] = Field(default_factory=list)
    selected_document: str | None = None
    content: str | None = None


class ToolDelegationInput(BaseModel):
    user_notice: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="User-visible message explaining that the assistant is processing the request",
    )
    command: str = Field(
        ...,
        min_length=1,
        description="Natural-language instruction describing the task for the tool agent",
    )
    max_tool_calls: int = Field(
        default=3,
        ge=1,
        le=5,
        description="Maximum number of internal tool calls permitted for this delegation",
    )


ToolDelegationOutput = SubAgentToolResult


class ToolErrorPayload(BaseModel):
    error_code: str = Field(..., description="Stable identifier for the failure")
    message: str = Field(..., description="Short diagnostic hint")
    details: dict[str, Any] | None = None


T = TypeVar("T")

_SNAPSHOT_QUERY_SPLIT_PATTERN = re.compile(r"[\s,]+")
_MAX_SNAPSHOT_TOKENS = 5


def _iso_utc_now() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


def _search_service(ctx: RunContext) -> SearchService:
    return SearchService(ctx.deps.http_client, ctx.deps.tool_settings)


def _web_service(ctx: RunContext) -> WebContentService:
    return WebContentService(ctx.deps.http_client, ctx.deps.tool_settings)


def _code_execution_service(ctx: RunContext) -> CodeExecutionService:
    return CodeExecutionService(ctx.deps.http_client, ctx.deps.tool_settings)


def _market_service(ctx: RunContext) -> MarketDataService:
    return MarketDataService(ctx.deps.http_client, ctx.deps.tool_settings)


def _insight_service(ctx: RunContext) -> UserInsightService:
    return UserInsightService(ctx.deps.session)


def _list_agent_docs() -> list[str]:
    if not AGENT_DOCS_DIR.exists() or not AGENT_DOCS_DIR.is_dir():
        return []
    return sorted(
        path.name
        for path in AGENT_DOCS_DIR.glob("*.md")
        if path.is_file()
    )


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


def _parse_snapshot_tokens(raw_query: str) -> list[str]:
    tokens = [token.strip() for token in _SNAPSHOT_QUERY_SPLIT_PATTERN.split(raw_query) if token.strip()]
    if len(tokens) > _MAX_SNAPSHOT_TOKENS:
        tokens = tokens[:_MAX_SNAPSHOT_TOKENS]
    return tokens


async def fetch_market_snapshot_tool(
    ctx: RunContext, data: FetchMarketSnapshotInput
) -> FetchMarketSnapshotOutput:
    tokens = _parse_snapshot_tokens(data.query)
    if not tokens:
        raise RuntimeError("Please provide at least one valid code or keyword")

    service = _market_service(ctx)
    try:
        payload = await service.query_snapshots(tokens, data.max_results)
    except ToolServiceError as exc:
        return FetchMarketSnapshotOutput(
            as_of=_iso_utc_now(),
            total_matches=0,
            truncated=False,
            unmatched_tokens=tokens,
            items=[],
            error_message=str(exc),
        )
    items = [InstrumentSnapshot(**item) for item in payload.items]
    return FetchMarketSnapshotOutput(
        as_of=payload.as_of,
        total_matches=payload.total_matches,
        truncated=payload.truncated,
        unmatched_tokens=payload.unmatched_tokens,
        items=items,
        error_message=None,
    )


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


async def collaborative_reasoning_tool(
    ctx: RunContext, data: CollaborativeReasoningInput
) -> CollaborativeReasoningOutput:
    from app.config import get_settings
    settings = get_settings()
    is_dev = settings.environment == "dev"
    
    collaborator: CollaboratorAgent | None = getattr(ctx.deps, "collaborator_agent", None)
    if collaborator is None:
        raise RuntimeError("Collaborator agent is not configured")

    if data.session_id and data.session_id.strip():
        session_id = data.session_id.strip()
    else:
        session_id = f"default:{ctx.deps.conversation_id}"
    threads = getattr(ctx.deps, "collaborator_threads", None)
    if threads is None:
        raise RuntimeError("Collaborator thread store is missing from dependencies")
    if data.reset_session:
        threads.pop(session_id, None)
        if is_dev:
            logger.info(
                "collaborator_session_reset",
                session_id=session_id,
                topic=data.topic[:100]
            )

    conversation_history: Sequence[ModelMessage] = threads.get(session_id, ())
    
    if is_dev:
        logger.info(
            "collaborator_reasoning_start",
            session_id=session_id,
            topic=data.topic,
            max_rounds=data.max_rounds,
            has_history=len(conversation_history) > 0,
            history_length=len(conversation_history)
        )

    primary_topic = data.topic.strip()
    focus = primary_topic
    last_output: CollaboratorTurnOutput | None = None

    max_rounds = data.max_rounds

    for _ in range(max_rounds):
        round_num = _ + 1
        
        if is_dev:
            logger.info(
                "collaborator_round_start",
                session_id=session_id,
                round=round_num,
                max_rounds=max_rounds,
                focus=focus[:200]
            )
        
        reasoning_prompt = (
            "You are a reasoning collaborator working with me on a multi-step analysis.\n"
            "Your goal in this round is to make meaningful progress toward the overall objective.\n\n"

            f"Primary objective:\n{primary_topic}\n\n"
            f"Current focus of this round:\n{focus}\n\n"
            f"Current round: {round_num} / {max_rounds}\n\n"

            "Guidelines for this round:\n"
            "- Build directly on prior discussion (if provided in the history).\n"
            "- Avoid repeating previous analyses unless needed for context.\n"
            "- Provide clear, concise, and insightful reasoning for this specific focus.\n"
            "- Do not attempt to give the final conclusion unless it is truly justified.\n"
            "- If further investigation is needed, propose a precise next_step.\n"
            "- Maintain analytical tone; do not produce conversational dialogue.\n"
        )
        run_result = await collaborator.run(
            reasoning_prompt, message_history=conversation_history
        )
        conversation_history = list(run_result.all_messages())
        threads[session_id] = conversation_history

        last_output = run_result.output
        
        if is_dev:
            logger.info(
                "collaborator_round_complete",
                session_id=session_id,
                round=round_num,
                result_preview=last_output.result[:300] if last_output.result else None,
                task_completed=last_output.task_completed,
                next_step=last_output.next_step[:100] if last_output.next_step else None,
                history_messages=len(conversation_history)
            )
        
        if last_output.task_completed or not last_output.next_step:
            if is_dev:
                logger.info(
                    "collaborator_reasoning_ended",
                    session_id=session_id,
                    reason="completed" if last_output.task_completed else "no_next_step",
                    total_rounds=round_num
                )
            break
        focus = last_output.next_step.strip()
        if not focus:
            if is_dev:
                logger.info(
                    "collaborator_reasoning_ended",
                    session_id=session_id,
                    reason="empty_next_step",
                    total_rounds=round_num
                )
            break

    if last_output is None:
        raise RuntimeError("Collaborator agent produced no output")

    if is_dev:
        logger.info(
            "collaborator_reasoning_final",
            session_id=session_id,
            result_length=len(last_output.result),
            result_preview=last_output.result[:500],
            task_completed=last_output.task_completed,
            next_step=last_output.next_step
        )

    return CollaborativeReasoningOutput(
        result=last_output.result,
        task_completed=last_output.task_completed,
        next_step=last_output.next_step,
        session_id=session_id,
    )


async def agent_docs_tool(ctx: RunContext, data: AgentDocsInput) -> AgentDocsOutput:
    del ctx  # context is unused but maintained for consistent signature
    documents = _list_agent_docs()
    selected_document: str | None = None
    content: str | None = None

    if data.document_name:
        selected_document = Path(data.document_name).name
        target_path = AGENT_DOCS_DIR / selected_document
        if target_path.is_file() and target_path.suffix.lower() == ".md":
            content = target_path.read_text(encoding="utf-8")

    return AgentDocsOutput(
        documents=documents,
        selected_document=selected_document,
        content=content,
    )


async def delegate_tool_agent(ctx: RunContext, data: ToolDelegationInput) -> ToolDelegationOutput:
    deps = getattr(ctx, "deps", None)
    if deps is None:
        raise RuntimeError("Tool agent dependencies are missing")
    tool_agent: ToolAgent | None = getattr(deps, "tool_agent", None)
    if tool_agent is None:
        raise RuntimeError("Tool agent is not configured")

    tool_deps = ToolAgentDependencies(
        user_id=deps.user_id,
        session=deps.session,
        http_client=deps.http_client,
        tool_settings=deps.tool_settings,
        tool_call_limit=data.max_tool_calls,
    )
    try:
        run_result = await tool_agent.run(data.command, deps=tool_deps)
    except Exception as exc:  # pragma: no cover - defensive guardrail
        logger.warning(
            "tool_agent_run_failed",
            error=str(exc),
        )
        return SubAgentToolResult(
            status="AGENT_FAILURE",
            result=None,
            error_code="TOOL_AGENT_FAILURE",
            message="Tool agent failed to execute the delegated command",
            metadata={
                "tool_name": "delegate_to_tool_agent",
                "tool_input": {
                    "command": data.command,
                    "max_tool_calls": data.max_tool_calls,
                },
            },
        )
    return run_result.output


DEFAULT_TOOLS: tuple[ToolTemplate, ...] = (
    ToolTemplate(
        handler=delegate_tool_agent,
        name="delegate_to_tool_agent",
        description="Delegate a natural-language command to the internal ToolAgent for execution",
    ),
    ToolTemplate(
        handler=google_search_tool,
        name="google_search",
        description="Use Google search engine to obtain the latest information and answers",
    ),
    ToolTemplate(
        handler=fetch_market_snapshot_tool,
        name="fetch_market_snapshot",
        description="Retrieve up-to-date market quotes for stocks or crypto symbols",
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
    ToolTemplate(
        handler=collaborative_reasoning_tool,
        name="collaborative_reasoning",
        description="Invoke an internal collaborator agent for deeper multi-step reasoning with resumable internal dialogues",
    ),
    ToolTemplate(
        handler=agent_docs_tool,
        name="agent_docs_lookup",
        description="List or read internal documentation stored",
    ),
)


class ToolRegistry:
    def __init__(self, presets: Iterable[ToolTemplate] | None = None) -> None:
        self._templates: list[ToolTemplate] = list(presets or DEFAULT_TOOLS)

    def register(self, template: ToolTemplate) -> None:
        self._templates.append(template)

    def iter_tools(
        self,
        *,
        include: Iterable[str] | None = None,
        exclude: Iterable[str] | None = None,
    ) -> Iterable[Tool]:
        include_set = {name for name in include} if include else None
        exclude_set = {name for name in exclude} if exclude else set()
        tools: list[Tool] = []
        for template in self._templates:
            if include_set is not None and template.name not in include_set:
                continue
            if template.name in exclude_set:
                continue
            tools.append(template.build())
        return tuple(tools)


__all__ = [
    "ToolRegistry",
    "ToolTemplate",
    "ToolInputBase",
    "GoogleSearchInput",
    "GoogleSearchOutput",
    "FetchUrlInput",
    "FetchUrlOutput",
    "FetchMarketSnapshotInput",
    "FetchMarketSnapshotOutput",
    "InstrumentSnapshot",
    "ExecutePythonCodeInput",
    "ExecutePythonCodeOutput",
    "UpdateImpressionInput",
    "UpdateImpressionOutput",
    "FetchPermanentSummariesInput",
    "FetchPermanentSummariesOutput",
    "PermanentSummary",
    "CollaborativeReasoningInput",
    "CollaborativeReasoningOutput",
    "AgentDocsInput",
    "AgentDocsOutput",
    "ToolDelegationInput",
    "ToolDelegationOutput",
    "ToolErrorPayload",
    "agent_docs_tool",
    "delegate_tool_agent",
]


def _enforce_tool_budget(ctx: RunContext | None) -> None:
    if ctx is None:
        return
    deps = getattr(ctx, "deps", None)
    if deps is None:
        return
    limit = getattr(deps, "tool_call_limit", None)
    if not limit or limit <= 0:
        return
    current = getattr(deps, "tool_call_count", 0)
    if current >= limit:
        raise RuntimeError("Tool call limit exceeded for this run")
    setattr(deps, "tool_call_count", current + 1)


async def _maybe_notify_user(ctx: RunContext | None, payload: Any) -> None:
    if ctx is None or payload is None:
        return
    notice = getattr(payload, "user_notice", None)
    if not notice:
        return
    notice = notice.strip()
    if not notice:
        return
    deps = getattr(ctx, "deps", None)
    callback: Callable[[str], Awaitable[None]] | None = getattr(
        deps, "tool_notification_cb", None
    )
    if callback is None:
        return
    try:
        await callback(notice)
    except Exception as exc:  # pragma: no cover - notification best effort
        logger.warning("tool_notification_failed", error=str(exc))


async def _wrap_tool_error(ctx: RunContext | None, exc: Exception) -> ToolErrorPayload:
    error_code = getattr(exc, "error_code", None) or exc.__class__.__name__
    message = str(exc) or error_code
    metadata: dict[str, Any] | None = None
    if ctx and getattr(ctx, "deps", None) is not None:
        metadata = {
            "environment": getattr(ctx.deps, "environment", None),
        }
    return ToolErrorPayload(error_code=error_code, message=message, details=metadata)


def _log_tool_error(should_log: bool, tool_name: str, exc: Exception) -> None:
    logger.warning("tool_execution_failed", tool=tool_name, error=str(exc))
    if should_log:
        log_tool_event(tool_name, "error", serialize_tool_payload({"error": str(exc)}))
