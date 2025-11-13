"""Tests for subscription defaults."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.db.models.core import SubscriptionPlan, User
from app.services.subscriptions import SubscriptionService


def _stub_settings() -> SimpleNamespace:
    return SimpleNamespace(subscriptions=SimpleNamespace(subscription_duration_days=30))


async def _bootstrap_user_and_plan(session):
    plan = SubscriptionPlan(
        code="FREE",
        name="Free",
        description="Free tier",
        hourly_message_limit=10,
        monthly_price=0.0,
        priority=0,
        is_default=True,
    )
    user = User(telegram_id=12345, username="tester")
    session.add_all([plan, user])
    await session.flush()
    return user, plan


@pytest.mark.asyncio
async def test_ensure_default_subscription_creates_record(session):
    user, plan = await _bootstrap_user_and_plan(session)
    service = SubscriptionService(session, settings=_stub_settings())

    subscription = await service.ensure_default_subscription(user)

    assert subscription.plan_id == plan.id
    assert subscription.status == "active"
    assert subscription.expires_at is None

    # Idempotent
    again = await service.ensure_default_subscription(user)
    assert again.id == subscription.id


@pytest.mark.asyncio
async def test_get_hourly_limit_uses_default_plan(session):
    user, plan = await _bootstrap_user_and_plan(session)
    service = SubscriptionService(session, settings=_stub_settings())

    limit = await service.get_hourly_limit(user)

    assert limit == plan.hourly_message_limit
    active = await service.get_active_subscription(user)
    assert active is not None
    assert active.plan_id == plan.id
    assert active.plan is not None
    assert active.plan.hourly_message_limit == plan.hourly_message_limit
