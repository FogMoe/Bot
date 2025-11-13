"""Tests covering card issuance and redemption flows."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.db.models.core import SubscriptionCard, SubscriptionPlan, User, UserSubscription
from app.services.subscriptions import SubscriptionService
from app.services.exceptions import CardNotFound
from app.utils.datetime import utc_now


def _settings(duration_days: int = 30) -> SimpleNamespace:
    return SimpleNamespace(subscriptions=SimpleNamespace(subscription_duration_days=duration_days))


async def _bootstrap_user_and_plan(session, *, priority: int = 0) -> tuple[User, SubscriptionPlan]:
    plan = SubscriptionPlan(
        code="PRO" if priority else "FREE",
        name="Plan",
        description="Test plan",
        hourly_message_limit=50,
        monthly_price=0.0,
        priority=priority,
        is_default=(priority == 0),
    )
    user = User(telegram_id=5555 + priority, username=f"user-{priority}")
    session.add_all([plan, user])
    await session.flush()
    return user, plan


def _card(plan_id: int, code: str, days: int = 10) -> SubscriptionCard:
    return SubscriptionCard(
        code=code,
        plan_id=plan_id,
        status="new",
        valid_days=days,
        expires_at=utc_now() + timedelta(days=30),
    )


@pytest.mark.asyncio
async def test_redeem_card_creates_new_subscription(session):
    user, plan = await _bootstrap_user_and_plan(session)
    service = SubscriptionService(session, settings=_settings())
    card = _card(plan.id, "CARD-NEW")
    session.add(card)
    await session.flush()

    subscription = await service.redeem_card(user, card.code)

    assert subscription.user_id == user.id
    assert subscription.plan_id == plan.id
    assert subscription.source_card_id == card.id
    assert subscription.status == "active"


@pytest.mark.asyncio
async def test_redeem_card_stacks_same_plan_duration(session):
    user, plan = await _bootstrap_user_and_plan(session)
    service = SubscriptionService(session, settings=_settings())

    first_card = _card(plan.id, "CARD-1", days=5)
    session.add(first_card)
    await session.flush()
    subscription = await service.redeem_card(user, first_card.code)

    assert subscription.expires_at is not None
    first_expiry = subscription.expires_at

    second_card = _card(plan.id, "CARD-2", days=3)
    session.add(second_card)
    await session.flush()
    stacked = await service.redeem_card(user, second_card.code)

    assert stacked.id == subscription.id
    assert stacked.expires_at > first_expiry


@pytest.mark.asyncio
async def test_redeem_card_rejects_invalid_code(session):
    user, plan = await _bootstrap_user_and_plan(session)
    service = SubscriptionService(session, settings=_settings())
    with pytest.raises(CardNotFound):
        await service.redeem_card(user, "UNKNOWN")
