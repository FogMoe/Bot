from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta

from app.db.models.core import Conversation, ConversationArchive, User
from app.services.user_insights import UserInsightService


def _make_user():
    return User(telegram_id=999, username="tester", language_code="en")


def _make_conversation(user_id: int, title: str = "Chat") -> Conversation:
    return Conversation(
        user_id=user_id,
        title=title,
        context_tokens=0,
        status="active",
    )


@pytest.mark.asyncio
async def test_upsert_impression_creates_and_updates(session):
    user = _make_user()
    session.add(user)
    await session.flush()

    service = UserInsightService(session)

    created = await service.upsert_impression(user.id, "Great helper")
    assert created.impression == "Great helper"

    updated = await service.upsert_impression(user.id, "Updated view")
    assert updated.impression == "Updated view"


@pytest.mark.asyncio
async def test_fetch_permanent_summaries_window(session):
    user = _make_user()
    session.add(user)
    await session.flush()
    convo1 = _make_conversation(user_id=user.id, title="Chat 1")
    convo2 = _make_conversation(user_id=user.id, title="Chat 2")
    session.add_all([convo1, convo2])
    await session.flush()

    now = datetime.now(timezone.utc)
    archive1 = ConversationArchive(
        conversation_id=convo1.id,
        user_id=user.id,
        summary_text="Most recent summary",
        history=[],
        token_count=10,
        created_at=now,
    )
    session.add(archive1)
    await session.flush()

    archive2 = ConversationArchive(
        conversation_id=convo2.id,
        user_id=user.id,
        summary_text="Older summary",
        history=[],
        token_count=8,
        created_at=now - timedelta(days=1),
    )
    session.add(archive2)
    await session.flush()

    service = UserInsightService(session)
    result = await service.fetch_permanent_summaries(user.id, start=1, end=5)

    assert result["total"] == 2
    assert result["range_start"] == 1
    assert result["range_end"] == 2
    assert len(result["records"]) == 2
    assert result["records"][0]["summary"] == "Most recent summary"
    assert result["records"][1]["summary"] == "Older summary"
