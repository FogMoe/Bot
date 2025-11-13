"""Tests covering MemoryService helpers."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models.core import Conversation, LongTermMemory, MemoryChunk, Message, User
from app.services.memory import MemoryService


async def _bootstrap_conversation(session):
    user = User(telegram_id=2222, username="mem-user")
    conversation = Conversation(user=user, title="Mem", context_tokens=0, status="active")
    session.add_all([user, conversation])
    await session.flush()
    return user, conversation


@pytest.mark.asyncio
async def test_create_and_fetch_memories(session):
    service = MemoryService(session)
    user, conversation = await _bootstrap_conversation(session)

    mem1 = await service.create_memory(
        user_id=user.id,
        conversation_id=conversation.id,
        source_message=None,
        content="first",
    )
    mem2 = await service.create_memory(
        user_id=user.id,
        conversation_id=conversation.id,
        source_message=None,
        content="second",
    )

    memories = await service.fetch_relevant_memories(user.id, limit=1)
    assert memories[0].id == mem2.id

    stmt = select(LongTermMemory).where(LongTermMemory.id == mem1.id)
    stored = (await session.execute(stmt)).scalar_one()
    assert stored.content == "first"


@pytest.mark.asyncio
async def test_flag_chunk_for_compression(session):
    service = MemoryService(session)
    user, conversation = await _bootstrap_conversation(session)

    start_msg = Message(
        conversation_id=conversation.id,
        user_id=user.id,
        history=[],
        total_tokens=10,
        message_count=1,
    )
    session.add(start_msg)
    await session.flush()

    chunk = await service.flag_chunk_for_compression(
        conversation.id,
        start=start_msg,
        end=start_msg,
        token_count=42,
    )

    stmt = select(MemoryChunk).where(MemoryChunk.id == chunk.id)
    stored = (await session.execute(stmt)).scalar_one()
    assert stored.state == "needs_compress"
    assert stored.token_count == 42
