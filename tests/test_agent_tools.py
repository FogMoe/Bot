from __future__ import annotations

import pytest
from types import SimpleNamespace

from pydantic import SecretStr

from app.agents.toolkit import (
    FetchMarketSnapshotInput,
    FetchPermanentSummariesInput,
    fetch_market_snapshot_tool,
    fetch_permanent_summaries_tool,
    UpdateImpressionInput,
    update_impression_tool,
)
from app.db.models.core import Conversation, ConversationArchive, User
from app.config import ExternalToolSettings


def _ctx(session, user_id):
    return SimpleNamespace(deps=SimpleNamespace(session=session, user_id=user_id))


def _tool_ctx(http_client, tool_settings):
    return SimpleNamespace(
        deps=SimpleNamespace(http_client=http_client, tool_settings=tool_settings)
    )


class _SnapshotClient:
    def __init__(self, payload):
        self.payload = payload

    async def get(self, url, params=None, timeout=None):

        class _Response:
            status_code = 200
            text = "{}"
            headers = {}

            def __init__(self, payload):
                self._payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self._payload

        return _Response(self.payload)


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


@pytest.mark.asyncio
async def test_fetch_market_snapshot_tool():
    payload = {
        "gb_nvda": {
            "symbol": "gb_nvda",
            "name": "NVIDIA",
            "current_price": "1",
            "collection_timestamp": 100,
        },
        "btc_btcbtcusd": {
            "symbol": "btc_btcbtcusd",
            "name": "Bitcoin",
            "current_price": "2",
            "collection_timestamp": 200,
        },
    }

    ctx = _tool_ctx(
        _SnapshotClient(payload),
        ExternalToolSettings(),
    )

    data = FetchMarketSnapshotInput(query="nvda missing btc")
    result = await fetch_market_snapshot_tool(ctx, data)

    assert result.items
    # should only return up to 5 items but dataset has 2
    assert len(result.items) == 2
    assert {item.symbol for item in result.items} == {"gb_nvda", "btc_btcbtcusd"}
    assert "missing" in result.unmatched_tokens
    assert result.error_message is None


@pytest.mark.asyncio
async def test_fetch_market_snapshot_tool_handles_error():
    ctx = _tool_ctx(
        _SnapshotClient({}),
        ExternalToolSettings(),
    )

    data = FetchMarketSnapshotInput(query="nvda")
    result = await fetch_market_snapshot_tool(ctx, data)

    assert not result.items
    assert result.error_message
    assert "no data" in result.error_message.lower()
