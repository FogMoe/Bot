"""High-level integration tests covering core services working together."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from sqlalchemy import select

from app.db.models.core import ConversationArchive, SubscriptionCard, SubscriptionPlan, User
from app.services.conversations import ConversationService
from app.services.memory import MemoryService
from app.services.rate_limit import RateLimiter
from app.services.subscriptions import SubscriptionService
from app.services.exceptions import RateLimitExceeded
from app.utils.datetime import utc_now


def _settings(subscription_duration_days: int = 30) -> SimpleNamespace:
    return SimpleNamespace(subscriptions=SimpleNamespace(subscription_duration_days=subscription_duration_days))


async def _bootstrap_user_and_plans(session) -> User:
    user = User(telegram_id=9999, username="integration")
    free_plan = SubscriptionPlan(
        code="FREE",
        name="Free",
        description="Free tier",
        hourly_message_limit=5,
        monthly_price=0.0,
        priority=0,
        is_default=True,
    )
    pro_plan = SubscriptionPlan(
        code="PRO",
        name="Pro",
        description="Pro tier",
        hourly_message_limit=20,
        monthly_price=5.0,
        priority=10,
        is_default=False,
    )
    session.add_all([user, free_plan, pro_plan])
    await session.flush()
    return user


class DummyResult:
    def __init__(self, messages, total_tokens: int) -> None:
        self._messages = messages
        self._usage = SimpleNamespace(total_tokens=total_tokens)

    def all_messages(self):
        return self._messages

    def usage(self):
        return self._usage


def _messages():
    from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

    return [
        ModelRequest(parts=[UserPromptPart(content="hello")]),
        ModelResponse(parts=[TextPart(content="world")]),
    ]


@pytest.mark.asyncio
async def test_end_to_end_subscription_quota_and_memory_flow(session, monkeypatch):
    user = await _bootstrap_user_and_plans(session)
    subscription_service = SubscriptionService(session, settings=_settings())

    # Default FREE plan is provisioned automatically
    hourly_limit = await subscription_service.get_hourly_limit(user)
    assert hourly_limit == 5

    pro_plan = (
        await session.execute(select(SubscriptionPlan).where(SubscriptionPlan.code == "PRO"))
    ).scalar_one()

    # Redeem PRO card to upgrade subscription
    card = SubscriptionCard(
        code="PRO-CARD",
        plan_id=pro_plan.id,
        status="new",
        valid_days=15,
        expires_at=utc_now() + timedelta(days=30),
    )
    session.add(card)
    await session.flush()

    await subscription_service.redeem_card(user, card.code)
    hourly_limit = await subscription_service.get_hourly_limit(user)
    assert hourly_limit == 20

    # Rate limiting honours upgraded plan and cleans old windows
    limiter = RateLimiter(session, retention_hours=1)
    for _ in range(hourly_limit):
        await limiter.increment(user, hourly_limit)
    with pytest.raises(RateLimitExceeded):
        await limiter.increment(user, hourly_limit)

    # Conversation persistence and archiving
    conversation_service = ConversationService(session)
    conversation = await conversation_service.get_or_create_active_conversation(user)

    result = DummyResult(_messages() * 15, total_tokens=1000)
    monkeypatch.setattr("app.services.conversations.ARCHIVE_TOKEN_THRESHOLD", 50)
    async def summarizer(history):
        return f"summary({len(history)})"

    await conversation_service.process_agent_result(
        conversation,
        user=user,
        agent_result=result,
        history_record=None,
        summarizer=summarizer,
    )

    archive = (
        await session.execute(
            select(ConversationArchive).where(ConversationArchive.conversation_id == conversation.id)
        )
    ).scalar_one()
    assert archive.summary_text.startswith("summary")

    # Memory service stores learnings
    memory_service = MemoryService(session)
    history_record = await conversation_service.get_history_record(conversation)
    await memory_service.create_memory(
        user_id=user.id,
        conversation_id=conversation.id,
        source_message=history_record,
        content="remember this",
    )
    memories = await memory_service.fetch_relevant_memories(user.id)
    assert memories and memories[0].content == "remember this"
