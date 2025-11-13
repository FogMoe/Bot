"""Tests for middlewares and chat router entrypoints."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select
from aiogram.enums import MessageEntityType

from app.bot.middlewares.rate_limit import RateLimitMiddleware
from app.bot.middlewares.throttle import ThrottleMiddleware
from app.bot.middlewares.user_context import UserContextMiddleware
from app.bot.routers import chat as chat_router
from app.bot.routers.chat import handle_start
from app.db.models.core import SubscriptionPlan, User, UserSubscription


class DummyFromUser:
    def __init__(self, user_id: int = 1, full_name: str = "Test User", language_code: str = "en") -> None:
        self.id = user_id
        self.username = f"user{user_id}"
        self.first_name = full_name.split()[0]
        self.last_name = "".join(full_name.split()[1:]) or "User"
        self.language_code = language_code
        self.full_name = full_name


class DummyMessage:
    def __init__(self, text: str = "hi", from_user: DummyFromUser | None = None) -> None:
        self.text = text
        self.from_user = from_user or DummyFromUser()
        self.entities = []
        self.caption_entities = []
        self.answers: list[tuple[str, str | None]] = []
        self.chat = SimpleNamespace(type="private")

    async def answer(self, text: str, parse_mode: str | None = None):
        self.answers.append((text, parse_mode))
        return text


@pytest.fixture(autouse=True)
def stub_subscription_settings(monkeypatch):
    import app.services.subscriptions as subs_module

    settings = SimpleNamespace(subscriptions=SimpleNamespace(subscription_duration_days=30))
    monkeypatch.setattr(subs_module, "get_settings", lambda: settings)
    return settings


@pytest.fixture(autouse=True)
def patch_aiogram_message(monkeypatch):
    from app.bot.middlewares import throttle as throttle_module
    from app.bot.middlewares import rate_limit as rate_module

    monkeypatch.setattr(throttle_module, "Message", DummyMessage)
    monkeypatch.setattr(rate_module, "Message", DummyMessage)


@pytest.mark.asyncio
async def test_user_context_creates_user_and_subscription(session):
    middleware = UserContextMiddleware()
    plan = SubscriptionPlan(
        code="FREE",
        name="Free",
        description="",
        hourly_message_limit=10,
        monthly_price=0.0,
        priority=0,
        is_default=True,
    )
    session.add(plan)
    await session.flush()

    message = DummyMessage(from_user=DummyFromUser(user_id=10, full_name="New User"))
    data = {"session": session}
    handled = {}

    async def handler(event, ctx):
        handled["db_user"] = ctx["db_user"]
        return "ok"

    await middleware(handler, message, data)

    assert "db_user" in handled
    user = handled["db_user"]
    assert user.telegram_id == 10
    subs = (await session.execute(select(UserSubscription))).scalars().all()
    assert subs and subs[0].plan_id == plan.id


@pytest.mark.asyncio
async def test_user_context_blocks_group_chat(session):
    middleware = UserContextMiddleware()
    plan = SubscriptionPlan(
        code="FREE",
        name="Free",
        description="",
        hourly_message_limit=10,
        monthly_price=0.0,
        priority=0,
        is_default=True,
    )
    session.add(plan)
    await session.flush()

    message = DummyMessage(from_user=DummyFromUser(user_id=11))
    message.chat = SimpleNamespace(type="group")
    data = {"session": session}

    async def handler(event, ctx):
        raise AssertionError("Handler should not be called")

    await middleware(handler, message, data)

    assert message.answers
    assert "private chat" in message.answers[-1][0]


@pytest.mark.asyncio
async def test_throttle_blocks_excess_requests():
    settings = SimpleNamespace(request_limit=SimpleNamespace(interval_seconds=60, max_requests=1))
    middleware = ThrottleMiddleware(settings)
    message = DummyMessage(text="/start")
    handled = []

    async def handler(event, data):
        handled.append("called")
        return "ok"

    await middleware(handler, message, {})
    assert len(handled) == 1

    await middleware(handler, message, {})
    assert len(handled) == 1
    assert message.answers[-1][0].startswith("Too many")


@pytest.mark.asyncio
async def test_rate_limit_middleware_blocks_after_limit(session, stub_subscription_settings):
    plan = SubscriptionPlan(
        code="FREE",
        name="Free",
        description="",
        hourly_message_limit=1,
        monthly_price=0.0,
        priority=0,
        is_default=True,
    )
    user = User(telegram_id=77, username="limit_user", language_code="en")
    session.add_all([plan, user])
    await session.flush()

    settings = SimpleNamespace(
        default_language="en",
        request_limit=SimpleNamespace(interval_seconds=1, max_requests=5, window_retention_hours=1),
        subscriptions=stub_subscription_settings.subscriptions,
    )
    middleware = RateLimitMiddleware(settings)
    message = DummyMessage(text="hello", from_user=DummyFromUser(user_id=user.telegram_id))
    handled = []

    async def handler(event, data):
        handled.append(event.text)
        return "ok"

    data = {"session": session, "db_user": user}

    await middleware(handler, message, data)
    assert len(handled) == 1

    await middleware(handler, message, data)
    assert len(handled) == 1
    assert message.answers[-1][0].startswith("Hourly quota")


@pytest.mark.asyncio
async def test_handle_start_uses_subscription_plan(session, monkeypatch, stub_subscription_settings):
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
    user = User(telegram_id=999, username="pro_user", language_code="en")
    session.add_all([free_plan, pro_plan, user])
    await session.flush()

    subscription = UserSubscription(
        user_id=user.id,
        plan_id=pro_plan.id,
        status="active",
    )
    session.add(subscription)
    await session.flush()

    chat_settings = SimpleNamespace(default_language="en")
    monkeypatch.setattr(chat_router, "settings", chat_settings)

    message = DummyMessage(text="/start", from_user=DummyFromUser(full_name="Plan User"))
    await handle_start(message, session, db_user=user)

    assert message.answers
    assert "Pro" in message.answers[0][0]
