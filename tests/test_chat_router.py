"""Tests for chat router commands with mocked dependencies."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.bot.routers import chat as chat_router
from app.bot.routers.chat import handle_activate, handle_chat
from app.db.models.core import SubscriptionPlan, User
from app.services.exceptions import CardNotFound


class DummyMessage:
    def __init__(self, text: str, from_user):
        self.text = text
        self.from_user = from_user
        self.answers: list[tuple[str, str | None]] = []

    async def answer(self, text: str, parse_mode: str | None = None):
        self.answers.append((text, parse_mode))
        return text


class DummyFromUser:
    def __init__(self, user_id: int = 1, full_name: str = "Test User"):
        self.id = user_id
        self.full_name = full_name
        self.language_code = "en"


@pytest.mark.asyncio
async def test_handle_activate_success(session, monkeypatch):
    plan = SubscriptionPlan(
        code="PRO",
        name="Pro",
        description="",
        hourly_message_limit=50,
        monthly_price=10.0,
        priority=10,
        is_default=False,
    )
    user = User(telegram_id=111, username="activate", language_code="en")
    session.add_all([plan, user])
    await session.flush()

    class FakeSubscriptionService:
        def __init__(self, _session):
            self.session = _session

        async def redeem_card(self, db_user, code):
            subs = SimpleNamespace(plan_id=plan.id, expires_at=datetime.now(timezone.utc))
            subs.plan_id = plan.id
            subs.expires_at = datetime.now(timezone.utc)
            return subs

    monkeypatch.setattr(chat_router, "SubscriptionService", FakeSubscriptionService)
    message = DummyMessage("/activate CODE123", DummyFromUser(user_id=user.telegram_id))
    await handle_activate(message, session, db_user=user)

    assert any("Activated" in ans for ans, _ in message.answers)


@pytest.mark.asyncio
async def test_handle_activate_invalid(session, monkeypatch):
    user = User(telegram_id=112, username="activate", language_code="en")
    session.add(user)
    await session.flush()

    class FakeSubscriptionService:
        def __init__(self, _session):
            pass

        async def redeem_card(self, db_user, code):
            raise CardNotFound("invalid")

    monkeypatch.setattr(chat_router, "SubscriptionService", FakeSubscriptionService)
    message = DummyMessage("/activate BAD", DummyFromUser(user_id=user.telegram_id))
    await handle_activate(message, session, db_user=user)

    assert message.answers and "Invalid" in message.answers[0][0]


@pytest.mark.asyncio
async def test_handle_chat_happy_path(session, monkeypatch):
    user = User(telegram_id=113, username="chat", language_code="en")
    plan = SubscriptionPlan(
        code="FREE",
        name="Free",
        description="",
        hourly_message_limit=10,
        monthly_price=0.0,
        priority=0,
        is_default=True,
    )
    session.add_all([user, plan])
    await session.flush()

    fake_agent_result = SimpleNamespace(
        output="Hello there",
        all_messages=lambda: [],
        usage=lambda: SimpleNamespace(total_tokens=0),
    )

    class FakeAgent:
        async def run(self, **kwargs):
            return fake_agent_result

        async def summarize_history(self, history):
            return "summary"

    message = DummyMessage("hello", DummyFromUser(user_id=user.telegram_id))
    monkeypatch.setattr(chat_router, "ConversationService", chat_router.ConversationService)
    monkeypatch.setattr(chat_router, "MemoryService", chat_router.MemoryService)
    agent = FakeAgent()

    await handle_chat(message, session, agent, db_user=user)

    assert message.answers
    assert any("Hello" in ans for ans, _ in message.answers)
