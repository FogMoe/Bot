"""Helper utilities for logging tool inputs/outputs."""

from __future__ import annotations

import os
from dataclasses import asdict, is_dataclass
from typing import Any, Literal, Sequence

from pydantic import BaseModel
from pydantic_ai import RunContext

from app.logging import logger


def should_log_tool_call(ctx: RunContext | None) -> bool:
    """Determine whether tool logging should run for this invocation."""

    env_override = os.getenv("BOT_ENVIRONMENT")
    if env_override is not None:
        return env_override == "dev"

    deps = getattr(ctx, "deps", None) if ctx else None
    ctx_env = getattr(deps, "environment", None)
    return ctx_env == "dev"


def extract_ctx(
    args: Sequence[Any], kwargs: dict[str, Any], takes_ctx: bool
) -> RunContext | None:
    """Extract the RunContext from positional or keyword arguments."""

    if "ctx" in kwargs:
        return kwargs["ctx"]
    if takes_ctx and args:
        return args[0]
    return None


def extract_tool_arguments(args: Sequence[Any], kwargs: dict[str, Any], takes_ctx: bool) -> Any:
    """Return the tool input payload, skipping ctx if required."""

    if "data" in kwargs:
        return kwargs["data"]
    if kwargs:
        return kwargs
    idx = 1 if takes_ctx else 0
    if len(args) > idx:
        return args[idx]
    return None


def serialize_tool_payload(value: Any) -> Any:
    """Convert tool inputs/outputs into JSON-friendly structures."""

    if isinstance(value, BaseModel):
        return value.model_dump()
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {key: serialize_tool_payload(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize_tool_payload(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def log_tool_event(tool: str, phase: Literal["request", "response"], payload: Any) -> None:
    """Emit a structured tool log entry."""

    logger.info("tool_call", tool=tool, phase=phase, payload=payload)


__all__ = [
    "should_log_tool_call",
    "extract_ctx",
    "extract_tool_arguments",
    "serialize_tool_payload",
    "log_tool_event",
]
