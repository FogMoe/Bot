"""Tests for chat router commands with mocked dependencies."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from sqlalchemy import select

from app.bot.routers import chat as chat_router
from app.bot.routers.chat import (
    handle_activate,
    handle_chat,
    handle_issue_card,
    handle_status,
)
from app.db.models.core import SubscriptionCard, SubscriptionPlan, User
from app.services.exceptions import CardNotFound


class DummyMessage:
    def __init__(self, text: str, from_user, *, caption: str | None = None, reply_to_message=None):
        self.text = text
        self.caption = caption
        self.from_user = from_user
        self.reply_to_message = reply_to_message
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
async def test_handle_activate_usage_message(session):
    user = User(telegram_id=120, username="missing", language_code="en")
    session.add(user)
    await session.flush()

    message = DummyMessage("/activate", DummyFromUser(user_id=user.telegram_id))
    await handle_activate(message, session, db_user=user)

    assert message.answers and "Usage" in message.answers[0][0]


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
async def test_handle_status_shows_subscription(session):
    plan = SubscriptionPlan(
        code="FREE",
        name="Free",
        description="",
        hourly_message_limit=10,
        monthly_price=0.0,
        priority=0,
        is_default=True,
    )
    user = User(telegram_id=130, username="status", language_code="en")
    session.add_all([plan, user])
    await session.flush()

    message = DummyMessage("/status", DummyFromUser(user_id=user.telegram_id))
    await handle_status(message, session, db_user=user)

    assert message.answers
    text, _ = message.answers[0]
    assert "Plan: Free" in text
    assert "Status: Active" in text


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


@pytest.mark.asyncio
async def test_handle_chat_includes_reply_context(session, monkeypatch):
    user = User(telegram_id=115, username="chat", language_code="en")
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
        output="ack",
        all_messages=lambda: [],
        usage=lambda: SimpleNamespace(total_tokens=0),
    )

    class CapturingAgent:
        def __init__(self):
            self.last_user_message = None

        async def run(self, **kwargs):
            self.last_user_message = kwargs["latest_user_message"]
            return fake_agent_result

        async def summarize_history(self, history):
            return "summary"

    reply_message = SimpleNamespace(
        text="previous answer",
        caption=None,
        from_user=SimpleNamespace(is_bot=True),
    )
    message = DummyMessage(
        "follow up question",
        DummyFromUser(user_id=user.telegram_id),
        reply_to_message=reply_message,
    )
    agent = CapturingAgent()
    await handle_chat(message, session, agent, db_user=user)

    assert agent.last_user_message is not None
    assert agent.last_user_message.startswith('> Quote from Assistant: "previous answer"')
    assert agent.last_user_message.splitlines()[-1] == "follow up question"


@pytest.mark.asyncio
async def test_handle_chat_agent_error(session, monkeypatch):
    user = User(telegram_id=114, username="chat", language_code="en")
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

    class ExplodingAgent:
        async def run(self, **kwargs):
            raise RuntimeError("agent boom")

    message = DummyMessage("hello", DummyFromUser(user_id=user.telegram_id))
    with pytest.raises(RuntimeError):
        await handle_chat(message, session, ExplodingAgent(), db_user=user)

    assert message.answers and "Agent failed" in message.answers[0][0]


@pytest.mark.asyncio
async def test_handle_issue_card_success(session, monkeypatch):
    free_plan = SubscriptionPlan(
        code="FREE",
        name="Free",
        description="",
        hourly_message_limit=10,
        monthly_price=0.0,
        priority=0,
        is_default=True,
    )
    pro_plan = SubscriptionPlan(
        code="PRO",
        name="Pro",
        description="",
        hourly_message_limit=50,
        monthly_price=10.0,
        priority=10,
        is_default=False,
    )
    admin_user = User(telegram_id=500, username="admin", language_code="en")
    session.add_all([free_plan, pro_plan, admin_user])
    await session.flush()

    chat_router.settings.admin_telegram_id = admin_user.telegram_id
    monkeypatch.setattr(chat_router, "_generate_card_code", lambda plan_code: f"{plan_code}-CARD")

    message = DummyMessage("/issuecard PRO 15", DummyFromUser(user_id=admin_user.telegram_id))
    await handle_issue_card(message, session, db_user=admin_user)

    card = (await session.execute(select(SubscriptionCard))).scalars().first()
    assert card is not None and card.plan_id == pro_plan.id
    assert message.answers and "Card generated" in message.answers[0][0]


@pytest.mark.asyncio
async def test_handle_issue_card_unauthorized(session):
    chat_router.settings.admin_telegram_id = 999
    user = User(telegram_id=600, username="user", language_code="en")
    session.add(user)
    await session.flush()

    message = DummyMessage("/issuecard PRO", DummyFromUser(user_id=user.telegram_id))
    await handle_issue_card(message, session, db_user=user)

    assert message.answers and message.answers[0][0] == "Unauthorized"
