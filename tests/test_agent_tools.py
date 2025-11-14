from __future__ import annotations

import pytest
from types import SimpleNamespace

from app.agents.toolkit import (
    FetchPermanentSummariesInput,
    fetch_permanent_summaries_tool,
    UpdateImpressionInput,
    update_impression_tool,
)
from app.db.models.core import Conversation, ConversationArchive, User


def _ctx(session, user_id):
    return SimpleNamespace(deps=SimpleNamespace(session=session, user_id=user_id))


@pytest.mark.asyncio
async def test_update_impression_tool(session):
    user = User(telegram_id=1, username="ctx", language_code="en")
    session.add(user)
    await session.flush()

    ctx = _ctx(session, user.id)
    payload = UpdateImpressionInput(impression="Friendly user")
    result = await update_impression_tool(ctx, payload)

    assert result.user_id == user.id
    assert result.impression == "Friendly user"
    assert "successfully" in result.message


@pytest.mark.asyncio
async def test_fetch_permanent_summaries_tool(session):
    user = User(telegram_id=2, username="ctx2", language_code="en")
    session.add(user)
    await session.flush()
    convo = Conversation(
        user_id=user.id,
        title="Chat",
        context_tokens=0,
        status="active",
    )
    session.add(convo)
    await session.flush()

    archive = ConversationArchive(
        conversation_id=convo.id,
        user_id=user.id,
        summary_text="Stored summary",
        history=[],
        token_count=10,
    )
    session.add(archive)
    await session.flush()

    ctx = _ctx(session, user.id)
    payload = FetchPermanentSummariesInput()
    result = await fetch_permanent_summaries_tool(ctx, payload)

    assert result.user_id == user.id
    assert result.total == 1
    assert result.records
    assert result.records[0].summary == "Stored summary"
