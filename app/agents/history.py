"""Utilities for translating stored messages into pydantic-ai history."""

from __future__ import annotations

from typing import Iterable, List

from pydantic_ai import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.messages import SystemPromptPart

from app.domain.models import MessageModel


ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_SYSTEM = "system"


def build_message_history(messages: Iterable[MessageModel]) -> List[ModelMessage]:
    """Convert domain messages into structured model history."""

    history: List[ModelMessage] = []
    for item in messages:
        content = item.content.strip()
        if not content:
            continue

        if item.role == ROLE_ASSISTANT:
            history.append(ModelResponse(parts=[TextPart(content=content)]))
        elif item.role == ROLE_SYSTEM:
            history.append(ModelRequest(parts=[SystemPromptPart(content=content)]))
        elif item.role == "tool":
            continue
        else:  # default to user
            history.append(ModelRequest(parts=[UserPromptPart(content=content)]))

    return history


__all__ = ["build_message_history"]
