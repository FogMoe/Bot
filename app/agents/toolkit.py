"""Tool registry and reusable templates for pydantic-ai."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from functools import wraps
from typing import Any, Awaitable, Iterable, Protocol, Sequence, TypeVar, Callable

from pydantic import BaseModel, Field
from pydantic_ai import RunContext, Tool
from pydantic_ai.messages import ModelMessage
from app.agents.collaborator import CollaboratorAgent, CollaboratorTurnOutput
from app.services.external_tools import (
    CodeExecutionService,
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
            if should_log:
                log_tool_event(
                    self.name,
                    "request",
                    serialize_tool_payload(tool_input),
                )
            await _maybe_notify_user(ctx, tool_input)
            result = await original_handler(*args, **kwargs)
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
    user_notice: str = Field(
        min_length=1,
        max_length=50,
        description=("User-facing message displayed in user's language when this tool runs\n"
                     'For example: "I am helping you look up relevant information…"'
        ),
    )


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


class UpdateImpressionInput(ToolInputBase):
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


class FetchPermanentSummariesInput(ToolInputBase):
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
    ToolTemplate(
        handler=collaborative_reasoning_tool,
        name="collaborative_reasoning",
        description="Invoke an internal collaborator agent for deeper multi-step reasoning with resumable internal dialogues",
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
    "ToolInputBase",
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
    "CollaborativeReasoningInput",
    "CollaborativeReasoningOutput",
]


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
