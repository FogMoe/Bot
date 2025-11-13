"""Tests for conversation persistence and archiving logic."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from app.db.models.core import ConversationArchive, Message, User
from app.services import conversations as conversations_module
from app.services.conversations import ConversationService


def _make_messages(pair_count: int = 3):
    messages: list = []
    for idx in range(pair_count):
        messages.append(
            ModelRequest(parts=[UserPromptPart(content=f"user message {idx}")])
        )
        messages.append(ModelResponse(parts=[TextPart(content=f"bot reply {idx}")]))
    return messages


class DummyResult:
    def __init__(self, messages, total_tokens: int) -> None:
        self._messages = messages
        self._usage = SimpleNamespace(total_tokens=total_tokens)

    def all_messages(self):
        return self._messages

    def usage(self):
        return self._usage


async def _bootstrap_user(session) -> User:
    user = User(telegram_id=1111, username="tester")
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_get_or_create_conversation_is_idempotent(session):
    service = ConversationService(session)
    user = await _bootstrap_user(session)

    first = await service.get_or_create_active_conversation(user)
    second = await service.get_or_create_active_conversation(user)

    assert first.id == second.id


@pytest.mark.asyncio
async def test_process_agent_result_archives_when_threshold_exceeded(session, monkeypatch):
    service = ConversationService(session)
    user = await _bootstrap_user(session)
    conversation = await service.get_or_create_active_conversation(user)

    messages = _make_messages(pair_count=15)
    result = DummyResult(messages, total_tokens=200)

    monkeypatch.setattr(conversations_module, "ARCHIVE_TOKEN_THRESHOLD", 50)
    monkeypatch.setattr(conversations_module, "RECENT_MESSAGE_LIMIT", 4)

    async def summarizer(history):
        return f"summary({len(history)})"

    await service.process_agent_result(
        conversation,
        user=user,
        agent_result=result,
        history_record=None,
        summarizer=summarizer,
    )

    archive_stmt = select(ConversationArchive).where(
        ConversationArchive.conversation_id == conversation.id
    )
    archive = (await session.execute(archive_stmt)).scalar_one()
    assert archive.summary_text.startswith("summary")
    message_stmt = select(Message).where(Message.conversation_id == conversation.id)
    history_record = (await session.execute(message_stmt)).scalar_one()
    assert history_record.message_count == conversations_module.RECENT_MESSAGE_LIMIT


@pytest.mark.asyncio
async def test_process_agent_result_updates_history_without_archive(session, monkeypatch):
    service = ConversationService(session)
    user = await _bootstrap_user(session)
    conversation = await service.get_or_create_active_conversation(user)

    messages = _make_messages(pair_count=2)
    result = DummyResult(messages, total_tokens=10)
    monkeypatch.setattr(conversations_module, "ARCHIVE_TOKEN_THRESHOLD", 999999)

    async def summarizer(history):
        return "should-not-be-used"

    await service.process_agent_result(
        conversation,
        user=user,
        agent_result=result,
        history_record=None,
        summarizer=summarizer,
    )

    stmt = select(Message).where(Message.conversation_id == conversation.id)
    record = (await session.execute(stmt)).scalar_one()
    assert record.message_count == len(messages)


@pytest.mark.asyncio
async def test_store_manual_history(session):
    service = ConversationService(session)
    user = await _bootstrap_user(session)
    conversation = await service.get_or_create_active_conversation(user)

    messages = _make_messages(pair_count=1)
    await service.store_manual_history(conversation, user=user, messages=messages)

    stmt = select(Message).where(Message.conversation_id == conversation.id)
    record = (await session.execute(stmt)).scalar_one()
    assert record.message_count == len(messages)
