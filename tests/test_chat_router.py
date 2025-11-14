"""Tests for chat router commands with mocked dependencies."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from aiogram.types import ReactionTypeEmoji, ReactionTypeCustomEmoji

from sqlalchemy import select
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from app.bot.routers import chat as chat_router
from app.bot.routers.chat import (
    handle_announce,
    handle_activate,
    handle_chat,
    handle_help,
    handle_issue_card,
    handle_new_conversation,
    handle_status,
)
from app.db.models.core import Conversation, ConversationArchive, Message, SubscriptionCard, SubscriptionPlan, User
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
    assert "Hourly usage: 0/10" in text


@pytest.mark.asyncio
async def test_handle_help_returns_placeholder(session):
    user = User(telegram_id=140, username="helper", language_code="en")
    session.add(user)
    await session.flush()

    message = DummyMessage("/help", DummyFromUser(user_id=user.telegram_id))
    await handle_help(message, session, db_user=user)

    assert message.answers
    assert "/start" in message.answers[0][0]


def test_compose_reaction_text_handles_multiple():
    reactions = [ReactionTypeEmoji(emoji="👍"), ReactionTypeCustomEmoji(custom_emoji_id="abc123")]
    result = chat_router._compose_reaction_text(reactions)
    assert result == "👍:custom:abc123:"


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
async def test_handle_new_conversation_archives_and_starts_fresh(session):
    user = User(telegram_id=200, username="newcmd", language_code="en")
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

    conversation_service = chat_router.ConversationService(session)
    conversation = await conversation_service.get_or_create_active_conversation(user)
    messages = [
        ModelRequest(parts=[UserPromptPart(content="Hello there")]),
        ModelResponse(parts=[TextPart(content="Hi!")]),
    ]
    await conversation_service.store_manual_history(conversation, user=user, messages=messages)

    class FakeAgent:
        async def summarize_history(self, history):
            return "summary text"

    message = DummyMessage("/new", DummyFromUser(user_id=user.telegram_id))
    await handle_new_conversation(message, session, agent=FakeAgent(), db_user=user)

    texts = [text for text, _ in message.answers]
    assert any("Cleared" in text for text in texts)

    conversations = (await session.execute(select(Conversation))).scalars().all()
    assert len(conversations) == 2
    old = next(conv for conv in conversations if conv.id == conversation.id)
    assert old.status == "archived"
    active = next(conv for conv in conversations if conv.status == "active")
    assert active.id != old.id

    archive = (
        await session.execute(
            select(ConversationArchive).where(ConversationArchive.conversation_id == old.id)
        )
    ).scalar_one_or_none()
    assert archive is not None
    assert archive.summary_text == "summary text"

    old_history = (
        await session.execute(select(Message).where(Message.conversation_id == old.id))
    ).scalar_one_or_none()
    assert old_history is None

    new_history = (
        await session.execute(select(Message).where(Message.conversation_id == active.id))
    ).scalar_one_or_none()
    assert new_history is None


@pytest.mark.asyncio
async def test_handle_new_conversation_without_history(session):
    user = User(telegram_id=201, username="newcmd-empty", language_code="en")
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

    class FakeAgent:
        async def summarize_history(self, history):
            return "should not be called"

    message = DummyMessage("/new", DummyFromUser(user_id=user.telegram_id))
    await handle_new_conversation(message, session, agent=FakeAgent(), db_user=user)

    texts = [text for text, _ in message.answers]
    assert len(texts) == 1
    assert "fresh conversation" in texts[0]

    conversations = (await session.execute(select(Conversation))).scalars().all()
    assert len(conversations) == 2
    assert sum(1 for conv in conversations if conv.status == "active") == 1

    archives = (await session.execute(select(ConversationArchive))).scalars().all()
    assert len(archives) == 0


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
async def test_handle_issue_card_defaults_duration(session, monkeypatch):
    pro_plan = SubscriptionPlan(
        code="PRO",
        name="Pro",
        description="",
        hourly_message_limit=50,
        monthly_price=10.0,
        priority=10,
        is_default=False,
    )
    admin_user = User(telegram_id=501, username="admin2", language_code="en")
    session.add_all([pro_plan, admin_user])
    await session.flush()

    chat_router.settings.admin_telegram_id = admin_user.telegram_id
    monkeypatch.setattr(chat_router, "_generate_card_code", lambda plan_code: f"{plan_code}-CARD2")

    message = DummyMessage("/issuecard PRO", DummyFromUser(user_id=admin_user.telegram_id))
    await handle_issue_card(message, session, db_user=admin_user)

    card = (await session.execute(select(SubscriptionCard))).scalars().first()
    assert card is not None
    assert card.valid_days == chat_router.settings.subscriptions.subscription_duration_days


@pytest.mark.asyncio
async def test_handle_issue_card_unauthorized(session):
    chat_router.settings.admin_telegram_id = 999
    user = User(telegram_id=600, username="user", language_code="en")
    session.add(user)
    await session.flush()

    message = DummyMessage("/issuecard PRO", DummyFromUser(user_id=user.telegram_id))
    await handle_issue_card(message, session, db_user=user)

    assert message.answers and message.answers[0][0] == "Unauthorized"


@pytest.mark.asyncio
async def test_handle_announce_requires_admin(session):
    previous_admin = chat_router.settings.admin_telegram_id
    chat_router.settings.admin_telegram_id = 4242
    user = User(telegram_id=610, username="user", language_code="en")
    session.add(user)
    await session.flush()

    message = DummyMessage("/announce hello", DummyFromUser(user_id=user.telegram_id))
    try:
        await handle_announce(message, session, db_user=user)
    finally:
        chat_router.settings.admin_telegram_id = previous_admin

    assert message.answers and message.answers[0][0] == "Unauthorized"


@pytest.mark.asyncio
async def test_handle_announce_broadcasts(session, monkeypatch):
    previous_admin = chat_router.settings.admin_telegram_id
    admin = User(telegram_id=700, username="admin", language_code="en")
    active_user = User(telegram_id=701, username="active", language_code="en")
    pending_user = User(telegram_id=702, username="pending", language_code="en", status="pending")
    blocked_user = User(telegram_id=703, username="blocked", language_code="en", status="blocked")
    session.add_all([admin, active_user, pending_user, blocked_user])
    await session.flush()

    chat_router.settings.admin_telegram_id = admin.telegram_id
    sent_messages: list[tuple[int, str]] = []

    async def fake_send(bot, *, chat_id: int, text: str, parse_mode=None):  # type: ignore[override]
        sent_messages.append((chat_id, text))

    monkeypatch.setattr(chat_router, "bot_send_with_retry", fake_send)

    message = DummyMessage("/announce Maintenance window", DummyFromUser(user_id=admin.telegram_id))
    message.bot = object()

    try:
        await handle_announce(message, session, db_user=admin)
    finally:
        chat_router.settings.admin_telegram_id = previous_admin

    assert sent_messages == [
        (active_user.telegram_id, "Maintenance window"),
        (pending_user.telegram_id, "Maintenance window"),
    ]
    assert message.answers
    assert "Announcement sent to 2 users." in message.answers[0][0]
